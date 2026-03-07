import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import feedparser

from newsfeed.model import FetchedItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str


DEFAULT_SOURCES: list[FeedSource] = [
    FeedSource("aws", "https://aws.amazon.com/blogs/aws/feed/"),
    FeedSource("azure", "https://azure.microsoft.com/en-us/blog/feed/"),
    FeedSource("gcp", "https://cloud.google.com/blog/feed"),
    FeedSource("oci", "https://blogs.oracle.com/cloud-infrastructure/rss"),
]


def fetch_all(sources: list[FeedSource] = DEFAULT_SOURCES) -> list[FetchedItem]:
    items: list[FetchedItem] = []
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
        except Exception as e:
            logger.error("fetcher: failed to parse feed %s (%s): %s", src.name, src.url, e)
    return items


def _entry_content(entry, title: str) -> str:
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
