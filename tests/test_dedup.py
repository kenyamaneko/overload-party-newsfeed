"""DedupStore の結合テスト。

docker-compose の Valkey 相手に実挙動を検証する (matchmaking の
redis_queue_test.go と同じ方針)。DB 1 を使うのは run-local (.env.local) の
DB 0 と分離するため — テストは毎回 FLUSHDB するので、ジョブのマーカーと
同居させない。

Valkey 未起動のときは Ping で明示的に fail させる (silent skip を避ける)。
`make up` もしくは `docker compose up -d redis` が前提。
"""
import time

import pytest
import redis

from newsfeed.dedup import DedupStore

_TEST_REDIS_URL = "redis://localhost:6379/1"


@pytest.fixture
def client():
    c = redis.from_url(_TEST_REDIS_URL, decode_responses=True)
    try:
        c.ping()
    except redis.ConnectionError as e:
        pytest.fail(
            f"Redis not reachable at {_TEST_REDIS_URL}: {e}. "
            "Run `make up` or `docker compose up -d redis` first."
        )
    c.flushdb()
    yield c
    c.close()


@pytest.fixture
def store(client):
    return DedupStore(client)


class TestReserve:
    def test_new_url_returns_true(self, store):
        assert store.reserve("https://example.com/a") is True

    def test_same_url_returns_false_on_second_call(self, store):
        assert store.reserve("https://example.com/a") is True
        assert store.reserve("https://example.com/a") is False

    def test_different_urls_are_independent(self, store):
        assert store.reserve("https://example.com/a") is True
        assert store.reserve("https://example.com/b") is True

    def test_sets_30_day_ttl(self, client, store):
        store.reserve("https://example.com/a")
        ttl = client.ttl("newsfeed:seen:https://example.com/a")
        # TTL は設定済み (> 0) かつ上限 30 日 (2592000 秒) 以下
        assert 0 < ttl <= 30 * 24 * 60 * 60


class TestRelease:
    def test_releasing_allows_re_reserve(self, store):
        store.reserve("https://example.com/a")
        store.release("https://example.com/a")
        # 解放後は再予約できる (Vertex AI / publish 失敗時の再試行パス)
        assert store.reserve("https://example.com/a") is True

    def test_releasing_unknown_url_is_noop(self, store):
        # DEL は存在しないキーに対しても例外を出さない (redis-py 仕様)
        store.release("https://example.com/nonexistent")


class TestExpiry:
    def test_reserved_url_becomes_available_after_ttl(self, client):
        """短 TTL をセットして、期限切れ後は再予約できることを確認する。

        30 日 TTL の挙動を直接テストするのは非現実的なので、本テストは
        expire(1) で短 TTL を強制する。DedupStore の API 経由ではなく
        低レベル redis client を使って「TTL が効いている」点だけ保証する。
        """
        key = "newsfeed:seen:https://example.com/short"
        client.set(key, "1", nx=True, ex=1)
        assert client.get(key) == "1"
        time.sleep(1.2)
        assert client.get(key) is None


class TestAtomicity:
    def test_setnx_prevents_concurrent_double_reservation(self, store):
        """SETNX のアトミック性: 連続呼び出しで最初だけ True。

        同一プロセス内で検査するため厳密な並行性テストではないが、
        `set(..., nx=True)` が check+mark を 1 コマンドで行う契約が
        崩れていないことを担保する。
        """
        url = "https://example.com/race"
        first = store.reserve(url)
        second = store.reserve(url)
        third = store.reserve(url)
        assert first is True
        assert second is False
        assert third is False
