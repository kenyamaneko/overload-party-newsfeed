import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from newsfeed.fetcher import (
    FeedSource,
    FetchError,
    _html_to_plain_text,
    _parse_date,
    extract_entry_body,
    fetch_all,
)


class TestEntryBody:
    def test_prefers_content_over_summary(self):
        entry = {
            "content": [{"value": "<p>full body</p>"}],
            "summary": "short summary",
        }
        assert extract_entry_body(entry, "Title") == "full body"

    def test_falls_back_to_summary(self):
        entry = {"summary": "<p>short summary</p>"}
        assert extract_entry_body(entry, "Title") == "short summary"

    def test_falls_back_to_title_when_body_empty(self):
        entry = {}
        assert extract_entry_body(entry, "My Title") == "My Title"

    def test_html_is_stripped_to_plain_text(self):
        entry = {"content": [{"value": "<p>Hello</p><p>World</p>"}]}
        assert extract_entry_body(entry, "t") == "Hello\nWorld"

    @pytest.mark.parametrize("entry", [
        {"content": [{"value": ""}], "summary": "ignored summary"},
        {"content": [{}], "summary": "ignored summary"},
    ], ids=["empty-content-value", "missing-content-value-key"])
    def test_present_but_empty_content_falls_back_to_title(self, entry):
        """content キーが在れば値が空/欠落でも summary を使わず title で本文を埋めることを検証する。

        Args:
            entry: content キーは在るが本文値が空または欠落した feedparser エントリ。
        """
        assert extract_entry_body(entry, "Fallback Title") == "Fallback Title"


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
