import os
from unittest.mock import patch

import pytest

import main


class Testエントリポイントの実行:
    def test_パイプラインが例外で失敗したときCRITICALログを出し終了コード1で終了する(self, capsys, preserve_root_logger):
        with patch("main.run", side_effect=RuntimeError("vertex down")), \
                patch.dict(os.environ, {"APP_ENV": "local"}, clear=True):
            with pytest.raises(SystemExit) as excinfo:
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
