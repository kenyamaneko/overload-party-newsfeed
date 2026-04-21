import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from newsfeed.model import ArticleEvent
from newsfeed.publisher import TOPIC_NAME, ArticlePublisher


def _event(**overrides) -> ArticleEvent:
    defaults = dict(
        article_id="01ABC",
        source="aws",
        source_url="https://example.com/a",
        title="Title",
        body="body",
    )
    defaults.update(overrides)
    return ArticleEvent(**defaults)


class TestArticlePublisher:
    def test_publishes_to_configured_topic(self):
        client = MagicMock()
        client.topic_path.return_value = "projects/my-project/topics/" + TOPIC_NAME
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event())

        client.topic_path.assert_called_once_with("my-project", TOPIC_NAME)
        assert client.publish.call_args[0][0] == "projects/my-project/topics/" + TOPIC_NAME

    def test_serializes_event_as_utf8_json(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event(title="日本語タイトル"))

        data: bytes = client.publish.call_args[0][1]
        decoded = json.loads(data.decode("utf-8"))
        assert decoded["title"] == "日本語タイトル"

    def test_omits_source_published_at_when_none(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event(source_published_at=None))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert "source_published_at" not in decoded

    def test_source_published_at_serialized_as_rfc3339_z(self):
        client = MagicMock()
        client.publish.return_value.result.return_value = "msg-id"

        publisher = ArticlePublisher("my-project", client=client)
        publisher.publish(_event(
            source_published_at=datetime(2026, 4, 21, 10, 30, 0, tzinfo=timezone.utc),
        ))

        decoded = json.loads(client.publish.call_args[0][1].decode("utf-8"))
        assert decoded["source_published_at"] == "2026-04-21T10:30:00Z"

    def test_publish_failure_propagates_exception(self):
        client = MagicMock()
        client.publish.return_value.result.side_effect = RuntimeError("ack timeout")

        publisher = ArticlePublisher("my-project", client=client)
        import pytest
        with pytest.raises(RuntimeError, match="ack timeout"):
            publisher.publish(_event())
