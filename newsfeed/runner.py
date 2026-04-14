"""newsfeed パイプラインの実行ロジックです。

記事ごとの処理フロー（アトミック単位）:
  1. GCS アップロード（生 JSON ペイロード、非トランザクション）
  2. Vertex AI 要約（非トランザクション）
  3. summary + tags + gcs_path が揃った状態で newsfeed.news_articles へ
     単一 INSERT（NewsRepo.insert() 内で DB トランザクション管理）

いずれかのステップが失敗した場合、DB 行は作成されません。
source_url UNIQUE 制約 + ON CONFLICT DO NOTHING により再取り込みは冪等です。
"""
import logging
from datetime import datetime, timezone

import psycopg2
from ulid import ULID

from newsfeed.config import Config, load_config
from newsfeed.fetcher import DEFAULT_SOURCES, fetch_all
from newsfeed.model import NewsArticle
from newsfeed.repository import NewsRepo
from newsfeed.storage import GCSStorage
from newsfeed.summarizer import Summarizer

logger = logging.getLogger(__name__)


def run(cfg: Config | None = None) -> None:
    """パイプライン全体を実行します。"""
    if cfg is None:
        cfg = load_config()

    conn = psycopg2.connect(cfg.database_url)
    try:
        repo = NewsRepo(conn)
        gcs = GCSStorage(cfg.gcs_bucket)
        summarizer = Summarizer(cfg.google_cloud_project, cfg.vertex_location)

        _fetch_and_store(repo, gcs, summarizer)
    finally:
        conn.close()


def _fetch_and_store(
    repo: NewsRepo, gcs: GCSStorage, summarizer: Summarizer
) -> None:
    logger.info("step 1: fetching RSS feeds")
    items = fetch_all(DEFAULT_SOURCES)
    logger.info("step 1: fetched %d items total", len(items))

    inserted = duplicates = errors = 0

    for item in items:
        article_id = str(ULID())
        fetched_at = datetime.now(timezone.utc)

        try:
            gcs_path = gcs.save(article_id, item, fetched_at)
        except Exception as e:
            logger.error("gcs.save failed for %s: %s", item.source_url, e)
            errors += 1
            continue

        try:
            result = summarizer.summarize(item.title, item.content)
        except Exception as e:
            logger.error("summarizer failed for %s: %s", item.source_url, e)
            errors += 1
            continue

        article = NewsArticle(
            article_id=article_id,
            source=item.source,
            source_url=item.source_url,
            title=item.title,
            summary=result.summary,
            tags=result.tags,
            raw_gcs_path=gcs_path,
            published_at=item.published_at,
            fetched_at=fetched_at,
        )

        try:
            was_inserted = repo.insert(article)
        except Exception as e:
            logger.error("repo.insert failed for %s: %s", item.source_url, e)
            errors += 1
            continue

        if was_inserted:
            inserted += 1
            logger.info("new article: source_url=%s article_id=%s", item.source_url, article_id)
        else:
            duplicates += 1
            logger.info("duplicate skipped: source_url=%s", item.source_url)

    logger.info(
        "step 2: inserted=%d duplicates=%d errors=%d",
        inserted, duplicates, errors,
    )
