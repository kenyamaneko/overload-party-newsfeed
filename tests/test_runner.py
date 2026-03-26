from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from newsfeed.model import FetchedItem, NewsArticle
from newsfeed.runner import _fetch_and_store, _retry_unsummarized


class TestFetchAndStore:
    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_continues_when_repo_exists_raises(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [
            FetchedItem(
                source="aws",
                source_url="https://example.com/1",
                title="Article 1",
                content="content1",
            ),
            FetchedItem(
                source="aws",
                source_url="https://example.com/2",
                title="Article 2",
                content="content2",
            ),
        ]
        mock_ulid.return_value = "fake-ulid"

        repo = MagicMock()
        repo.exists.side_effect = [Exception("db down"), False]

        gcs = MagicMock()
        gcs.save.return_value = "gs://bucket/raw/path.json"

        summarizer = MagicMock()
        summarizer.summarize.return_value = MagicMock(
            summary="sum", tags=["ai"]
        )

        _fetch_and_store(repo, gcs, summarizer)

        # First item's exists() failed, so insert should only be called for second item
        assert repo.insert.call_count == 1

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_continues_when_repo_insert_raises(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [
            FetchedItem(
                source="aws",
                source_url="https://example.com/1",
                title="Article 1",
                content="content1",
            ),
            FetchedItem(
                source="aws",
                source_url="https://example.com/2",
                title="Article 2",
                content="content2",
            ),
        ]
        mock_ulid.return_value = "fake-ulid"

        repo = MagicMock()
        repo.exists.return_value = False
        repo.insert.side_effect = [Exception("db write fail"), None]

        gcs = MagicMock()
        gcs.save.return_value = "gs://bucket/raw/path.json"

        summarizer = MagicMock()
        summarizer.summarize.return_value = MagicMock(
            summary="sum", tags=["ai"]
        )

        _fetch_and_store(repo, gcs, summarizer)

        # insert was called for both items
        assert repo.insert.call_count == 2
        # summarizer only called for second item (first insert failed -> continue)
        assert summarizer.summarize.call_count == 1


class TestRetryUnsummarized:
    def test_skips_empty_raw_gcs_path(self):
        repo = MagicMock()
        repo.list_unsummarized.return_value = [
            NewsArticle(
                article_id="id-1",
                source="aws",
                source_url="https://example.com/1",
                title="No path article",
                raw_gcs_path="",
                fetched_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
        ]

        gcs = MagicMock()
        summarizer = MagicMock()

        _retry_unsummarized(repo, gcs, summarizer)

        gcs.load_content.assert_not_called()
        summarizer.summarize.assert_not_called()

    def test_skips_when_load_content_fails(self):
        repo = MagicMock()
        repo.list_unsummarized.return_value = [
            NewsArticle(
                article_id="id-2",
                source="gcp",
                source_url="https://example.com/2",
                title="Broken GCS",
                raw_gcs_path="gs://bucket/raw/file.json",
                fetched_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
        ]

        gcs = MagicMock()
        gcs.load_content.side_effect = Exception("gcs read error")

        summarizer = MagicMock()

        _retry_unsummarized(repo, gcs, summarizer)

        gcs.load_content.assert_called_once()
        summarizer.summarize.assert_not_called()
