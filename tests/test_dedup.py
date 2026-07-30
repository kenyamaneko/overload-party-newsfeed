"""DedupStore の結合テスト。

Valkey を testcontainers で起動して実挙動を検証する (matchmaking の
redis_queue_test.go と同じ方針)。container は conftest.py の session fixture を
test_runner.py と共有し、各テストは redis_client fixture の FLUSHDB で分離する。
"""
import time

import pytest

from newsfeed.dedup import DedupStore


@pytest.fixture
def store(redis_client):
    return DedupStore(redis_client)


class TestURLの予約:
    def test_新規URLはTrueを返す(self, store):
        assert store.reserve("https://example.com/a") is True

    def test_同じURLの2回目はFalseを返す(self, store):
        assert store.reserve("https://example.com/a") is True
        assert store.reserve("https://example.com/a") is False

    def test_異なるURLはそれぞれ独立して予約できる(self, store):
        assert store.reserve("https://example.com/a") is True
        assert store.reserve("https://example.com/b") is True

    def test_予約キーに30日以内のTTLを設定する(self, redis_client, store):
        store.reserve("https://example.com/a")
        ttl = redis_client.ttl("newsfeed:seen:https://example.com/a")
        # TTL は設定済み (> 0) かつ上限 30 日 (2592000 秒) 以下
        assert 0 < ttl <= 30 * 24 * 60 * 60

    def test_TTL経過後は同一URLを再予約できる(self, store, monkeypatch):
        # production の TTL (30日) を待てないため、production 経路 (reserve() 内部)
        # に短い TTL を注入して期限切れを実際に発生させる
        monkeypatch.setattr("newsfeed.dedup._TTL_SECONDS", 1)

        assert store.reserve("https://example.com/a") is True
        time.sleep(1.2)
        assert store.reserve("https://example.com/a") is True


class TestURLの解放:
    def test_解放後は再予約できる(self, store):
        store.reserve("https://example.com/a")
        store.release("https://example.com/a")
        # 解放後は再予約できる (Vertex AI / publish 失敗時の再試行パス)
        assert store.reserve("https://example.com/a") is True

    def test_存在しないURLの解放は何もしない(self, store):
        # DEL は存在しないキーに対しても例外を出さない (redis-py 仕様)
        store.release("https://example.com/nonexistent")
