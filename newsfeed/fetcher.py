import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import feedparser

from newsfeed.model import FetchedItem

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """全フィードソースの取得に失敗した場合に送出されます。

    Cloud Run Job の終了コードに伝播し、Google Cloud コンソール上で
    全面障害を検知可能にします。
    """


@dataclass(frozen=True)
class FeedSource:
    """RSS フィードソースの名前と URL を保持します。"""

    name: str
    url: str


DEFAULT_SOURCES: list[FeedSource] = [
    FeedSource("aws", "https://aws.amazon.com/blogs/aws/feed/"),
    FeedSource("azure", "https://azure.microsoft.com/en-us/blog/feed/"),
    FeedSource("google-cloud", "https://cloud.google.com/blog/feed"),
    FeedSource("oci", "https://blogs.oracle.com/cloud-infrastructure/rss"),
]


def fetch_all(sources: list[FeedSource] = DEFAULT_SOURCES) -> list[FetchedItem]:
    """全ソースから RSS フィードを取得し FetchedItem のリストを返します。"""
    items: list[FetchedItem] = []
    success_count = 0
    failure_count = 0
    for src in sources:
        try:
            feed = feedparser.parse(src.url)
            count = 0
            for entry in feed.entries:
                source_url = entry.get("link") or entry.get("id") or ""
                title = entry.get("title", "")
                if not source_url or not title:
                    continue
                items.append(FetchedItem(
                    source=src.name,
                    source_url=source_url,
                    title=title,
                    content=_entry_content(entry, title),
                    published_at=_parse_date(entry),
                ))
                count += 1
            logger.info("fetcher: %s — fetched %d items", src.name, count)
            success_count += 1
        except Exception as e:
            logger.error("fetcher: failed to parse feed %s (%s): %s", src.name, src.url, e)
            failure_count += 1

    if success_count == 0 and failure_count > 0:
        raise FetchError(
            f"all {failure_count} feed sources failed; no items fetched"
        )

    return items


def _entry_content(entry, title: str) -> str:
    # feedparser の content は [{"type": "...", "value": "本文"}] 形式のリスト
    content_list = entry.get("content")
    if content_list:
        return content_list[0].get("value", "")
    if entry.get("summary"):
        return entry.summary
    return f"Title: {title}\n\nPublished: {entry.get('published', '')}"


def _parse_date(entry) -> Optional[datetime]:
    t = entry.get("published_parsed")
    if t is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
