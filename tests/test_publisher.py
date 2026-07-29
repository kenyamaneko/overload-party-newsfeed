import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from newsfeed.model import ArticleEvent
from newsfeed.publisher import TOPIC_NAME, ArticlePublisher


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
    def test_設定されたトピックにpublishする(self):
        client = MagicMock()
        client.topic_path.return_value = "projects/my-project/topics/" + TOPIC_NAME
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event())

        client.topic_path.assert_called_once_with("my-project", TOPIC_NAME)
        assert client.publish.call_args[0][0] == "projects/my-project/topics/" + TOPIC_NAME

    def test_payloadがnewsのArticleCollectedEvent契約と一致する(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
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

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event(title="日本語タイトル"))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert decoded["translations"][0]["title"] == "日本語タイトル"

    def test_source_published_atがNoneのとき出力から省く(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event(source_published_at=None))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert "source_published_at" not in decoded

    def test_publish失敗時は例外を伝播する(self):
        client = MagicMock()
        client.publish.return_value.result.side_effect = RuntimeError("ack timeout")

        publisher = ArticlePublisher("my-project", client=client)
        with pytest.raises(RuntimeError, match="ack timeout"):
            publisher.publish(_event())

    def test_langをenに上書きしたイベントを配信するとtranslationsのlangがenになる(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event(lang="en"))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert decoded["translations"][0]["lang"] == "en"
