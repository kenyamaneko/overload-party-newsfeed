import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from newsfeed.model import ArticleEvent
from newsfeed.publisher import ArticlePublisher, PublishError

_TOPIC_NAME = "test-topic"


def _event(**overrides) -> ArticleEvent:
    defaults = {
        "article_id": "01ABC",
        "source": "aws",
        "source_url": "https://example.com/a",
        "tags": ["ai"],
        "title": "Title",
        "summary": "Summary",
        "body": "body",
    }
    defaults.update(overrides)
    return ArticleEvent(**defaults)


class TestArticlePublisherによる配信:
    def test_publishしたイベントが設定されたトピックに実配信される(self, pubsub_emulator, pubsub_topic):
        project_id, topic, subscription_path = pubsub_topic
        publisher_client = pubsub_emulator.get_publisher_client()
        subscriber_client = pubsub_emulator.get_subscriber_client()

        publisher = ArticlePublisher(project_id, topic, client=publisher_client)
        publisher.publish(_event(source_url="https://example.com/delivered"))

        response = subscriber_client.pull(
            request={"subscription": subscription_path, "max_messages": 1},
            timeout=10,
        )

        assert len(response.received_messages) == 1
        decoded = json.loads(response.received_messages[0].message.data.decode("utf-8"))
        assert decoded["source_url"] == "https://example.com/delivered"

    def test_payloadがnewsのArticleCollectedEvent契約と一致する(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", _TOPIC_NAME, client=client)
        publisher.publish(_event(
            article_id="01ABC",
            source="aws",
            source_url="https://example.com/a",
            tags=["ai", "compute"],
            title="Title",
            summary="Summary",
            body="body",
            source_published_at=datetime(2026, 4, 21, 10, 30, tzinfo=timezone.utc),
        ))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert decoded["article_id"] == "01ABC"
        assert decoded["source"] == "aws"
        assert decoded["source_url"] == "https://example.com/a"
        assert decoded["tags"] == ["ai", "compute"]
        assert decoded["source_published_at"] == "2026-04-21T10:30:00Z"
        assert decoded["translations"] == [
            {
                "lang": "ja",
                "title": "Title",
                "summary": "Summary",
                "body": "body",
            }
        ]

    def test_イベントをUTF8のJSONとして直列化する(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", _TOPIC_NAME, client=client)
        publisher.publish(_event(title="日本語タイトル"))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert decoded["translations"][0]["title"] == "日本語タイトル"

    def test_source_published_atがNoneのとき出力から省く(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", _TOPIC_NAME, client=client)
        publisher.publish(_event(source_published_at=None))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert "source_published_at" not in decoded

    def test_存在しないトピックへ配信すると配信の失敗になる(self, pubsub_emulator):
        publisher_client = pubsub_emulator.get_publisher_client()

        publisher = ArticlePublisher(
            f"test-{uuid.uuid4().hex}", _TOPIC_NAME, client=publisher_client,
        )
        with pytest.raises(PublishError) as excinfo:
            publisher.publish(_event(article_id="01XYZ"))

        assert "failed to publish 01XYZ" in str(excinfo.value)
        assert "not found" in str(excinfo.value).lower()

    def test_langをenに上書きしたイベントを配信するとtranslationsのlangがenになる(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", _TOPIC_NAME, client=client)
        publisher.publish(_event(lang="en"))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert decoded["translations"][0]["lang"] == "en"
