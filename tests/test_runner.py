from unittest.mock import MagicMock, patch

import pytest

from newsfeed.model import FetchedItem
from newsfeed.runner import PublishError, _fetch_and_publish


def _item(n: int) -> FetchedItem:
    return FetchedItem(
        source="aws",
        source_url=f"https://example.com/{n}",
        title=f"Article {n}",
        body=f"body{n}",
    )


class TestFetchAndPublish:
    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_publishes_each_fetched_item(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "fake-ulid"

        publisher = MagicMock()

        _fetch_and_publish(publisher)

        assert publisher.publish.call_count == 2

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_event_payload_mirrors_fetched_item(self, mock_ulid, mock_fetch_all):
        item = FetchedItem(
            source="aws",
            source_url="https://example.com/1",
            title="Title",
            body="body",
        )
        mock_fetch_all.return_value = [item]
        mock_ulid.return_value = "01ABC"

        publisher = MagicMock()

        _fetch_and_publish(publisher)

        event = publisher.publish.call_args[0][0]
        assert event.article_id == "01ABC"
        assert event.source == "aws"
        assert event.source_url == "https://example.com/1"
        assert event.title == "Title"
        assert event.body == "body"

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_individual_publish_failure_does_not_stop_pipeline(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2), _item(3)]
        mock_ulid.return_value = "fake-ulid"

        publisher = MagicMock()
        publisher.publish.side_effect = [Exception("pubsub down"), None, None]

        with pytest.raises(PublishError):
            _fetch_and_publish(publisher)

        # 失敗後も残り記事の publish 試行が継続する
        assert publisher.publish.call_count == 3

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_raises_publish_error_when_any_article_fails(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "fake-ulid"

        publisher = MagicMock()
        publisher.publish.side_effect = [None, Exception("pubsub down")]

        with pytest.raises(PublishError, match="1/2"):
            _fetch_and_publish(publisher)

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_does_not_raise_when_all_articles_succeed(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "fake-ulid"

        publisher = MagicMock()

        _fetch_and_publish(publisher)  # no raise

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_no_items_no_publish_no_error(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = []
        mock_ulid.return_value = "fake-ulid"

        publisher = MagicMock()

        _fetch_and_publish(publisher)

        assert publisher.publish.call_count == 0
