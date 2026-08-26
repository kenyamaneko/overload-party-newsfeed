from datetime import datetime, timezone

import feedparser
import pytest

from newsfeed.fetcher import (
    FeedSource,
    FetchError,
    MalformedEntryError,
    extract_entry_body,
    fetch_all,
)
from newsfeed.model import MalformedEntry

_ERROR_PAGE_HTML = "<!DOCTYPE html><html><body><h1>Service Unavailable</h1></body></html>"


def _rss(items_xml: str) -> str:
    """<item> 断片を差し込んだ RSS 2.0 フィード全体を組み立てる。

    Args:
        items_xml: <item>...</item> を連結した断片。

    Returns:
        content:encoded 名前空間を含む RSS フィード全体の XML 文字列。
    """
    return (
        '<?xml version="1.0"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">\n'
        f"<channel><title>T</title>\n{items_xml}\n</channel></rss>"
    )


class Testソース単位の取得:
    def test_正常なRSSを返すソースの記事が取得結果に含まれる(self, feed_server):
        url = feed_server.serve_feed(
            "/good",
            _rss("<item><title>Good Article</title><link>http://example.com/good</link>"
                 "<description>good body</description></item>"),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert [item.source_url for item in result.items] == ["http://example.com/good"]
        assert result.failed_sources == []

    def test_400以上のHTTPステータスで応答したソースは取得失敗として記録され記事一覧に含まれない(self, feed_server):
        dead_url = feed_server.serve_feed(
            "/dead",
            _rss("<item><title>Should Not Appear</title><link>http://example.com/x</link>"
                 "<description>body</description></item>"),
            status=503,
        )
        good_url = feed_server.serve_feed(
            "/good",
            _rss("<item><title>Good Article</title><link>http://example.com/good</link>"
                 "<description>body</description></item>"),
        )

        result = fetch_all([FeedSource("azure", dead_url), FeedSource("aws", good_url)])

        assert result.failed_sources == ["azure"]
        assert [item.source_url for item in result.items] == ["http://example.com/good"]

    def test_リダイレクト応答を経由して正常なRSSへ到達したソースは取得失敗にならずリダイレクト先の記事が含まれる(self, feed_server):
        good_url = feed_server.serve_feed(
            "/good",
            _rss("<item><title>Redirected Article</title><link>http://example.com/redirected</link>"
                 "<description>body</description></item>"),
        )
        redirect_url = feed_server.serve_redirect("/dead", good_url)

        result = fetch_all([FeedSource("google-cloud", redirect_url)])

        assert result.failed_sources == []
        assert [item.source_url for item in result.items] == ["http://example.com/redirected"]

    def test_RSSとして解釈できずかつ記事が1件も読み取れない応答のソースは取得失敗として記録される(self, feed_server):
        html_url = feed_server.serve_feed("/html", _ERROR_PAGE_HTML, content_type="text/html")
        good_url = feed_server.serve_feed(
            "/good",
            _rss("<item><title>Good Article</title><link>http://example.com/good</link>"
                 "<description>body</description></item>"),
        )

        result = fetch_all([FeedSource("aws", html_url), FeedSource("azure", good_url)])

        assert result.failed_sources == ["aws"]
        assert [item.source_url for item in result.items] == ["http://example.com/good"]

    def test_一部の書式が壊れているが記事を読み取れる応答のソースは取得失敗にならず読み取れた記事が含まれる(self, feed_server):
        url = feed_server.serve_feed(
            "/broken",
            _rss("<item><title>Unclosed & Ampersand</title><link>http://example.com/broken</link>"
                 "<description>body</description>"),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert result.failed_sources == []
        assert [item.source_url for item in result.items] == ["http://example.com/broken"]

    def test_複数のソースのうち1つが失敗しても他のソースの記事は取得結果に反映される(self, feed_server):
        good_url = feed_server.serve_feed(
            "/good",
            _rss("<item><title>Good Article</title><link>http://example.com/good</link>"
                 "<description>body</description></item>"),
        )
        dead_url = feed_server.serve_feed("/dead", _ERROR_PAGE_HTML, status=503, content_type="text/html")

        result = fetch_all([FeedSource("azure", dead_url), FeedSource("aws", good_url)])

        assert result.failed_sources == ["azure"]
        assert [item.source_url for item in result.items] == ["http://example.com/good"]

    def test_全てのソースが取得に失敗したとき取得は例外で失敗し記事は1件も返らない(self, feed_server):
        dead_url_1 = feed_server.serve_feed("/dead1", _ERROR_PAGE_HTML, status=503, content_type="text/html")
        dead_url_2 = feed_server.serve_feed("/dead2", _ERROR_PAGE_HTML, status=500, content_type="text/html")

        with pytest.raises(FetchError):
            fetch_all([FeedSource("azure", dead_url_1), FeedSource("aws", dead_url_2)])

    def test_少なくとも1つのソースが成功したとき例外にならず失敗したソース名を含む結果が返る(self, feed_server):
        good_url = feed_server.serve_feed(
            "/good",
            _rss("<item><title>Good Article</title><link>http://example.com/good</link>"
                 "<description>body</description></item>"),
        )
        dead_url = feed_server.serve_feed("/dead", _ERROR_PAGE_HTML, status=503, content_type="text/html")

        result = fetch_all([FeedSource("azure", dead_url), FeedSource("aws", good_url)])

        assert result.failed_sources == ["azure"]


class Testエントリの選別:
    def test_リンクもIDも無いエントリは記事一覧にも本文欠落の記録にも含まれない(self, feed_server):
        url = feed_server.serve_feed(
            "/mixed",
            _rss(
                "<item><title>No Link No Id</title><description>body</description></item>"
                "<item><title>Normal Article</title><link>http://example.com/normal</link>"
                "<description>body</description></item>",
            ),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert [item.title for item in result.items] == ["Normal Article"]
        assert result.malformed_entries == []

    def test_linkが無くisPermaLinkがfalseのguidとタイトルがあるエントリはguidの値がURLとして記事一覧に含まれる(self, feed_server):
        url = feed_server.serve_feed(
            "/guid",
            _rss(
                '<item><title>Guid Article</title>'
                '<guid isPermaLink="false">urn:uuid:fixed-guid-1</guid>'
                "<description>body</description></item>",
            ),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert len(result.items) == 1
        assert result.items[0].source_url == "urn:uuid:fixed-guid-1"

    def test_タイトルが無いエントリは記事一覧にも本文欠落の記録にも含まれない(self, feed_server):
        url = feed_server.serve_feed(
            "/notitle",
            _rss(
                "<item><link>http://example.com/notitle</link><description>body</description></item>"
                "<item><title>Normal Article</title><link>http://example.com/normal</link>"
                "<description>body</description></item>",
            ),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert [item.title for item in result.items] == ["Normal Article"]
        assert result.malformed_entries == []

    def test_本文が空のエントリは本文欠落として記録され記事一覧には含まれない(self, feed_server):
        url = feed_server.serve_feed(
            "/emptybody",
            _rss(
                "<item><title>Broken Article</title><link>http://example.com/broken</link>"
                "<description></description></item>",
            ),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert result.items == []
        assert result.malformed_entries == [MalformedEntry(source="aws", title="Broken Article")]

    def test_本文欠落エントリより後の同じソースの本文を読み取れるエントリは記事一覧に含まれる(self, feed_server):
        url = feed_server.serve_feed(
            "/mixedbody",
            _rss(
                "<item><title>Broken Article</title><link>http://example.com/broken</link>"
                "<description></description></item>"
                "<item><title>Good Article</title><link>http://example.com/good</link>"
                "<description>good body</description></item>",
            ),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert [item.title for item in result.items] == ["Good Article"]
        assert result.malformed_entries == [MalformedEntry(source="aws", title="Broken Article")]

    def test_公開日時の情報が無いエントリの記事は公開日時が値を持たない(self, feed_server):
        url = feed_server.serve_feed(
            "/nodate",
            _rss(
                "<item><title>No Date Article</title><link>http://example.com/nodate</link>"
                "<description>body</description></item>",
            ),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert result.items[0].source_published_at is None

    def test_公開日時の情報があるエントリの記事の公開日時はUTCの日時に変換される(self, feed_server):
        url = feed_server.serve_feed(
            "/withdate",
            _rss(
                "<item><title>Dated Article</title><link>http://example.com/dated</link>"
                "<description>body</description>"
                "<pubDate>Mon, 01 Jan 2024 19:00:00 +0900</pubDate></item>",
            ),
        )

        result = fetch_all([FeedSource("aws", url)])

        assert result.items[0].source_published_at == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


class Test本文抽出:
    def _entry(self, item_xml: str):
        feed = feedparser.parse(_rss(item_xml))
        return feed.entries[0]

    def test_content_encodedに本文があるときタグを除去したプレーンテキストが本文になる(self):
        entry = self._entry(
            "<item><title>T</title><link>http://example.com/1</link>"
            "<content:encoded><![CDATA[<p>Full body text</p>]]></content:encoded>"
            "<description>short desc</description></item>",
        )

        assert extract_entry_body(entry, "T") == "Full body text"

    @pytest.mark.parametrize(
        "item_xml",
        [
            pytest.param(
                "<item><title>T</title><link>http://example.com/1</link>"
                "<description>&lt;p&gt;desc body&lt;/p&gt;</description></item>",
                id="content_encodedが無いとき",
            ),
            pytest.param(
                "<item><title>T</title><link>http://example.com/1</link>"
                "<content:encoded><![CDATA[<br/>]]></content:encoded>"
                "<description>&lt;p&gt;desc body&lt;/p&gt;</description></item>",
                id="content_encodedのタグを除去すると空になるとき",
            ),
        ],
    )
    def test_content_encodedが使えないときdescriptionのプレーンテキストが本文になる(self, item_xml):
        entry = self._entry(item_xml)

        assert extract_entry_body(entry, "T") == "desc body"

    def test_content_encodedにもdescriptionにもタグ除去後に残る内容が無いとき本文抽出は例外で失敗する(self):
        entry = self._entry(
            "<item><title>T</title><link>http://example.com/1</link>"
            "<content:encoded><![CDATA[<br/>]]></content:encoded>"
            "<description></description></item>",
        )

        with pytest.raises(MalformedEntryError):
            extract_entry_body(entry, "T")

    def test_段落見出しリストなど区切りとなる要素の境界で改行される(self):
        entry = self._entry(
            "<item><title>T</title><link>http://example.com/1</link>"
            "<content:encoded><![CDATA[<h1>Heading</h1><p>Paragraph one</p>"
            "<ul><li>Item A</li><li>Item B</li></ul>]]></content:encoded></item>",
        )

        result = extract_entry_body(entry, "T")

        lines = [line.strip() for line in result.splitlines() if line.strip()]
        assert lines == ["Heading", "Paragraph one", "Item A", "Item B"]

    def test_本文の前後に余分な空白は残らない(self):
        entry = self._entry(
            "<item><title>T</title><link>http://example.com/1</link>"
            "<content:encoded><![CDATA[<h1>Heading</h1><p>Paragraph one</p>"
            "<ul><li>Item A</li><li>Item B</li></ul>]]></content:encoded></item>",
        )

        result = extract_entry_body(entry, "T")

        assert result == result.strip()
