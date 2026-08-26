import json
import os
import re
import time
from unittest.mock import MagicMock, patch

import pytest

from newsfeed.config import Config
from newsfeed.dedup import DedupStore
from newsfeed.fetcher import FetchError
from newsfeed.model import FetchedItem, FetchResult, MalformedEntry, SummarizeResult
from newsfeed.publisher import ArticlePublisher
from newsfeed.runner import JobFailedError, run
from newsfeed.summarizer import SummarizeError

_DUMMY_CFG = Config(
    google_cloud_project="unused-project",
    redis_url="redis://unused:6379",
    vertex_location="us-central1",
    news_article_collected_topic="unused-topic",
)
_REQUIRED_ENV = {
    "GOOGLE_CLOUD_PROJECT": "test-project",
    "VERTEX_LOCATION": "us-central1",
    "NEWS_ARTICLE_COLLECTED_TOPIC": "test-topic",
}


def _fixed_summarizer(raise_for_titles: frozenset[str] = frozenset()) -> MagicMock:
    """要約結果を固定した Summarizer の代用を組み立てる。

    Args:
        raise_for_titles: 要約を失敗させたい記事のタイトル集合。

    Returns:
        指定タイトル以外は固定の SummarizeResult を返す代用。
    """
    summarizer = MagicMock()

    def fake_summarize(title: str, body: str) -> SummarizeResult:
        if title in raise_for_titles:
            raise SummarizeError(f"summarization failed for {title}")
        return SummarizeResult(summary=f"summary of {title}", tags=[])

    summarizer.summarize.side_effect = fake_summarize
    return summarizer


def _pull_messages(subscriber_client, subscription_path: str, max_messages: int, timeout: float = 10) -> list:
    """subscription から最大 max_messages 件を受信し ack する。

    最初に受信できた 1 回分の応答をそのまま結果として返す。応答が届くまで
    (emulator への伝播待ちのため) 短い間隔で pull をリトライするが、既に
    届いた分より多く集めようと ack 前に pull を繰り返すと同じ未 ack
    メッセージが再配送されるため、複数回の pull にまたがって集計しない。

    Args:
        subscriber_client: pull に使う subscriber クライアント。
        subscription_path: 対象の subscription。
        max_messages: 受信を試みる最大件数。
        timeout: 受信を待つ最大秒数。

    Returns:
        受信した received_messages の一覧 (max_messages 未満のこともある)。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = subscriber_client.pull(
            request={"subscription": subscription_path, "max_messages": max_messages},
            timeout=2,
        )
        if response.received_messages:
            subscriber_client.acknowledge(
                request={
                    "subscription": subscription_path,
                    "ack_ids": [m.ack_id for m in response.received_messages],
                },
            )
            return response.received_messages
    return []


def _source_url(received_message) -> str:
    """受信メッセージのペイロードから元記事の URL を取り出す。

    Args:
        received_message: pull で受信した ReceivedMessage。

    Returns:
        ペイロードの source_url。
    """
    return json.loads(received_message.message.data)["source_url"]


def _assert_no_message_published(subscriber_client, subscription_path: str) -> None:
    """subscription に一定時間待ってもメッセージが届かないことを確認する。

    Args:
        subscriber_client: pull に使う subscriber クライアント。
        subscription_path: 対象の subscription。
    """
    response = subscriber_client.pull(
        request={"subscription": subscription_path, "max_messages": 10}, timeout=3,
    )
    assert response.received_messages == []


class Test記事の処理と配信:
    def test_未処理の記事が1件取得できたとき要約結果を反映したイベントが配信され元記事URLと一致する(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/new", title="New", body="body")],
            failed_sources=[],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(), publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        received = _pull_messages(subscriber, subscription_path, max_messages=1)
        assert len(received) == 1
        assert _source_url(received[0]) == "https://example.com/new"

    def test_処理済みと未処理が両方取得できたとき未処理の記事のイベントのみ配信される(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        dedup.reserve("https://example.com/seen")
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[
                FetchedItem(source="aws", source_url="https://example.com/seen", title="Seen", body="body"),
                FetchedItem(source="aws", source_url="https://example.com/new", title="New", body="body"),
            ],
            failed_sources=[],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(), publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        received = _pull_messages(subscriber, subscription_path, max_messages=2)
        assert len(received) == 1
        assert _source_url(received[0]) == "https://example.com/new"

    def test_記事の要約が失敗したときその記事は配信されず次に処理すると再び未処理として扱われる(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/fail", title="Fail", body="body")],
            failed_sources=[],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched), pytest.raises(JobFailedError):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(raise_for_titles=frozenset({"Fail"})),
                publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        _assert_no_message_published(subscriber, subscription_path)
        assert dedup.reserve("https://example.com/fail") is True

    def test_記事の配信が失敗したとき次に処理すると再び未処理として扱われる(self, redis_client, pubsub_emulator, pubsub_topic):
        project_id, _topic_name, _subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        failing_publisher = ArticlePublisher(
            project_id, "topic-that-does-not-exist", client=pubsub_emulator.get_publisher_client(),
        )
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/fail", title="Fail", body="body")],
            failed_sources=[],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched), pytest.raises(JobFailedError):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(), publisher=failing_publisher)

        assert dedup.reserve("https://example.com/fail") is True


class Test処理失敗のジョブ終了:
    def test_記事の要約または配信が1件以上失敗したとき全ての記事の処理を終えてから失敗件数を含む例外になる(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[
                FetchedItem(source="aws", source_url="https://example.com/fail", title="Fail", body="body"),
                FetchedItem(source="aws", source_url="https://example.com/ok", title="Ok", body="body"),
            ],
            failed_sources=[],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched), \
                pytest.raises(JobFailedError, match=re.escape("1 article(s) failed to process")):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(raise_for_titles=frozenset({"Fail"})),
                publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        received = _pull_messages(subscriber, subscription_path, max_messages=1)
        assert len(received) == 1
        assert _source_url(received[0]) == "https://example.com/ok"

    def test_取得元の一部のソースが失敗し他から正常に取得できたとき正常な記事は配信され失敗件数を含む例外になる(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/ok", title="Ok", body="body")],
            failed_sources=["azure"],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched), \
                pytest.raises(JobFailedError, match=re.escape("1 feed source(s) failed to fetch: azure")):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(), publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        received = _pull_messages(subscriber, subscription_path, max_messages=1)
        assert len(received) == 1
        assert _source_url(received[0]) == "https://example.com/ok"

    def test_本文が空で処理できなかった記事があったとき他の正常な記事は処理されつつ失敗件数を含む例外になる(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/ok", title="Ok", body="body")],
            failed_sources=[],
            malformed_entries=[MalformedEntry(source="aws", title="Broken Article")],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched), \
                pytest.raises(
                    JobFailedError,
                    match=re.escape("1 entry(ies) skipped for empty body: aws:Broken Article"),
                ):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(), publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        received = _pull_messages(subscriber, subscription_path, max_messages=1)
        assert len(received) == 1
        assert _source_url(received[0]) == "https://example.com/ok"

    def test_記事処理の失敗とソースの失敗と本文欠落が同時に起きたとき例外に全ての件数が含まれる(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, _subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/fail", title="Fail", body="body")],
            failed_sources=["azure"],
            malformed_entries=[MalformedEntry(source="aws", title="Broken Article")],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched), pytest.raises(JobFailedError) as excinfo:
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(raise_for_titles=frozenset({"Fail"})),
                publisher=publisher)

        message = str(excinfo.value)
        assert "1 feed source(s) failed to fetch: azure" in message
        assert "1 entry(ies) skipped for empty body: aws:Broken Article" in message
        assert "1 article(s) failed to process" in message

    def test_取得元の全てのソースが失敗したとき記事の処理を1件も行う前に取得自体の失敗を理由とする例外になる(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())

        with patch("newsfeed.runner.fetch_all", side_effect=FetchError("all sources failed")), \
                pytest.raises(FetchError):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(), publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        _assert_no_message_published(subscriber, subscription_path)

    def test_ソースの失敗も記事処理の失敗も本文欠落エントリも無かったとき例外を送出せずに終了する(
        self, redis_client, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        dedup = DedupStore(redis_client)
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/ok", title="Ok", body="body")],
            failed_sources=[],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched):
            run(cfg=_DUMMY_CFG, dedup=dedup, summarizer=_fixed_summarizer(), publisher=publisher)

        subscriber = pubsub_emulator.get_subscriber_client()
        received = _pull_messages(subscriber, subscription_path, max_messages=1)
        assert len(received) == 1


class Test環境変数からの設定読み込み:
    @pytest.mark.parametrize(
        "env, missing_var",
        [
            pytest.param({}, "GOOGLE_CLOUD_PROJECT", id="GOOGLE_CLOUD_PROJECTが未設定のとき"),
            pytest.param(
                {"GOOGLE_CLOUD_PROJECT": "test-project"},
                "VERTEX_LOCATION",
                id="GOOGLE_CLOUD_PROJECTのみ設定されVERTEX_LOCATIONが未設定のとき",
            ),
            pytest.param(
                {"GOOGLE_CLOUD_PROJECT": "test-project", "VERTEX_LOCATION": "us-central1"},
                "NEWS_ARTICLE_COLLECTED_TOPIC",
                id="GOOGLE_CLOUD_PROJECTとVERTEX_LOCATIONのみ設定されNEWS_ARTICLE_COLLECTED_TOPICが未設定のとき",
            ),
            pytest.param(
                {**_REQUIRED_ENV, "APP_ENV": "local"},
                "UPSTASH_REDIS_URL",
                id="APP_ENVがlocalでUPSTASH_REDIS_URLが未設定のとき",
            ),
        ],
    )
    def test_設定を指定せず必須の環境変数が未設定のとき未設定の環境変数名を理由とするエラーになる(self, env, missing_var):
        with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError, match=missing_var):
            run()


class Test実接続の組み立て:
    def test_重複排除の予約先と配信先を指定しないとき設定の接続情報に基づいて重複排除の予約と記事の配信が実際に行われる(
        self, monkeypatch, redis_client, valkey_url, pubsub_emulator, pubsub_topic,
    ):
        project_id, topic_name, subscription_path = pubsub_topic
        monkeypatch.setenv("PUBSUB_EMULATOR_HOST", pubsub_emulator.get_pubsub_emulator_host())
        cfg = Config(
            google_cloud_project=project_id,
            redis_url=valkey_url,
            vertex_location="us-central1",
            news_article_collected_topic=topic_name,
        )
        fetched = FetchResult(
            items=[FetchedItem(source="aws", source_url="https://example.com/wired", title="Wired", body="body")],
            failed_sources=[],
            malformed_entries=[],
        )

        with patch("newsfeed.runner.fetch_all", return_value=fetched):
            run(cfg=cfg, summarizer=_fixed_summarizer())

        assert redis_client.keys("*") != []
        subscriber = pubsub_emulator.get_subscriber_client()
        received = _pull_messages(subscriber, subscription_path, max_messages=1)
        assert len(received) == 1
        assert _source_url(received[0]) == "https://example.com/wired"
