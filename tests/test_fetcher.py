import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import feedparser
import pytest

from newsfeed.fetcher import (
    FeedSource,
    FetchError,
    MalformedEntryError,
    _html_to_plain_text,
    _parse_date,
    extract_entry_body,
    fetch_all,
)


def _first_entry(xml: str):
    """RSS/Atom XML を feedparser で解釈し最初のエントリを返す。

    Args:
        xml: RSS または Atom フィードの XML 文字列。

    Returns:
        feedparser が解釈した最初のエントリ。
    """
    return feedparser.parse(xml).entries[0]


_ATOM_CONTENT_AND_SUMMARY = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Article</title>
    <link href="http://example.com/a"/>
    <summary>short summary</summary>
    <content type="html">&lt;p&gt;full body&lt;/p&gt;</content>
  </entry>
</feed>"""

_RSS_SUMMARY_ONLY = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>T</title>
<item>
  <title>Article</title>
  <link>http://example.com/r</link>
  <description>&lt;p&gt;short summary&lt;/p&gt;</description>
</item>
</channel></rss>"""

_RSS_NO_CONTENT_NO_SUMMARY = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>T</title>
<item>
  <title>Bare Article</title>
  <link>http://example.com/r2</link>
</item>
</channel></rss>"""

_ATOM_EMPTY_CONTENT = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Empty Content Article</title>
    <link href="http://example.com/empty"/>
    <summary>summary that must not become the body</summary>
    <content type="html"></content>
  </entry>
</feed>"""

_ATOM_SELF_CLOSING_CONTENT = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Self Closing Content Article</title>
    <link href="http://example.com/sc"/>
    <summary>summary that must not become the body</summary>
    <content type="html"/>
  </entry>
</feed>"""

_RSS_EMPTY_CONTENT_ENCODED = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>T</title>
<item>
  <title>Empty content:encoded Article</title>
  <link>http://example.com/rss-empty</link>
  <description>description that must not become the body</description>
  <content:encoded></content:encoded>
</item>
</channel></rss>"""


class TestEntryBody:
    """extract_entry_body の本文解決仕様を実フィード解釈 (feedparser) で検証する。"""

    def test_content_is_used_over_summary(self):
        """content タグが在る記事は content を本文とし summary を使わないことを検証する。"""
        entry = _first_entry(_ATOM_CONTENT_AND_SUMMARY)
        assert extract_entry_body(entry, "Title") == "full body"

    def test_summary_is_used_when_content_tag_absent(self):
        """content タグが無い記事は description (summary) を本文とすることを検証する。"""
        entry = _first_entry(_RSS_SUMMARY_ONLY)
        assert extract_entry_body(entry, "Title") == "short summary"

    def test_title_is_used_when_content_tag_absent_and_summary_empty(self):
        """content タグが無く summary も空の記事のみ title を本文とする正当なフォールバックを検証する。"""
        entry = _first_entry(_RSS_NO_CONTENT_NO_SUMMARY)
        assert extract_entry_body(entry, "My Title") == "My Title"

    @pytest.mark.parametrize("xml", [
        _ATOM_EMPTY_CONTENT,
        _ATOM_SELF_CLOSING_CONTENT,
        _RSS_EMPTY_CONTENT_ENCODED,
    ], ids=["atom-empty-content", "atom-self-closing-content", "rss-empty-content-encoded"])
    def test_empty_content_tag_raises_malformed_entry_error(self, xml):
        """content タグが在るのに本文が空の記事は不正として MalformedEntryError を送出することを検証する。

        title への黙フォールバックを廃止し、summary が在っても本文に流用せず
        取得失敗として表面化させる仕様。

        Args:
            xml: content タグが在るが本文値が空の実 RSS/Atom フィード XML。
        """
        entry = _first_entry(xml)
        with pytest.raises(MalformedEntryError):
            extract_entry_body(entry, "Fallback Title")


class TestHtmlToPlainText:
    def test_strips_inline_tags(self):
        assert _html_to_plain_text("<b>bold</b> and <i>italic</i>") == "bold and italic"

    def test_block_tags_produce_line_breaks(self):
        assert _html_to_plain_text("<p>A</p><p>B</p>") == "A\nB"

    def test_collapses_whitespace(self):
        assert _html_to_plain_text("<p>  leading trailing  </p>") == "leading trailing"

    def test_decodes_html_entities(self):
        assert _html_to_plain_text("<p>foo &amp; bar</p>") == "foo & bar"


class TestParseDate:
    def test_returns_none_when_missing(self):
        entry = {}
        assert _parse_date(entry) is None

    def test_parses_time_struct_as_utc(self):
        t = time.struct_time((2025, 6, 15, 12, 0, 0, 6, 166, 0))
        entry = {"published_parsed": t}
        result = _parse_date(entry)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15


class TestFetchAll:
    def _make_feed(self, entries):
        feed = MagicMock()
        feed.entries = entries
        return feed

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_skips_entries_without_source_url(self, mock_parse):
        mock_parse.return_value = self._make_feed([{"title": "No URL entry"}])
        result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_skips_entries_without_title(self, mock_parse):
        mock_parse.return_value = self._make_feed([
            {"link": "http://example.com/1", "title": ""},
        ])
        result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_raises_when_all_sources_fail(self, mock_parse):
        mock_parse.side_effect = Exception("network error")
        sources = [
            FeedSource("bad1", "http://bad1.example.com/feed"),
            FeedSource("bad2", "http://bad2.example.com/feed"),
        ]
        with pytest.raises(FetchError, match="all 2 feed sources failed"):
            fetch_all(sources)

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_continues_when_at_least_one_source_succeeds(self, mock_parse):
        valid_entry = {
            "link": "http://example.com/good",
            "title": "Good Article",
            "content": [{"value": "<p>body</p>"}],
            "published_parsed": time.struct_time((2025, 1, 1, 0, 0, 0, 0, 1, 0)),
        }
        mock_parse.side_effect = [
            Exception("network error"),
            self._make_feed([valid_entry]),
        ]
        sources = [
            FeedSource("bad", "http://bad.example.com/feed"),
            FeedSource("good", "http://good.example.com/feed"),
        ]
        result = fetch_all(sources)
        assert len(result) == 1
        assert result[0].source == "good"
        assert result[0].title == "Good Article"
        assert result[0].body == "body"

    @pytest.mark.parametrize("entry, expected_urls", [
        ({"link": "http://example.com/link", "title": "T"},
         ["http://example.com/link"]),
        ({"id": "urn:uuid:abc", "title": "T"},
         ["urn:uuid:abc"]),
        ({"link": "http://example.com/link", "id": "urn:uuid:abc", "title": "T"},
         ["http://example.com/link"]),
        ({"title": "T"},
         []),
    ], ids=["link-only", "id-only", "link-and-id-prefers-link", "neither-skipped"])
    def test_source_url_resolves_link_then_id_then_skips(self, entry, expected_urls):
        """source_url は link→id の順に解決し、両者欠落の entry は item 化しないことを検証する。

        Args:
            entry: feedparser エントリを模した辞書。
            expected_urls: 生成される FetchedItem の source_url 列 (除外時は空リスト)。
        """
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = self._make_feed([entry])
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert [item.source_url for item in result] == expected_urls

    def test_empty_source_list_returns_empty_without_error(self):
        """ソース 0 件では全面失敗と区別され、FetchError を送出せず空リストを返すことを検証する。"""
        assert fetch_all([]) == []

    def test_empty_feed_returns_empty_without_error(self):
        """取得は成功するが entries 0 件のフィードは全面失敗と区別され、空リストを返すことを検証する。"""
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = self._make_feed([])
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result == []

    def test_returns_all_valid_entries_from_single_source(self):
        """単一ソースに含まれる複数の有効 entry が全て FetchedItem 化されることを検証する。"""
        entries = [
            {"link": "http://example.com/0", "title": "Article 0"},
            {"link": "http://example.com/1", "title": "Article 1"},
            {"link": "http://example.com/2", "title": "Article 2"},
        ]
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = self._make_feed(entries)
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert [item.source_url for item in result] == [
            "http://example.com/0",
            "http://example.com/1",
            "http://example.com/2",
        ]
        assert [item.title for item in result] == [
            "Article 0",
            "Article 1",
            "Article 2",
        ]

    def test_source_with_malformed_entry_escalates_to_fetch_error_when_sole_source(self):
        """不正エントリ (content 在り・本文空) を含むソースは取得失敗として扱われ、
        単独ソースなら全面失敗として FetchError に昇格することを検証する。
        """
        feed = feedparser.parse(_ATOM_EMPTY_CONTENT)
        with patch("newsfeed.fetcher.feedparser.parse", return_value=feed):
            with pytest.raises(FetchError):
                fetch_all([FeedSource("only", "http://example.com/feed")])

    def test_malformed_entry_in_one_source_does_not_fail_other_sources(self):
        """1 ソースの不正エントリは他ソースの取得を妨げず、部分取得として継続することを検証する。"""
        bad_feed = feedparser.parse(_ATOM_EMPTY_CONTENT)
        good_feed = feedparser.parse(_ATOM_CONTENT_AND_SUMMARY)
        with patch("newsfeed.fetcher.feedparser.parse", side_effect=[bad_feed, good_feed]):
            result = fetch_all([
                FeedSource("bad", "http://bad.example.com/feed"),
                FeedSource("good", "http://good.example.com/feed"),
            ])
        assert [item.source for item in result] == ["good"]
        assert [item.body for item in result] == ["full body"]
