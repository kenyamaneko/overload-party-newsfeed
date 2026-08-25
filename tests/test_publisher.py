import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import GoogleAPIError

from newsfeed.model import ArticleEvent
from newsfeed.publisher import ArticlePublisher, PublishError

_PULL_TIMEOUT_SECONDS = 10


def _pull_one_message(subscriber_client, subscription_path: str) -> dict:
    """subscription から 1 件のメッセージを取得し、JSON として復号する。

    Args:
        subscriber_client: pull に使う subscriber クライアント。
        subscription_path: 対象の subscription。

    Returns:
        受信したメッセージのペイロードを JSON デコードした辞書。
    """
    response = subscriber_client.pull(
        request={"subscription": subscription_path, "max_messages": 1},
        timeout=_PULL_TIMEOUT_SECONDS,
    )
    assert len(response.received_messages) == 1
    received = response.received_messages[0]
    subscriber_client.acknowledge(
        request={"subscription": subscription_path, "ack_ids": [received.ack_id]},
    )
    return json.loads(received.message.data)


class Test記事イベントのpublish:
    def test_publishすると指定したプロジェクトとトピック宛てに送信され購読側で受信できる(self, pubsub_emulator, pubsub_topic):
        project_id, topic_name, subscription_path = pubsub_topic
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        event = ArticleEvent(
            article_id="article-1",
            source="aws",
            source_url="https://example.com/article-1",
            tags=["compute"],
            title="T",
            summary="S",
            body="B",
        )

        publisher.publish(event)

        subscriber = pubsub_emulator.get_subscriber_client()
        payload = _pull_one_message(subscriber, subscription_path)
        assert payload["source_url"] == "https://example.com/article-1"

    def test_受信したメッセージは記事IDソース名URLタグと1要素のtranslationsを持つ(self, pubsub_emulator, pubsub_topic):
        project_id, topic_name, subscription_path = pubsub_topic
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        event = ArticleEvent(
            article_id="article-2",
            source="azure",
            source_url="https://example.com/article-2",
            tags=["compute", "network"],
            title="タイトル",
            summary="要約",
            body="本文",
            lang="ja",
        )

        publisher.publish(event)

        subscriber = pubsub_emulator.get_subscriber_client()
        payload = _pull_one_message(subscriber, subscription_path)
        assert payload["article_id"] == "article-2"
        assert payload["source"] == "azure"
        assert payload["source_url"] == "https://example.com/article-2"
        assert payload["tags"] == ["compute", "network"]
        assert payload["translations"] == [
            {"lang": "ja", "title": "タイトル", "summary": "要約", "body": "本文"},
        ]

    def test_記事に公開日時が設定されているとき末尾Z付きのUTC日時文字列が含まれる(self, pubsub_emulator, pubsub_topic):
        project_id, topic_name, subscription_path = pubsub_topic
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        event = ArticleEvent(
            article_id="article-3",
            source="aws",
            source_url="https://example.com/article-3",
            tags=[],
            title="T",
            summary="S",
            body="B",
            source_published_at=datetime(2024, 6, 1, 9, 15, 0, tzinfo=timezone.utc),
        )

        publisher.publish(event)

        subscriber = pubsub_emulator.get_subscriber_client()
        payload = _pull_one_message(subscriber, subscription_path)
        assert payload["source_published_at"] == "2024-06-01T09:15:00Z"

    def test_記事に公開日時が設定されていないとき公開日時の項目は含まれない(self, pubsub_emulator, pubsub_topic):
        project_id, topic_name, subscription_path = pubsub_topic
        publisher = ArticlePublisher(project_id, topic_name, client=pubsub_emulator.get_publisher_client())
        event = ArticleEvent(
            article_id="article-4",
            source="aws",
            source_url="https://example.com/article-4",
            tags=[],
            title="T",
            summary="S",
            body="B",
            source_published_at=None,
        )

        publisher.publish(event)

        subscriber = pubsub_emulator.get_subscriber_client()
        payload = _pull_one_message(subscriber, subscription_path)
        assert "source_published_at" not in payload

    def test_送信自体が失敗したとき記事IDを含む例外で失敗する(self):
        client = MagicMock()
        future = MagicMock()
        future.result.side_effect = GoogleAPIError("pubsub unavailable")
        client.publish.return_value = future
        publisher = ArticlePublisher("test-project", "test-topic", client=client)
        event = ArticleEvent(
            article_id="article-99",
            source="aws",
            source_url="https://example.com/article-99",
            tags=[],
            title="T",
            summary="S",
            body="B",
        )

        with pytest.raises(PublishError, match="article-99"):
            publisher.publish(event)
