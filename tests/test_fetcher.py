import time
from datetime import datetime, timezone
from unittest.mock import patch

import feedparser
import pytest
from feedparser.util import FeedParserDict

from newsfeed.fetcher import (
    FeedSource,
    FetchError,
    MalformedEntryError,
    _html_to_plain_text,
    _parse_date,
    extract_entry_body,
    fetch_all,
)
from newsfeed.model import MalformedEntry


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

_RSS_EMPTY_SUMMARY = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>T</title>
<item>
  <title>Empty Description Article</title>
  <link>http://example.com/r3</link>
  <description></description>
</item>
</channel></rss>"""

_RSS_MARKUP_ONLY_SUMMARY = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>T</title>
<item>
  <title>Markup Only Article</title>
  <link>http://example.com/r4</link>
  <description>&lt;p&gt;&lt;/p&gt;</description>
</item>
</channel></rss>"""

_RSS_EMPTY_SUMMARY_THEN_VALID = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>T</title>
<item>
  <title>Empty Description Article</title>
  <link>http://example.com/empty</link>
  <description></description>
</item>
<item>
  <title>Good Article</title>
  <link>http://example.com/good</link>
  <description>&lt;p&gt;body&lt;/p&gt;</description>
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

    @pytest.mark.parametrize("xml", [
        pytest.param(_ATOM_EMPTY_CONTENT, id="Atom の空 content タグのとき、MalformedEntryError になる"),
        pytest.param(_ATOM_SELF_CLOSING_CONTENT, id="Atom の自己終了 content タグのとき、MalformedEntryError になる"),
        pytest.param(_RSS_EMPTY_CONTENT_ENCODED, id="RSS の空 content:encoded のとき、MalformedEntryError になる"),
    ])
    def test_contentタグがあるのに本文が空ならMalformedEntryErrorになる(self, xml):
        entry = _first_entry(xml)
        with pytest.raises(MalformedEntryError, match="content tag present but body is empty"):
            extract_entry_body(entry, "Fallback Title")

    @pytest.mark.parametrize("xml", [
        pytest.param(_RSS_NO_CONTENT_NO_SUMMARY, id="content も description も無いとき、MalformedEntryError になる"),
        pytest.param(_RSS_EMPTY_SUMMARY, id="content が無く description が空のとき、MalformedEntryError になる"),
        pytest.param(_RSS_MARKUP_ONLY_SUMMARY,
                     id="content が無く description がタグだけのとき、MalformedEntryError になる"),
    ])
    def test_contentもdescriptionも本文にならないときtitleで埋めずMalformedEntryErrorになる(self, xml):
        entry = _first_entry(xml)
        with pytest.raises(MalformedEntryError, match="neither content nor summary carries a body"):
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


def _entry(url: str, title: str) -> dict:
    """本文を備えた最小の正常エントリを組み立てる。

    Args:
        url: エントリの link に入れる URL。
        title: エントリのタイトル。

    Returns:
        feedparser のエントリと同じ形の dict。
    """
    return {"link": url, "title": title, "content": [{"value": "<p>body</p>"}]}


def _parsed_feed(entries: list[dict]) -> FeedParserDict:
    """正常に取得できたフィードと同じ形の解釈結果を組み立てる。

    Args:
        entries: フィードに含めるエントリ。

    Returns:
        feedparser.parse の戻り値と同じ形の解釈結果。
    """
    return FeedParserDict(bozo=False, status=200, entries=entries)


class Test全フィードソースの取得:
    @patch("newsfeed.fetcher.feedparser.parse")
    def test_source_urlが無いentryはスキップする(self, mock_parse):
        mock_parse.return_value = _parsed_feed([{"title": "No URL entry"}])
        result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result.items == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_titleが空のentryはスキップする(self, mock_parse):
        mock_parse.return_value = _parsed_feed([
            {"link": "http://example.com/1", "title": ""},
        ])
        result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert result.items == []

    @patch("newsfeed.fetcher.feedparser.parse")
    def test_記事の公開日時をUTCで取り込む(self, mock_parse):
        mock_parse.return_value = _parsed_feed([{
            "link": "http://example.com/good",
            "title": "Good Article",
            "content": [{"value": "<p>body</p>"}],
            "published_parsed": time.struct_time((2025, 1, 1, 0, 0, 0, 0, 1, 0)),
        }])
        result = fetch_all([FeedSource("aws", "http://aws.example.com/feed")])
        assert [item.source_published_at for item in result.items] == [
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        ]

    @pytest.mark.parametrize("entry, expected_urls", [
        pytest.param(_entry("http://example.com/link", "T"),
                     ["http://example.com/link"],
                     id="link だけのとき、link を source_url にする"),
        pytest.param({"id": "urn:uuid:abc", "title": "T", "content": [{"value": "<p>body</p>"}]},
                     ["urn:uuid:abc"],
                     id="id だけのとき、id を source_url にする"),
        pytest.param({"link": "http://example.com/link", "id": "urn:uuid:abc", "title": "T",
                      "content": [{"value": "<p>body</p>"}]},
                     ["http://example.com/link"],
                     id="link と id が両方あるとき、link を優先する"),
        pytest.param({"title": "T", "content": [{"value": "<p>body</p>"}]},
                     [],
                     id="link も id も無いとき、item 化しない"),
    ])
    def test_source_urlはlinkを優先しidにフォールバックする(self, entry, expected_urls):
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = _parsed_feed([entry])
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert [item.source_url for item in result.items] == expected_urls

    def test_ソース0件はFetchErrorを出さず記事も失敗ソースも0件で返る(self):
        result = fetch_all([])
        assert result.items == []
        assert result.failed_sources == []

    def test_単一ソースの複数有効entryを全てFetchedItem化する(self):
        entries = [
            _entry("http://example.com/0", "Article 0"),
            _entry("http://example.com/1", "Article 1"),
            _entry("http://example.com/2", "Article 2"),
        ]
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = _parsed_feed(entries)
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert [item.source_url for item in result.items] == [
            "http://example.com/0",
            "http://example.com/1",
            "http://example.com/2",
        ]
        assert [item.title for item in result.items] == [
            "Article 0",
            "Article 1",
            "Article 2",
        ]

    def test_全エントリの本文が空のソースは取得失敗として扱わない(self):
        feed = feedparser.parse(_ATOM_EMPTY_CONTENT)
        with patch("newsfeed.fetcher.feedparser.parse", return_value=feed):
            result = fetch_all([FeedSource("only", "http://example.com/feed")])
        assert result.items == []
        assert result.failed_sources == []

    def test_本文が空の記事はソース名とタイトルを添えて記録する(self):
        feed = feedparser.parse(_ATOM_EMPTY_CONTENT)
        with patch("newsfeed.fetcher.feedparser.parse", return_value=feed):
            result = fetch_all([FeedSource("only", "http://example.com/feed")])
        assert result.malformed_entries == [
            MalformedEntry(source="only", title="Empty Content Article"),
        ]

    def test_全記事の本文が揃っているとき記録される不正な記事は0件になる(self):
        with patch("newsfeed.fetcher.feedparser.parse") as mock_parse:
            mock_parse.return_value = _parsed_feed([
                _entry("http://example.com/good", "Good Article"),
            ])
            result = fetch_all([FeedSource("aws", "http://aws.example.com/feed")])
        assert result.malformed_entries == []

    def test_本文が空の記事があっても同じソースの後続記事は取得できる(self):
        bad_then_good = feedparser.parse(_RSS_EMPTY_SUMMARY_THEN_VALID)
        with patch("newsfeed.fetcher.feedparser.parse", return_value=bad_then_good):
            result = fetch_all([FeedSource("src1", "http://example.com/feed")])
        assert [item.title for item in result.items] == ["Good Article"]
        assert [item.body for item in result.items] == ["body"]
        assert result.failed_sources == []

    def test_1ソースの本文が空の記事は他ソースの取得を妨げない(self):
        bad_feed = feedparser.parse(_ATOM_EMPTY_CONTENT)
        good_feed = feedparser.parse(_ATOM_CONTENT_AND_SUMMARY)
        with patch("newsfeed.fetcher.feedparser.parse", side_effect=[bad_feed, good_feed]):
            result = fetch_all([
                FeedSource("bad", "http://bad.example.com/feed"),
                FeedSource("good", "http://good.example.com/feed"),
            ])
        assert [item.source for item in result.items] == ["good"]
        assert [item.body for item in result.items] == ["full body"]
        assert result.failed_sources == []


_RSS_ONE_ARTICLE = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>Feed</title>
<item>
  <title>Good Article</title>
  <link>http://example.com/good</link>
  <description>&lt;p&gt;good body&lt;/p&gt;</description>
</item>
</channel></rss>"""

_RSS_NO_ARTICLE = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>Feed</title></channel></rss>"""

_RSS_CUT_OFF_MIDWAY = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>Feed</title>
<item>
  <title>Good Article</title>
  <link>http://example.com/good</link>
  <description>&lt;p&gt;good body&lt;/p&gt;</description>
</item>"""

_ERROR_PAGE_HTML = "<!DOCTYPE html><html><body><h1>Not Found</h1></body></html>"

# 特権ポートはテスト実行ユーザが listen できないため、接続は必ず拒否される
_UNREACHABLE_URL = "http://127.0.0.1:1/feed"


class Testソース取得の成否判定:
    @pytest.mark.parametrize("status, content_type, body", [
        pytest.param(500, "text/html", _ERROR_PAGE_HTML,
                     id="HTTP 500 でエラーページが返るとき、取得失敗になる"),
        pytest.param(404, "text/html", _ERROR_PAGE_HTML,
                     id="HTTP 404 でエラーページが返るとき、取得失敗になる"),
        pytest.param(200, "text/html", _ERROR_PAGE_HTML,
                     id="HTTP 200 で RSS ではない HTML が返るとき、取得失敗になる"),
        pytest.param(500, "application/rss+xml", _RSS_ONE_ARTICLE,
                     id="HTTP 500 の本文が RSS として読めるとき、取得失敗になる"),
    ])
    def test_フィードを受け取れなかったソースは取得失敗として記録される(
        self, feed_server, status, content_type, body,
    ):
        dead_url = feed_server.serve_feed("/dead", body, status=status, content_type=content_type)
        good_url = feed_server.serve_feed("/good", _RSS_ONE_ARTICLE)

        result = fetch_all([FeedSource("dead", dead_url), FeedSource("good", good_url)])

        assert result.failed_sources == ["dead"]
        assert [item.source for item in result.items] == ["good"]

    def test_接続できないソースは取得失敗として記録される(self, feed_server):
        good_url = feed_server.serve_feed("/good", _RSS_ONE_ARTICLE)

        result = fetch_all([
            FeedSource("down", _UNREACHABLE_URL),
            FeedSource("good", good_url),
        ])

        assert result.failed_sources == ["down"]
        assert [item.source for item in result.items] == ["good"]

    def test_正しいRSSを返すソースは取得失敗にならない(self, feed_server):
        url = feed_server.serve_feed("/feed", _RSS_ONE_ARTICLE)

        result = fetch_all([FeedSource("aws", url)])

        assert result.failed_sources == []
        assert [item.title for item in result.items] == ["Good Article"]
        assert [item.body for item in result.items] == ["good body"]

    def test_リダイレクトの先で正しいRSSを返すソースは取得失敗にならない(self, feed_server):
        target_url = feed_server.serve_feed("/moved-here", _RSS_ONE_ARTICLE)
        url = feed_server.serve_redirect("/feed", target_url)

        result = fetch_all([FeedSource("oci", url)])

        assert result.failed_sources == []
        assert [item.title for item in result.items] == ["Good Article"]

    def test_記事が0件の正しいRSSを返すソースは取得失敗にならない(self, feed_server):
        url = feed_server.serve_feed("/feed", _RSS_NO_ARTICLE)

        result = fetch_all([FeedSource("aws", url)])

        assert result.failed_sources == []
        assert result.items == []

    def test_XMLが途中で切れていても記事を読めるソースは取得失敗にならない(self, feed_server):
        url = feed_server.serve_feed("/feed", _RSS_CUT_OFF_MIDWAY)

        result = fetch_all([FeedSource("aws", url)])

        assert result.failed_sources == []
        assert [item.title for item in result.items] == ["Good Article"]

    def test_全ソースがフィードを受け取れないときFetchErrorになる(self, feed_server):
        first_url = feed_server.serve_feed(
            "/first", _ERROR_PAGE_HTML, status=500, content_type="text/html",
        )
        second_url = feed_server.serve_feed(
            "/second", _ERROR_PAGE_HTML, status=404, content_type="text/html",
        )

        with pytest.raises(FetchError, match="all 2 feed sources failed"):
            fetch_all([FeedSource("aws", first_url), FeedSource("azure", second_url)])
