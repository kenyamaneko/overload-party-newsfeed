"""newsfeed パイプラインの実行ロジック。

fetch_all の結果を記事単位で news-article-collected へ publish する。
障害ドメインは記事単位 (1 件の失敗が他記事の処理を止めない) だが、
1 件でも publish が失敗すればジョブ終了時に PublishError を送出し
exit 1 として Cloud Run Job 上で失敗を可視化する (ADR-019)。
"""
import logging

from ulid import ULID

from newsfeed.config import Config, load_config
from newsfeed.fetcher import DEFAULT_SOURCES, fetch_all
from newsfeed.model import ArticleEvent, FetchedItem
from newsfeed.publisher import ArticlePublisher

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """1 件以上の記事 publish に失敗した場合に送出されます。"""


def run(cfg: Config | None = None, publisher: ArticlePublisher | None = None) -> None:
    """パイプライン全体を実行します。"""
    if cfg is None:
        cfg = load_config()
    if publisher is None:
        publisher = ArticlePublisher(cfg.google_cloud_project)

    _fetch_and_publish(publisher)


def _fetch_and_publish(publisher: ArticlePublisher) -> None:
    logger.info("step 1: fetching RSS feeds")
    items = fetch_all(DEFAULT_SOURCES)
    logger.info("step 1: fetched %d items total", len(items))

    published = 0
    failed = 0

    for item in items:
        article_id = str(ULID())
        event = _to_event(article_id, item)

        try:
            publisher.publish(event)
        except Exception as e:
            logger.error(
                "publish failed: source=%s article_id=%s source_url=%s error=%s",
                item.source, article_id, item.source_url, e,
            )
            failed += 1
            continue

        published += 1
        logger.info(
            "published: source=%s article_id=%s source_url=%s",
            item.source, article_id, item.source_url,
        )

    logger.info("step 2: published=%d failed=%d", published, failed)

    if failed > 0:
        raise PublishError(f"{failed}/{published + failed} article(s) failed to publish")


def _to_event(article_id: str, item: FetchedItem) -> ArticleEvent:
    return ArticleEvent(
        article_id=article_id,
        source=item.source,
        source_url=item.source_url,
        title=item.title,
        body=item.body,
        source_published_at=item.source_published_at,
    )
