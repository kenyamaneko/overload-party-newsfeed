import os
from functools import partial
from unittest.mock import MagicMock, patch

import feedparser
import pytest

import main
from newsfeed.config import Config
from newsfeed.fetcher import FeedSource
from newsfeed.model import FetchedItem, FetchResult, SummarizeResult
from newsfeed.runner import run

_RSS_ONE_ARTICLE = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>T</title>
<item>
  <title>Good Article</title>
  <link>http://example.com/good</link>
  <description>&lt;p&gt;good body&lt;/p&gt;</description>
</item>
</channel></rss>"""

_ERROR_PAGE_HTML = "<!DOCTYPE html><html><body><h1>Service Unavailable</h1></body></html>"

_RSS_EMPTY_BODY_THEN_VALID = """<?xml version="1.0"?>
<rss version="2.0">
<channel><title>T</title>
<item>
  <title>Broken Article</title>
  <link>http://example.com/broken</link>
  <description></description>
</item>
<item>
  <title>Good Article</title>
  <link>http://example.com/good</link>
  <description>&lt;p&gt;good body&lt;/p&gt;</description>
</item>
</channel></rss>"""


def _fakes(publisher) -> dict:
    """run() に注入する外部境界の代用一式を組み立てる。

    Args:
        publisher: publish 呼び出しを観測するための代用。

    Returns:
        run() のキーワード引数として渡す代用一式。
    """
    dedup = MagicMock()
    dedup.reserve.return_value = True
    summarizer = MagicMock()
    summarizer.summarize.return_value = SummarizeResult(summary="要約", tags=[])
    return {
        "cfg": Config(
            google_cloud_project="test-project",
            redis_url="redis://localhost:6379",
            vertex_location="us-central1",
        ),
        "dedup": dedup,
        "summarizer": summarizer,
        "publisher": publisher,
    }


class Testエントリポイントの実行:
    def test_パイプラインが例外で失敗したときCRITICALログを出し終了コード1で終了する(self, capsys, preserve_root_logger):
        with patch("main.run", side_effect=RuntimeError("vertex down")), \
                patch.dict(os.environ, {"APP_ENV": "local"}, clear=True), \
                pytest.raises(SystemExit) as excinfo:
            main.main()

        assert excinfo.value.code == 1
        out = capsys.readouterr().out
        assert "CRITICAL" in out
        assert "vertex down" in out

    def test_パイプラインが成功したとき例外や終了コードを出さず完了する(self, preserve_root_logger):
        with patch("main.run") as mock_run, \
                patch.dict(os.environ, {"APP_ENV": "local"}, clear=True):
            main.main()

        mock_run.assert_called_once()

    def test_一部のRSSソースの取得に失敗したとき成功分をpublishした上で終了コード1で終了する(
        self, capsys, preserve_root_logger,
    ):
        publisher = MagicMock()
        fetched = FetchResult(
            items=[FetchedItem(
                source="aws",
                source_url="https://example.com/1",
                title="Article 1",
                body="body1",
            )],
            failed_sources=["azure"],
            malformed_entries=[],
        )
        with patch("newsfeed.runner.fetch_all", return_value=fetched), \
                patch("main.run", partial(run, **_fakes(publisher))), \
                patch.dict(os.environ, {"APP_ENV": "local"}, clear=True), \
                pytest.raises(SystemExit) as excinfo:
            main.main()

        assert excinfo.value.code == 1
        assert publisher.publish.call_args[0][0].source_url == "https://example.com/1"
        out = capsys.readouterr().out
        assert "CRITICAL" in out
        assert "1 feed source(s) failed to fetch: azure" in out

    def test_RSSソースがエラー応答を返すとき他ソースを配信した上で終了コード1で終了する(
        self, capsys, preserve_root_logger, feed_server,
    ):
        dead_url = feed_server.serve_feed(
            "/dead", _ERROR_PAGE_HTML, status=503, content_type="text/html",
        )
        good_url = feed_server.serve_feed("/good", _RSS_ONE_ARTICLE)
        publisher = MagicMock()
        with patch("newsfeed.runner.DEFAULT_SOURCES",
                   [FeedSource("azure", dead_url), FeedSource("aws", good_url)]), \
                patch("main.run", partial(run, **_fakes(publisher))), \
                patch.dict(os.environ, {"APP_ENV": "local"}, clear=True), \
                pytest.raises(SystemExit) as excinfo:
            main.main()

        assert excinfo.value.code == 1
        assert publisher.publish.call_count == 1
        assert publisher.publish.call_args[0][0].title == "Good Article"
        out = capsys.readouterr().out
        assert "CRITICAL" in out
        assert "1 feed source(s) failed to fetch: azure" in out

    def test_全RSSソースがエラー応答を返すとき何も配信せず終了コード1で終了する(
        self, capsys, preserve_root_logger, feed_server,
    ):
        dead_url = feed_server.serve_feed(
            "/dead", _ERROR_PAGE_HTML, status=503, content_type="text/html",
        )
        publisher = MagicMock()
        with patch("newsfeed.runner.DEFAULT_SOURCES",
                   [FeedSource("azure", dead_url), FeedSource("aws", dead_url)]), \
                patch("main.run", partial(run, **_fakes(publisher))), \
                patch.dict(os.environ, {"APP_ENV": "local"}, clear=True), \
                pytest.raises(SystemExit) as excinfo:
            main.main()

        assert excinfo.value.code == 1
        publisher.publish.assert_not_called()
        out = capsys.readouterr().out
        assert "CRITICAL" in out
        assert "all 2 feed sources failed" in out

    def test_本文が空の記事があっても同じソースの後続記事を配信し終了コード1で終了する(
        self, capsys, preserve_root_logger,
    ):
        publisher = MagicMock()
        feed = feedparser.parse(_RSS_EMPTY_BODY_THEN_VALID)
        with patch("newsfeed.fetcher.feedparser.parse", return_value=feed), \
                patch("newsfeed.runner.DEFAULT_SOURCES",
                      [FeedSource("aws", "http://aws.example.com/feed")]), \
                patch("main.run", partial(run, **_fakes(publisher))), \
                patch.dict(os.environ, {"APP_ENV": "local"}, clear=True), \
                pytest.raises(SystemExit) as excinfo:
            main.main()

        assert excinfo.value.code == 1
        assert publisher.publish.call_count == 1
        event = publisher.publish.call_args[0][0]
        assert event.title == "Good Article"
        assert event.body == "good body"
        out = capsys.readouterr().out
        assert "CRITICAL" in out
        assert "1 entry(ies) skipped for empty body: aws:Broken Article" in out
