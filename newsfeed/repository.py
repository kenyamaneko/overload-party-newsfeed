import psycopg2

from newsfeed.model import NewsArticle


class NewsRepo:
    """newsfeed.news_articles テーブルへの書き込みを提供します。"""

    def __init__(self, conn: psycopg2.extensions.connection):
        self._conn = conn

    def insert(self, article: NewsArticle) -> bool:
        """記事を INSERT し、新規挿入なら True、重複なら False を返します。

        RETURNING 句で実際に挿入されたかを判別するため、
        check-then-act のレースコンディションが発生しません。
        summary / tags / raw_gcs_path が全て揃った状態でのみ呼び出してください。
        """
        with self._conn:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO newsfeed.news_articles
                      (article_id, source, source_url, title, summary, tags,
                       raw_gcs_path, published_at, fetched_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_url) DO NOTHING
                    RETURNING article_id
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
                return cur.fetchone() is not None
