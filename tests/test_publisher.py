import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from testcontainers.community.google import PubSubContainer

from newsfeed.model import ArticleEvent
from newsfeed.publisher import ArticlePublisher

# production の TOPIC_NAME を import せず独立リテラルで持つ。トピック名が
# production 側で変わった場合、下記の emulator テストは publish 先の
# トピックが存在しなくなり NotFound で失敗する (トートロジーの解消)。
_TOPIC_NAME = "news-article-collected"


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


@pytest.fixture(scope="session")
def pubsub_emulator():
    """テストセッション全体で共有する Pub/Sub emulator container。

    Yields:
        PubSubContainer: 起動済みの emulator container。
    """
    with PubSubContainer(image="gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators") as emulator:
        yield emulator


@pytest.fixture
def topic_subscription(pubsub_emulator):
    """テストごとに独立した project 上に topic と subscription を用意する。

    project 単位で分離するため、production と同じ TOPIC_NAME を使っても
    テスト間でメッセージが混ざらない。

    Yields:
        tuple[str, str]: (project_id, subscription_path)。
    """
    project_id = f"test-{uuid.uuid4().hex}"
    publisher_client = pubsub_emulator.get_publisher_client()
    subscriber_client = pubsub_emulator.get_subscriber_client()
    topic_path = publisher_client.topic_path(project_id, _TOPIC_NAME)
    publisher_client.create_topic(name=topic_path)
    subscription_path = subscriber_client.subscription_path(project_id, "test-sub")
    subscriber_client.create_subscription(name=subscription_path, topic=topic_path)

    yield project_id, subscription_path

    subscriber_client.close()


class TestArticlePublisherによる配信:
    def test_publishしたイベントが設定されたトピックに実配信される(self, pubsub_emulator, topic_subscription):
        project_id, subscription_path = topic_subscription
        publisher_client = pubsub_emulator.get_publisher_client()
        subscriber_client = pubsub_emulator.get_subscriber_client()

        publisher = ArticlePublisher(project_id, client=publisher_client)
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
