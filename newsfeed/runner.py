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
    if cfg is None:
        cfg = load_config()

    conn = psycopg2.connect(cfg.database_url)
    try:
        repo = NewsRepo(conn)
        gcs = GCSStorage(cfg.gcs_bucket)
        summarizer = Summarizer(cfg.gcp_project, cfg.vertex_location)

        _fetch_and_store(repo, gcs, summarizer)
        _retry_unsummarized(repo, gcs, summarizer)
    finally:
        conn.close()


def _fetch_and_store(
    repo: NewsRepo, gcs: GCSStorage, summarizer: Summarizer
) -> None:
    logger.info("step 1: fetching RSS feeds")
    items = fetch_all(DEFAULT_SOURCES)
    logger.info("step 1: fetched %d items total", len(items))

    skipped = inserted = summarized = errors = 0

    for item in items:
        try:
            if repo.exists(item.source_url):
                skipped += 1
                continue
        except Exception as e:
            logger.error("repo.exists failed for %s: %s", item.source_url, e)
            errors += 1
            continue

        article_id = str(ULID())
        fetched_at = datetime.now(timezone.utc)

        try:
            gcs_path = gcs.save(article_id, item, fetched_at)
        except Exception as e:
            logger.error("gcs.save failed for %s: %s", item.source_url, e)
            errors += 1
            continue

        article = NewsArticle(
            article_id=article_id,
            source=item.source,
            source_url=item.source_url,
            title=item.title,
            raw_gcs_path=gcs_path,
            published_at=item.published_at,
            fetched_at=fetched_at,
        )

        try:
            repo.insert(article)
            inserted += 1
        except Exception as e:
            logger.error("repo.insert failed for %s: %s", item.source_url, e)
            errors += 1
            continue

        try:
            result = summarizer.summarize(item.title, item.content)
            repo.update_summary(article_id, result.summary, result.tags)
            summarized += 1
        except Exception as e:
            logger.error("summarizer failed for %s: %s", item.source_url, e)
            errors += 1

    logger.info(
        "step 2: inserted=%d summarized=%d skipped=%d errors=%d",
        inserted, summarized, skipped, errors,
    )


def _retry_unsummarized(
    repo: NewsRepo, gcs: GCSStorage, summarizer: Summarizer
) -> None:
    logger.info("step 3: retrying unsummarized articles")

    articles = repo.list_unsummarized(limit=50)

    success_count = error_count = 0
    for article in articles:
        if not article.raw_gcs_path:
            logger.error(
                "retry: raw_gcs_path is empty for %s, skipping", article.article_id
            )
            error_count += 1
            continue

        try:
            content = gcs.load_content(article.raw_gcs_path)
        except Exception as e:
            logger.error(
                "retry: load_content failed for %s: %s", article.article_id, e
            )
            error_count += 1
            continue

        try:
            result = summarizer.summarize(article.title, content)
            repo.update_summary(article.article_id, result.summary, result.tags)
            success_count += 1
        except Exception as e:
            logger.error("retry: summarize failed for %s: %s", article.article_id, e)
            error_count += 1

    logger.info("step 3: success=%d errors=%d", success_count, error_count)
