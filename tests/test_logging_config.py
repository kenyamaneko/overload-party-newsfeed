import json
import logging

import pytest

from newsfeed.config import APP_ENV_LOCAL, APP_ENV_PRODUCTION
from newsfeed.logging_config import configure_logging


class Test本番環境のログ出力:
    def test_productionのときログがseverityとmessageを持つ1行JSONで出力される(self, capsys, preserve_root_logger):
        configure_logging(APP_ENV_PRODUCTION)
        logging.getLogger("newsfeed.test").info("hello")

        decoded = json.loads(capsys.readouterr().out.strip())
        assert decoded["severity"] == "INFO"
        assert "hello" in decoded["message"]
        assert decoded["logger"] == "newsfeed.test"

    def test_例外情報付きのログのときmessageにスタックトレースが連結される(self, capsys, preserve_root_logger):
        configure_logging(APP_ENV_PRODUCTION)
        logger = logging.getLogger("newsfeed.test")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.exception("failed")

        decoded = json.loads(capsys.readouterr().out.strip())
        assert "RuntimeError" in decoded["message"]


class Testlocal環境のログ出力:
    def test_localのときログがテキスト形式で出力される(self, capsys, preserve_root_logger):
        configure_logging(APP_ENV_LOCAL)
        logging.getLogger("newsfeed.test").info("hello")

        out = capsys.readouterr().out
        assert "INFO" in out
        assert "hello" in out


class Test不正なAPP_ENVの検証:
    def test_localとproduction以外の値devのときエラーになる(self):
        with pytest.raises(ValueError, match="APP_ENV"):
            configure_logging("dev")
