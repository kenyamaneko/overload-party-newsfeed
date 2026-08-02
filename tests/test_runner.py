from unittest.mock import MagicMock, patch

import pytest

from newsfeed.dedup import DedupStore
from newsfeed.model import FetchedItem, FetchResult, MalformedEntry, SummarizeResult
from newsfeed.publisher import PublishError
from newsfeed.runner import JobFailedError, _fetch_and_publish
from newsfeed.summarizer import SummarizeError


def _item(n: int) -> FetchedItem:
    return FetchedItem(
        source="aws",
        source_url=f"https://example.com/{n}",
        title=f"Article {n}",
        body=f"body{n}",
    )


def _fetched(items, failed_sources=None, malformed_entries=None) -> FetchResult:
    """記事と失敗から fetch_all の戻り値を組み立てる。

    Args:
        items: 取得できた記事。
        failed_sources: 取得に失敗したソース名。省略時は失敗なし。
        malformed_entries: 本文が空でスキップしたエントリ。省略時はスキップなし。

    Returns:
        fetch_all が返す形の FetchResult。
    """
    return FetchResult(
        items=items,
        failed_sources=failed_sources or [],
        malformed_entries=malformed_entries or [],
    )


def _summarizer(summary: str = "要約", tags=None) -> MagicMock:
    m = MagicMock()
    m.summarize.return_value = SummarizeResult(summary=summary, tags=tags or [])
    return m


class _RecordingPublisher:
    """publish された event を記録するだけの fake。"""

    def __init__(self) -> None:
        self.published_events: list = []

    def publish(self, event) -> None:
        self.published_events.append(event)


@pytest.fixture
def dedup_store(redis_client) -> DedupStore:
    return DedupStore(redis_client)


class Test取得から配信までの処理:
    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_新規記事は予約後にpublishされ予約マーカーが実Redisに残る(self, mock_ulid, mock_fetch_all, dedup_store):
        mock_fetch_all.return_value = _fetched([_item(1)])
        mock_ulid.return_value = "01ABC"

        summarizer = _summarizer()
        publisher = _RecordingPublisher()

        _fetch_and_publish(dedup_store, summarizer, publisher)

        assert [e.source_url for e in publisher.published_events] == ["https://example.com/1"]
        # reserve() の再呼び出しが False を返すことで、予約マーカーが実際に残っていることを確認する
        assert dedup_store.reserve("https://example.com/1") is False

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_予約済みの記事と新規記事が混在するとき新規記事のみpublishされる(self, mock_ulid, mock_fetch_all, dedup_store):
        # 1 件目を事前に予約済み (= 既見) にしておく
        dedup_store.reserve("https://example.com/1")

        mock_fetch_all.return_value = _fetched([_item(1), _item(2)])
        mock_ulid.return_value = "01ABC"

        summarizer = _summarizer()
        publisher = _RecordingPublisher()

        _fetch_and_publish(dedup_store, summarizer, publisher)

        assert [e.source_url for e in publisher.published_events] == ["https://example.com/2"]

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_要約失敗時はマーカーを解放する(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = _fetched([_item(1)])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = MagicMock()
        summarizer.summarize.side_effect = SummarizeError("vertex down")
        publisher = MagicMock()

        with pytest.raises(JobFailedError, match="1 article\\(s\\) failed to process"):
            _fetch_and_publish(dedup, summarizer, publisher)

        dedup.release.assert_called_once_with("https://example.com/1")
        publisher.publish.assert_not_called()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_publish失敗時はマーカーを解放する(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = _fetched([_item(1)])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()
        publisher.publish.side_effect = PublishError("pubsub down")

        with pytest.raises(JobFailedError, match="1 article\\(s\\) failed to process"):
            _fetch_and_publish(dedup, summarizer, publisher)

        dedup.release.assert_called_once_with("https://example.com/1")

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_個別失敗後も残りの記事の処理を継続する(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = _fetched([_item(1), _item(2), _item(3)])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()
        publisher.publish.side_effect = [PublishError("fail"), None, None]

        with pytest.raises(JobFailedError, match="1 article\\(s\\) failed to process"):
            _fetch_and_publish(dedup, summarizer, publisher)

        # 1 件失敗後も残り 2 件の publish が試行される
        assert publisher.publish.call_count == 3

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_1件目の要約が失敗したとき1件目は飛ばされ2件目がpublishされる(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = _fetched([_item(1), _item(2)])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = MagicMock()
        summarizer.summarize.side_effect = [
            SummarizeError("vertex down"),
            SummarizeResult(summary="要約", tags=[]),
        ]
        publisher = _RecordingPublisher()

        with pytest.raises(JobFailedError, match="1 article\\(s\\) failed to process"):
            _fetch_and_publish(dedup, summarizer, publisher)

        assert [e.source_url for e in publisher.published_events] == ["https://example.com/2"]

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_記事の処理で想定外の失敗が起きたとき残りの記事を処理せず呼び出し元へ送出する(
        self, mock_ulid, mock_fetch_all,
    ):
        mock_fetch_all.return_value = _fetched([_item(1), _item(2)])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = MagicMock()
        summarizer.summarize.side_effect = AttributeError("summarizer is misconfigured")
        publisher = _RecordingPublisher()

        with pytest.raises(AttributeError, match="summarizer is misconfigured"):
            _fetch_and_publish(dedup, summarizer, publisher)

        assert publisher.published_events == []
        dedup.release.assert_not_called()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_全件成功時は各記事をpublishしマーカーを解放しない(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = _fetched([_item(1), _item(2)])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        assert publisher.publish.call_count == 2
        dedup.release.assert_not_called()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_イベントに要約とタグを載せる(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = _fetched([_item(1)])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer(summary="要約テキスト", tags=["ai", "compute"])
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        event = publisher.publish.call_args[0][0]
        assert event.article_id == "01ABC"
        assert event.summary == "要約テキスト"
        assert event.tags == ["ai", "compute"]
        assert event.title == "Article 1"
        assert event.body == "body1"

    @patch("newsfeed.runner.fetch_all")
    def test_取得記事が0件のとき要約も配信も行われず正常終了する(self, mock_fetch_all):
        mock_fetch_all.return_value = _fetched([])

        dedup = MagicMock()
        summarizer = _summarizer()
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        summarizer.summarize.assert_not_called()
        publisher.publish.assert_not_called()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_一部のソース取得に失敗したとき成功分をpublishした上でジョブを失敗させる(
        self, mock_ulid, mock_fetch_all,
    ):
        mock_fetch_all.return_value = _fetched([_item(1)], failed_sources=["azure", "oci"])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = _RecordingPublisher()

        with pytest.raises(JobFailedError, match="2 feed source\\(s\\) failed to fetch: azure, oci"):
            _fetch_and_publish(dedup, summarizer, publisher)

        assert [e.source_url for e in publisher.published_events] == ["https://example.com/1"]

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_本文が空でスキップした記事があったとき残りをpublishした上でジョブを失敗させる(
        self, mock_ulid, mock_fetch_all,
    ):
        mock_fetch_all.return_value = _fetched(
            [_item(1)],
            malformed_entries=[MalformedEntry(source="aws", title="Broken Article")],
        )
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = _RecordingPublisher()

        with pytest.raises(
            JobFailedError,
            match=r"1 entry\(ies\) skipped for empty body: aws:Broken Article",
        ):
            _fetch_and_publish(dedup, summarizer, publisher)

        assert [e.source_url for e in publisher.published_events] == ["https://example.com/1"]

    @patch("newsfeed.runner.fetch_all")
    def test_全記事の本文が空で取得記事が0件のときジョブを失敗させる(self, mock_fetch_all):
        mock_fetch_all.return_value = _fetched(
            [],
            malformed_entries=[
                MalformedEntry(source="aws", title="Broken Article"),
                MalformedEntry(source="azure", title="Another Broken Article"),
            ],
        )

        dedup = MagicMock()
        summarizer = _summarizer()
        publisher = MagicMock()

        with pytest.raises(
            JobFailedError,
            match=r"2 entry\(ies\) skipped for empty body: "
                  r"aws:Broken Article, azure:Another Broken Article",
        ):
            _fetch_and_publish(dedup, summarizer, publisher)

        publisher.publish.assert_not_called()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_ソース取得失敗と本文が空の記事が同時にあるときどちらの原因もエラーに出る(
        self, mock_ulid, mock_fetch_all,
    ):
        mock_fetch_all.return_value = _fetched(
            [_item(1)],
            failed_sources=["azure"],
            malformed_entries=[MalformedEntry(source="aws", title="Broken Article")],
        )
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()

        with pytest.raises(JobFailedError) as excinfo:
            _fetch_and_publish(dedup, summarizer, publisher)

        assert "1 feed source(s) failed to fetch: azure" in str(excinfo.value)
        assert "1 entry(ies) skipped for empty body: aws:Broken Article" in str(excinfo.value)

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_ソース取得と記事処理が両方失敗したときどちらの原因もエラーに出る(
        self, mock_ulid, mock_fetch_all,
    ):
        mock_fetch_all.return_value = _fetched([_item(1)], failed_sources=["azure"])
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()
        publisher.publish.side_effect = PublishError("pubsub down")

        with pytest.raises(JobFailedError) as excinfo:
            _fetch_and_publish(dedup, summarizer, publisher)

        assert "1 feed source(s) failed to fetch: azure" in str(excinfo.value)
        assert "1 article(s) failed to process" in str(excinfo.value)
