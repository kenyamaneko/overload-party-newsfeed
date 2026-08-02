import os
from functools import partial
from unittest.mock import MagicMock, patch

import pytest

import main
from newsfeed.config import Config
from newsfeed.model import FetchedItem, FetchResult, SummarizeResult
from newsfeed.runner import run


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
        assert "azure" in out
