from unittest.mock import MagicMock, patch

from newsfeed.model import FetchedItem, SummarizeResult
from newsfeed.runner import _fetch_and_store


def _item(n: int) -> FetchedItem:
    return FetchedItem(
        source="aws",
        source_url=f"https://example.com/{n}",
        title=f"Article {n}",
        content=f"content{n}",
    )


class TestFetchAndStore:
    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_new_insert_logs_as_new(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1)]
        mock_ulid.return_value = "fake-ulid"

        repo = MagicMock()
        repo.insert.return_value = True  # actually inserted

        gcs = MagicMock()
        gcs.save.return_value = "gs://bucket/raw/path.json"

        summarizer = MagicMock()
        summarizer.summarize.return_value = SummarizeResult(summary="sum", tags=["ai"])

        _fetch_and_store(repo, gcs, summarizer)

        assert repo.insert.call_count == 1
        # パイプライン順序: GCS → summarize → insert
        article = repo.insert.call_args[0][0]
        assert article.summary == "sum"
        assert article.tags == ["ai"]
        assert article.raw_gcs_path == "gs://bucket/raw/path.json"

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_duplicate_skipped_does_not_re_summarize_next_time(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "fake-ulid"

        repo = MagicMock()
        # 1 件目は重複（conflict）、2 件目は新規
        repo.insert.side_effect = [False, True]

        gcs = MagicMock()
        gcs.save.return_value = "gs://bucket/raw/path.json"

        summarizer = MagicMock()
        summarizer.summarize.return_value = SummarizeResult(summary="sum", tags=["ai"])

        _fetch_and_store(repo, gcs, summarizer)

        assert repo.insert.call_count == 2

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_gcs_failure_skips_insert(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "fake-ulid"

        repo = MagicMock()
        repo.insert.return_value = True

        gcs = MagicMock()
        gcs.save.side_effect = [Exception("gcs down"), "gs://bucket/raw/path.json"]

        summarizer = MagicMock()
        summarizer.summarize.return_value = SummarizeResult(summary="sum", tags=["ai"])

        _fetch_and_store(repo, gcs, summarizer)

        # GCS 成功分のみ insert に到達
        assert repo.insert.call_count == 1
        # GCS 失敗分は summarizer もスキップされる
        assert summarizer.summarize.call_count == 1

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_summarizer_failure_skips_insert(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "fake-ulid"

        repo = MagicMock()
        repo.insert.return_value = True

        gcs = MagicMock()
        gcs.save.return_value = "gs://bucket/raw/path.json"

        summarizer = MagicMock()
        summarizer.summarize.side_effect = [
            Exception("vertex down"),
            SummarizeResult(summary="sum", tags=["ai"]),
        ]

        _fetch_and_store(repo, gcs, summarizer)

        # 1 件目は summarizer 失敗 → insert なし。2 件目のみ insert される
        assert repo.insert.call_count == 1

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_insert_failure_does_not_stop_pipeline(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "fake-ulid"

        repo = MagicMock()
        repo.insert.side_effect = [Exception("db down"), True]

        gcs = MagicMock()
        gcs.save.return_value = "gs://bucket/raw/path.json"

        summarizer = MagicMock()
        summarizer.summarize.return_value = SummarizeResult(summary="sum", tags=["ai"])

        _fetch_and_store(repo, gcs, summarizer)

        assert repo.insert.call_count == 2
