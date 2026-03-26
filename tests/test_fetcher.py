import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from newsfeed.fetcher import FeedSource, _entry_content, _parse_date, fetch_all


class TestEntryContent:
    def test_with_content_list(self):
        entry = {"content": [{"value": "full body text"}]}
        assert _entry_content(entry, "My Title") == "full body text"

    def test_fallback_to_summary(self):
        class Entry(dict):
            def __init__(self, d):
                super().__init__(d)
                for k, v in d.items():
                    setattr(self, k, v)

        entry = Entry({"summary": "short summary"})
        assert _entry_content(entry, "My Title") == "short summary"

    def test_fallback_to_title_published(self):
        entry = {"published": "2025-01-01"}
        result = _entry_content(entry, "My Title")
        assert "Title: My Title" in result
        assert "Published: 2025-01-01" in result


class TestParseDate:
    def test_with_none(self):
        entry = {}
        assert _parse_date(entry) is None

    def test_with_valid_time_struct(self):
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
        mock_parse.return_value = self._make_feed([
            {"title": "No URL entry"},
        ])
        sources = [FeedSource("src1", "http://example.com/feed")]
        result = fetch_all(sources)
        assert result == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_skips_entries_without_title(self, mock_parse):
        mock_parse.return_value = self._make_feed([
            {"link": "http://example.com/1", "title": ""},
        ])
        sources = [FeedSource("src1", "http://example.com/feed")]
        result = fetch_all(sources)
        assert result == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_continues_on_feed_parse_error(self, mock_parse):
        valid_entry = {
            "link": "http://example.com/good",
            "title": "Good Article",
            "content": [{"value": "body"}],
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
