import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser

import feedparser

from newsfeed.model import FetchedItem, FetchResult, MalformedEntry

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """全フィードソースの取得に失敗した場合に送出されます。

    Cloud Run Job の終了コードに伝播し、Google Cloud コンソール上で
    全面障害を検知可能にします。
    """


class FeedSourceError(Exception):
    """1 つのフィードソースの取得に失敗した場合に送出されます。"""


class MalformedEntryError(Exception):
    """本文が空のエントリを検出した場合に送出されます。

    news 側は body が空文字列のイベントを不正として扱うため、title への
    黙フォールバックで本文を捏造せず、当該エントリの失敗として表面化させます。
    """


@dataclass(frozen=True)
class FeedSource:
    """RSS フィードソースの名前と URL を保持します。"""

    name: str
    url: str


DEFAULT_SOURCES: list[FeedSource] = [
    FeedSource("aws", "https://aws.amazon.com/blogs/aws/feed/"),
    FeedSource("azure", "https://azure.microsoft.com/en-us/blog/feed/"),
    FeedSource("google-cloud", "https://cloudblog.withgoogle.com/rss/"),
]

_HTTP_ERROR_STATUS_MIN = 400


def _parse_feed(src: FeedSource):
    """フィードソースの URL を取得して解釈する。

    Args:
        src: 取得対象のフィードソース。

    Returns:
        feedparser が返した取得結果。

    Raises:
        FeedSourceError: 取得または解釈が例外で終わったとき。
    """
    try:
        return feedparser.parse(src.url)
    # feedparser は取得と解釈の失敗を例外にしない仕様のため、例外が出たら種別を問わず当該ソースの失敗とする
    except Exception as e:
        raise FeedSourceError(
            f"fetcher: failed to read feed {src.name} ({src.url}): {e}"
        ) from e


def _find_fetch_failure(feed) -> str | None:
    """フィードの取得結果から取得失敗の理由を探す。

    Args:
        feed: feedparser が返した取得結果。

    Returns:
        取得失敗の理由。取得できていれば None。
    """
    status = getattr(feed, "status", None)
    if status is not None and status >= _HTTP_ERROR_STATUS_MIN:
        return f"HTTP status {status}"
    if feed.bozo and not feed.entries:
        return f"response is not a readable feed: {feed.bozo_exception}"
    return None


def fetch_all(sources: list[FeedSource] = DEFAULT_SOURCES) -> FetchResult:
    """全ソースから RSS フィードを取得し、記事と失敗を返します。

    Args:
        sources: 取得対象の RSS フィードソース。

    Returns:
        取得できた記事と、取得に失敗したソースの名前、本文が空でスキップしたエントリ。

    Raises:
        FetchError: 全ソースの取得に失敗したとき。
    """
    items: list[FetchedItem] = []
    success_count = 0
    failed_sources: list[str] = []
    malformed_entries: list[MalformedEntry] = []
    for src in sources:
        try:
            feed = _parse_feed(src)
            failure = _find_fetch_failure(feed)
            if failure is not None:
                logger.error(
                    "fetcher: failed to fetch feed %s (%s): %s", src.name, src.url, failure,
                )
                failed_sources.append(src.name)
                continue
            if feed.bozo:
                logger.warning(
                    "fetcher: %s: feed is malformed but %d entries were readable: %s",
                    src.name, len(feed.entries), feed.bozo_exception,
                )
            count = 0
            for entry in feed.entries:
                source_url = entry.get("link") or entry.get("id") or ""
                title = entry.get("title", "")
                if not source_url or not title:
                    continue
                try:
                    body = extract_entry_body(entry, title)
                # 恒常的に壊れた 1 エントリが同ソースの後続記事を毎周期止めないため、
                # ソースの失敗とせず当該エントリだけ飛ばす
                except MalformedEntryError as e:
                    logger.warning(
                        "fetcher: skipped entry with empty body: source=%s title=%r: %s",
                        src.name, title, e,
                    )
                    malformed_entries.append(MalformedEntry(source=src.name, title=title))
                    continue
                items.append(FetchedItem(
                    source=src.name,
                    source_url=source_url,
                    title=title,
                    body=body,
                    source_published_at=_parse_date(entry),
                ))
                count += 1
            logger.info("fetcher: %s — fetched %d items", src.name, count)
            success_count += 1
        # 1 ソースの失敗を他ソースへ波及させないため、当該ソースの失敗として記録し次へ進む
        except FeedSourceError as e:
            logger.error("%s", e)
            failed_sources.append(src.name)

    if success_count == 0 and failed_sources:
        raise FetchError(
            f"all {len(failed_sources)} feed sources failed; no items fetched"
        )

    return FetchResult(
        items=items,
        failed_sources=failed_sources,
        malformed_entries=malformed_entries,
    )


def extract_entry_body(entry, title: str) -> str:
    """RSS エントリから本文をプレーンテキストで取得する。

    content:encoded が在ればそれを本文とする。content タグが無いときに限り
    description (summary) を本文とする。

    Args:
        entry: feedparser が解釈した RSS/Atom エントリ。
        title: エラーメッセージで対象エントリを特定するためのタイトル。

    Returns:
        HTML を除去したプレーンテキストの本文。

    Raises:
        MalformedEntryError: 本文が空のとき。
    """
    content_list = entry.get("content")
    if content_list:
        html = content_list[0].get("value", "")
        body = _html_to_plain_text(html) if html else ""
        if not body:
            raise MalformedEntryError(
                f"content tag present but body is empty: title={title!r}"
            )
        return body
    summary = entry.get("summary", "")
    body = _html_to_plain_text(summary) if summary else ""
    if not body:
        raise MalformedEntryError(
            f"neither content nor summary carries a body: title={title!r}"
        )
    return body


def _parse_date(entry) -> datetime | None:
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
        """パース中に収集したテキスト断片を連結して返す。

        Returns:
            ブロック要素を改行で区切ったプレーンテキスト。
        """
        return "".join(self._parts)


def _html_to_plain_text(html: str) -> str:
    """HTML タグを除去し段落区切りを保ったプレーンテキストを返す。"""
    extractor = _PlainTextExtractor()
    extractor.feed(html)
    lines = [line.strip() for line in extractor.build_text().splitlines()]
    non_empty = [line for line in lines if line]
    return "\n".join(non_empty)
