from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from newsfeed.model import NewsArticle
from newsfeed.repository import NewsRepo

DT = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _make_repo():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    repo = NewsRepo(conn)
    return repo, conn, cur


def _make_article(**overrides):
    defaults = dict(
        article_id="art-1",
        source="test-source",
        source_url="https://example.com/1",
        title="Test Title",
        fetched_at=DT,
    )
    defaults.update(overrides)
    return NewsArticle(**defaults)


# ---------- TestExists ----------


class TestExists:
    def test_returns_true_when_row_exists(self):
        repo, _conn, cur = _make_repo()
        cur.fetchone.return_value = (True,)

        assert repo.exists("https://example.com/1") is True

    def test_returns_false_when_no_row(self):
        repo, _conn, cur = _make_repo()
        cur.fetchone.return_value = (False,)

        assert repo.exists("https://example.com/1") is False


# ---------- TestInsert ----------


class TestInsert:
    def test_calls_commit_after_execute(self):
        repo, conn, cur = _make_repo()
        article = _make_article()

        repo.insert(article)

        conn.commit.assert_called_once()

    def test_on_conflict_does_not_raise(self):
        repo, _conn, cur = _make_repo()
        article = _make_article()

        repo.insert(article)  # should not raise


# ---------- TestUpdateSummary ----------


class TestUpdateSummary:
    def test_raises_when_no_rows_updated(self):
        repo, _conn, cur = _make_repo()
        cur.rowcount = 0

        with pytest.raises(ValueError, match="not found"):
            repo.update_summary("art-missing", "summary", ["tag"])

    def test_commits_on_success(self):
        repo, conn, cur = _make_repo()
        cur.rowcount = 1

        repo.update_summary("art-1", "summary", ["tag"])

        conn.commit.assert_called_once()


# ---------- TestListUnsummarized ----------


class TestListUnsummarized:
    def test_returns_articles_from_rows(self):
        repo, _conn, cur = _make_repo()
        cur.fetchall.return_value = [
            ("id-1", "src-a", "https://a.com", "Title A", "gcs/a", DT, DT),
            ("id-2", "src-b", "https://b.com", "Title B", "gcs/b", DT, DT),
        ]

        articles = repo.list_unsummarized()

        assert len(articles) == 2
        a1, a2 = articles

        assert a1.article_id == "id-1"
        assert a1.source == "src-a"
        assert a1.source_url == "https://a.com"
        assert a1.title == "Title A"
        assert a1.raw_gcs_path == "gcs/a"
        assert a1.published_at == DT
        assert a1.fetched_at == DT

        assert a2.article_id == "id-2"
        assert a2.source == "src-b"

    def test_returns_empty_list_when_no_rows(self):
        repo, _conn, cur = _make_repo()
        cur.fetchall.return_value = []

        assert repo.list_unsummarized() == []
