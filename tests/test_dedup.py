"""DedupStore の結合テスト。

Valkey を testcontainers で起動して実挙動を検証する (matchmaking の
redis_queue_test.go と同じ方針)。各テストは client fixture の FLUSHDB で分離するため、
container は session に 1 つで足りる。
"""
import pytest
import redis
from testcontainers.redis import RedisContainer

from newsfeed.dedup import DedupStore


@pytest.fixture(scope="session")
def start_valkey_container():
    """session 全体で共有する Valkey container を起動する。

    Yields:
        str: 起動した container への redis:// 接続 URL。
    """
    with RedisContainer("valkey/valkey:8-alpine") as valkey:
        host = valkey.get_container_host_ip()
        port = valkey.get_exposed_port(valkey.port)
        yield f"redis://{host}:{port}"


@pytest.fixture
def client(start_valkey_container):
    """テストごとに FLUSHDB 済みの Valkey クライアントを用意する。

    Args:
        start_valkey_container: session fixture が起動した Valkey container の接続 URL。

    Yields:
        redis.Redis: FLUSHDB 済みのクライアント。テスト終了時に close する。
    """
    c = redis.from_url(start_valkey_container, decode_responses=True)
    c.flushdb()
    yield c
    c.close()


@pytest.fixture
def store(client):
    return DedupStore(client)


class TestURLの予約:
    def test_新規URLはTrueを返す(self, store):
        assert store.reserve("https://example.com/a") is True

    def test_同じURLの2回目はFalseを返す(self, store):
        assert store.reserve("https://example.com/a") is True
        assert store.reserve("https://example.com/a") is False

    def test_異なるURLはそれぞれ独立して予約できる(self, store):
        assert store.reserve("https://example.com/a") is True
        assert store.reserve("https://example.com/b") is True

    def test_予約キーに30日以内のTTLを設定する(self, client, store):
        store.reserve("https://example.com/a")
        ttl = client.ttl("newsfeed:seen:https://example.com/a")
        # TTL は設定済み (> 0) かつ上限 30 日 (2592000 秒) 以下
        assert 0 < ttl <= 30 * 24 * 60 * 60


class TestURLの解放:
    def test_解放後は再予約できる(self, store):
        store.reserve("https://example.com/a")
        store.release("https://example.com/a")
        # 解放後は再予約できる (Vertex AI / publish 失敗時の再試行パス)
        assert store.reserve("https://example.com/a") is True

    def test_存在しないURLの解放は何もしない(self, store):
        # DEL は存在しないキーに対しても例外を出さない (redis-py 仕様)
        store.release("https://example.com/nonexistent")
