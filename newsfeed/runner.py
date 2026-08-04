"""newsfeed パイプラインの実行ロジック (ADR-020)。

各記事につき:
  1. Redis SETNX で source_url を事前予約 (30 日 TTL)
  2. 予約成功分のみ Vertex AI 要約 + publish
  3. Vertex AI / publish が失敗したら DEL でマーカーを解放し次周期に再試行

障害ドメインはソース単位・記事単位で閉じる (1 件の失敗が他を止めない) が、
失敗が 1 件でもあれば JobFailedError でジョブを exit 1 として可視化する。
"""
import logging

from ulid import ULID

from newsfeed import port
from newsfeed.config import Config, load_config
from newsfeed.dedup import DedupStore, create_client_from_url
from newsfeed.fetcher import DEFAULT_SOURCES, fetch_all
from newsfeed.model import ArticleEvent, FetchedItem, SummarizeResult
from newsfeed.publisher import ArticlePublisher, PublishError
from newsfeed.summarizer import SummarizeError, Summarizer

logger = logging.getLogger(__name__)


class JobFailedError(Exception):
    """ソース取得の失敗・本文が空のエントリ・記事処理の失敗が 1 件以上あった場合に送出されます。"""


def run(
    cfg: Config | None = None,
    dedup: port.DedupStore | None = None,
    summarizer: port.Summarizer | None = None,
    publisher: port.ArticlePublisher | None = None,
) -> None:
    """パイプライン全体を実行します。テスト時は各依存を DI できます。"""
    if cfg is None:
        cfg = load_config()
    if dedup is None:
        dedup = DedupStore(create_client_from_url(cfg.redis_url))
    if summarizer is None:
        summarizer = Summarizer(cfg.google_cloud_project, cfg.vertex_location)
    if publisher is None:
        publisher = ArticlePublisher(
            cfg.google_cloud_project,
            cfg.news_article_collected_topic,
        )

    _fetch_and_publish(dedup, summarizer, publisher)


def _fetch_and_publish(
    dedup: port.DedupStore,
    summarizer: port.Summarizer,
    publisher: port.ArticlePublisher,
) -> None:
    logger.info("step 1: fetching RSS feeds")
    fetched = fetch_all(DEFAULT_SOURCES)
    logger.info("step 1: fetched %d items total", len(fetched.items))

    published = duplicates = errors = 0

    for item in fetched.items:
        if not dedup.reserve(item.source_url):
            duplicates += 1
            logger.info("already seen, skipping: source_url=%s", item.source_url)
            continue

        article_id = str(ULID())
        try:
            summary = summarizer.summarize(item.title, item.body)
            event = convert_to_event(article_id, item, summary)
            publisher.publish(event)
        # 1 記事の失敗を他記事へ波及させないため、当該記事の失敗として記録し次へ進む
        except (SummarizeError, PublishError) as e:
            # 次周期で再試行させるためマーカー解放
            dedup.release(item.source_url)
            errors += 1
            logger.error(
                "processing failed: source=%s article_id=%s source_url=%s "
                "error_type=%s error=%s",
                item.source, article_id, item.source_url,
                # 型名だけではどのモジュールの例外か判別できないため、モジュール名まで含めて一意に示す
                f"{type(e).__module__}.{type(e).__qualname__}", e,
            )
            continue

        published += 1
        logger.info(
            "published: source=%s article_id=%s source_url=%s",
            item.source, article_id, item.source_url,
        )

    logger.info(
        "step 2: published=%d duplicates=%d errors=%d",
        published, duplicates, errors,
    )

    failures: list[str] = []
    if fetched.failed_sources:
        failures.append(
            f"{len(fetched.failed_sources)} feed source(s) failed to fetch: "
            f"{', '.join(fetched.failed_sources)}"
        )
    if fetched.malformed_entries:
        skipped = ", ".join(f"{e.source}:{e.title}" for e in fetched.malformed_entries)
        failures.append(
            f"{len(fetched.malformed_entries)} entry(ies) skipped for empty body: {skipped}"
        )
    if errors > 0:
        failures.append(f"{errors} article(s) failed to process")
    if failures:
        raise JobFailedError("; ".join(failures))


def convert_to_event(article_id: str, item: FetchedItem, summary: SummarizeResult) -> ArticleEvent:
    """取得記事と要約結果を publish 用の ArticleEvent に変換する。

    Args:
        article_id: 採番済みの記事 ID。
        item: フィードから取得した記事。
        summary: Vertex AI による要約・タグ付け結果。

    Returns:
        publish 用に組み立てた ArticleEvent。
    """
    return ArticleEvent(
        article_id=article_id,
        source=item.source,
        source_url=item.source_url,
        tags=summary.tags,
        title=item.title,
        summary=summary.summary,
        body=item.body,
        source_published_at=item.source_published_at,
    )
