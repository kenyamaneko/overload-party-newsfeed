from datetime import datetime, timezone
from unittest.mock import MagicMock

from newsfeed.model import NewsArticle
from newsfeed.repository import NewsRepo

DT = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _make_repo():
    conn = MagicMock()
    # psycopg2 の connection はトランザクションのコンテキストマネージャとして使える
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    cur = conn.cursor.return_value.__enter__.return_value
    repo = NewsRepo(conn)
    return repo, conn, cur


def _make_article(**overrides):
    defaults = dict(
        article_id="art-1",
        source="test-source",
        source_url="https://example.com/1",
        title="Test Title",
        summary="test summary",
        tags=["ai"],
        raw_gcs_path="gs://bucket/raw/path.json",
        fetched_at=DT,
    )
    defaults.update(overrides)
    return NewsArticle(**defaults)


class TestInsert:
    def test_returns_true_when_row_inserted(self):
        repo, _conn, cur = _make_repo()
        cur.fetchone.return_value = ("art-1",)

        assert repo.insert(_make_article()) is True

    def test_returns_false_on_conflict(self):
        repo, _conn, cur = _make_repo()
        # ON CONFLICT DO NOTHING + RETURNING で行が返らない
        cur.fetchone.return_value = None

        assert repo.insert(_make_article()) is False

    def test_uses_transaction_context(self):
        repo, conn, cur = _make_repo()
        cur.fetchone.return_value = ("art-1",)

        repo.insert(_make_article())

        # `with conn:` で成功時にコミットされる — enter/exit の呼び出しを検証
        conn.__enter__.assert_called_once()
        conn.__exit__.assert_called_once()

    def test_query_targets_newsfeed_schema(self):
        repo, _conn, cur = _make_repo()
        cur.fetchone.return_value = ("art-1",)

        repo.insert(_make_article())

        sql = cur.execute.call_args[0][0]
        assert "newsfeed.news_articles" in sql
        assert "ON CONFLICT (source_url) DO NOTHING" in sql
        assert "RETURNING article_id" in sql
