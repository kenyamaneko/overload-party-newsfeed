import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from newsfeed.model import FetchedItem
from newsfeed.storage import GCSStorage


@pytest.fixture
def mock_gcs_client():
    with patch("newsfeed.storage.gcs_lib.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


class TestSave:
    def test_constructs_correct_path_and_payload(self, mock_gcs_client):
        storage = GCSStorage("my-bucket")
        item = FetchedItem(
            source="aws",
            source_url="https://example.com/post",
            title="Test Article",
            content="Full body content",
            published_at=datetime(2025, 3, 10, tzinfo=timezone.utc),
        )
        fetched_at = datetime(2025, 3, 15, 8, 30, 0, tzinfo=timezone.utc)

        result = storage.save("article-123", item, fetched_at)

        assert result == "gs://my-bucket/raw/aws/2025-03-15/article-123.json"

        mock_blob = mock_gcs_client.bucket("my-bucket").blob(
            "raw/aws/2025-03-15/article-123.json"
        )
        call_args = mock_blob.upload_from_string.call_args
        payload = json.loads(call_args[0][0])
        assert payload["article_id"] == "article-123"
        assert payload["content"] == "Full body content"
        assert payload["published_at"] == "2025-03-10T00:00:00+00:00"

    def test_uses_provided_fetched_at(self, mock_gcs_client):
        storage = GCSStorage("my-bucket")
        item = FetchedItem(
            source="gcp",
            source_url="https://example.com/post2",
            title="Another Article",
            content="Some content",
        )
        fetched_at = datetime(2025, 7, 20, 14, 0, 0, tzinfo=timezone.utc)

        result = storage.save("article-456", item, fetched_at)

        assert "2025-07-20" in result

        mock_blob = mock_gcs_client.bucket("my-bucket").blob(
            "raw/gcp/2025-07-20/article-456.json"
        )
        call_args = mock_blob.upload_from_string.call_args
        payload = json.loads(call_args[0][0])
        assert payload["fetched_at"] == "2025-07-20T14:00:00+00:00"


class TestLoadContent:
    def test_raises_when_path_wrong_bucket(self, mock_gcs_client):
        storage = GCSStorage("my-bucket")
        with pytest.raises(ValueError, match="does not belong to bucket"):
            storage.load_content("gs://wrong-bucket/raw/file.json")

    def test_raises_when_content_key_missing(self, mock_gcs_client):
        storage = GCSStorage("my-bucket")
        mock_blob = mock_gcs_client.bucket("my-bucket").blob("raw/file.json")
        mock_blob.download_as_text.return_value = json.dumps({"title": "no content"})

        with pytest.raises(ValueError, match="'content' key missing"):
            storage.load_content("gs://my-bucket/raw/file.json")
