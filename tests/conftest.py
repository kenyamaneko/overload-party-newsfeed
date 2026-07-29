"""テスト全体で共有する pytest フィクスチャ。"""
import logging

import pytest
import redis
from testcontainers.redis import RedisContainer


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


@pytest.fixture(scope="session")
def valkey_url():
    """テストセッション全体で共有する Valkey container の接続 URL。

    Yields:
        str: 起動した container への redis:// 接続 URL。
    """
    with RedisContainer("valkey/valkey:8-alpine") as valkey:
        host = valkey.get_container_host_ip()
        port = valkey.get_exposed_port(valkey.port)
        yield f"redis://{host}:{port}"


@pytest.fixture
def redis_client(valkey_url):
    """テストごとに FLUSHDB 済みの Valkey クライアントを用意する。

    Yields:
        redis.Redis: FLUSHDB 済みのクライアント。テスト終了時に close する。
    """
    c = redis.from_url(valkey_url, decode_responses=True)
    c.flushdb()
    yield c
    c.close()
