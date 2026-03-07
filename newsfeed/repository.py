import logging

import psycopg2

from newsfeed.model import NewsArticle

logger = logging.getLogger(__name__)


class NewsRepo:
    def __init__(self, conn: psycopg2.extensions.connection):
        self._conn = conn

    def exists(self, source_url: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM news_articles WHERE source_url = %s)",
                (source_url,),
            )
            return cur.fetchone()[0]

    def insert(self, article: NewsArticle) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_articles
                  (article_id, source, source_url, title, summary, tags,
                   raw_gcs_path, published_at, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_url) DO NOTHING
                """,
                (
                    article.article_id,
                    article.source,
                    article.source_url,
                    article.title,
                    article.summary,
                    article.tags,
                    article.raw_gcs_path,
                    article.published_at,
                    article.fetched_at,
                ),
            )
        self._conn.commit()

    def update_summary(self, article_id: str, summary: str, tags: list[str]) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE news_articles
                   SET summary = %s, tags = %s
                 WHERE article_id = %s
                """,
                (summary, tags, article_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"article {article_id} not found")
        self._conn.commit()

    def list_unsummarized(self, limit: int = 50) -> list[NewsArticle]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT article_id, source, source_url, title,
                       raw_gcs_path, published_at, fetched_at
                  FROM news_articles
                 WHERE summary IS NULL
                 ORDER BY fetched_at ASC
                 LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [
            NewsArticle(
                article_id=row[0],
                source=row[1],
                source_url=row[2],
                title=row[3],
                raw_gcs_path=row[4],
                published_at=row[5],
                fetched_at=row[6],
            )
            for row in rows
        ]
