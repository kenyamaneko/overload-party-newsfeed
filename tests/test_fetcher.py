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


class Test本文の解決:
    def test_contentタグがある記事はcontentを本文としsummaryを使わない(self):
        entry = _first_entry(_ATOM_CONTENT_AND_SUMMARY)
        assert extract_entry_body(entry, "Title") == "full body"

    def test_contentタグが無い記事はdescriptionを本文とする(self):
        entry = _first_entry(_RSS_SUMMARY_ONLY)
        assert extract_entry_body(entry, "Title") == "short summary"

    def test_contentタグが無くsummaryも空の記事のみtitleを本文とする(self):
        entry = _first_entry(_RSS_NO_CONTENT_NO_SUMMARY)
        assert extract_entry_body(entry, "My Title") == "My Title"

    @pytest.mark.parametrize("xml", [
        pytest.param(_ATOM_EMPTY_CONTENT, id="Atom の空 content タグのとき、MalformedEntryError になる"),
        pytest.param(_ATOM_SELF_CLOSING_CONTENT, id="Atom の自己終了 content タグのとき、MalformedEntryError になる"),
        pytest.param(_RSS_EMPTY_CONTENT_ENCODED, id="RSS の空 content:encoded のとき、MalformedEntryError になる"),
    ])
    def test_contentタグがあるのに本文が空ならMalformedEntryErrorになる(self, xml):
        # title への黙フォールバックを廃止し、summary が在っても本文に流用せず取得失敗として表面化させる。
        entry = _first_entry(xml)
        with pytest.raises(MalformedEntryError):
            extract_entry_body(entry, "Fallback Title")


class TestHTMLからプレーンテキストへの変換:
    def test_インラインタグを除去する(self):
        assert _html_to_plain_text("<b>bold</b> and <i>italic</i>") == "bold and italic"

    def test_ブロックタグは改行になる(self):
        assert _html_to_plain_text("<p>A</p><p>B</p>") == "A\nB"

    def test_連続する空白を畳む(self):
        assert _html_to_plain_text("<p>  leading trailing  </p>") == "leading trailing"

    def test_HTMLエンティティをデコードする(self):
        assert _html_to_plain_text("<p>foo &amp; bar</p>") == "foo & bar"


class Test公開日時のパース:
    def test_日付キーが無いときNoneを返す(self):
        entry = {}
        assert _parse_date(entry) is None

    def test_time_structをUTCのdatetimeとして解釈する(self):
        t = time.struct_time((2025, 6, 15, 12, 0, 0, 6, 166, 0))
        entry = {"published_parsed": t}
        result = _parse_date(entry)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15


class Test全フィードソースの取得:
    def _make_feed(self, entries):
        feed = MagicMock()
        feed.entries = entries
        return feed

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_source_urlが無いentryはスキップする(self, mock_parse):
        mock_parse.return_value = self._make_feed([{"title": "No URL entry"}])
        result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_titleが空のentryはスキップする(self, mock_parse):
        mock_parse.return_value = self._make_feed([
            {"link": "http://example.com/1", "title": ""},
        ])
        result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_全ソースが失敗するとFetchErrorになる(self, mock_parse):
        mock_parse.side_effect = Exception("network error")
        sources = [
            FeedSource("bad1", "http://bad1.example.com/feed"),
            FeedSource("bad2", "http://bad2.example.com/feed"),
        ]
        with pytest.raises(FetchError, match="all 2 feed sources failed"):
            fetch_all(sources)

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_少なくとも1ソース成功すれば部分取得として継続する(self, mock_parse):
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
        pytest.param({"link": "http://example.com/link", "title": "T"},
                     ["http://example.com/link"],
                     id="link だけのとき、link を source_url にする"),
        pytest.param({"id": "urn:uuid:abc", "title": "T"},
                     ["urn:uuid:abc"],
                     id="id だけのとき、id を source_url にする"),
        pytest.param({"link": "http://example.com/link", "id": "urn:uuid:abc", "title": "T"},
                     ["http://example.com/link"],
                     id="link と id が両方あるとき、link を優先する"),
        pytest.param({"title": "T"},
                     [],
                     id="link も id も無いとき、item 化しない"),
    ])
    def test_source_urlはlinkを優先しidにフォールバックする(self, entry, expected_urls):
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = self._make_feed([entry])
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert [item.source_url for item in result] == expected_urls

    def test_ソース0件はFetchErrorを出さず空リストを返す(self):
        # ソース 0 件は「全ソース失敗」とは区別し、FetchError にしない。
        assert fetch_all([]) == []

    def test_entries0件のフィードは空リストを返す(self):
        # 取得成功だが entries 0 件は「全ソース失敗」とは区別する。
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = self._make_feed([])
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result == []

    def test_単一ソースの複数有効entryを全てFetchedItem化する(self):
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

    def test_不正エントリを含む単独ソースはFetchErrorに昇格する(self):
        feed = feedparser.parse(_ATOM_EMPTY_CONTENT)
        with patch("newsfeed.fetcher.feedparser.parse", return_value=feed), pytest.raises(FetchError):
            fetch_all([FeedSource("only", "http://example.com/feed")])

    def test_1ソースの不正エントリは他ソースの取得を妨げない(self):
        bad_feed = feedparser.parse(_ATOM_EMPTY_CONTENT)
        good_feed = feedparser.parse(_ATOM_CONTENT_AND_SUMMARY)
        with patch("newsfeed.fetcher.feedparser.parse", side_effect=[bad_feed, good_feed]):
            result = fetch_all([
                FeedSource("bad", "http://bad.example.com/feed"),
                FeedSource("good", "http://good.example.com/feed"),
            ])
        assert [item.source for item in result] == ["good"]
        assert [item.body for item in result] == ["full body"]
