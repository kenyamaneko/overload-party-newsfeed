"""テスト全体で共有する pytest フィクスチャ。"""
import logging

import pytest


@pytest.fixture
def preserve_root_logger():
    """ルートロガーのハンドラとレベルを退避し、テスト終了後に復元する。

    configure_logging はルートロガーのハンドラを丸ごと置き換えるため、
    この fixture を挟まないと設定が他のテストへ漏れる。

    Yields:
        None
    """
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
