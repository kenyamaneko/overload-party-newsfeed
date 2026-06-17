import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
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
                    body=extract_entry_body(entry, title),
                    source_published_at=_parse_date(entry),
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


def extract_entry_body(entry, title: str) -> str:
    """RSS エントリから本文をプレーンテキストで取得する。

    content:encoded を優先、無ければ description (summary) を使う。
    body が空になる場合のみ title で埋める (news 側は body が空文字列のイベントを
    不正として扱うため)。
    """
    content_list = entry.get("content")
    if content_list:
        html = content_list[0].get("value", "")
    else:
        html = entry.get("summary", "")
    body = _html_to_plain_text(html) if html else ""
    return body if body else title


def _parse_date(entry) -> Optional[datetime]:
    t = entry.get("published_parsed")
    if t is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)


_BLOCK_TAGS = frozenset({
    "p", "div", "br", "li", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "pre", "blockquote", "section", "article", "figure", "figcaption",
})


class _PlainTextExtractor(HTMLParser):
    """HTML をプレーンテキストに変換するパーサ。ブロック要素で改行を挿入する。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data) -> None:
        self._parts.append(data)

    def build_text(self) -> str:
        return "".join(self._parts)


def _html_to_plain_text(html: str) -> str:
    """HTML タグを除去し段落区切りを保ったプレーンテキストを返す。"""
    extractor = _PlainTextExtractor()
    extractor.feed(html)
    lines = [line.strip() for line in extractor.build_text().splitlines()]
    non_empty = [line for line in lines if line]
    return "\n".join(non_empty)
