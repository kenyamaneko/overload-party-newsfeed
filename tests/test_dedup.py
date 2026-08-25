import threading
import time

from newsfeed.dedup import DedupStore

_THIRTY_DAYS_SECONDS = 30 * 24 * 60 * 60


def _the_only_key(redis_client) -> str:
    """DB を空にした状態で reserve() を 1 回呼んだ後に残る唯一のキーを特定する。

    Args:
        redis_client: 検証対象の Valkey クライアント。

    Returns:
        reserve() が作成したキー。
    """
    keys = redis_client.keys("*")
    assert len(keys) == 1
    return keys[0]


class Test予約と解放:
    def test_未予約のURLを予約すると予約は成功する(self, redis_client):
        store = DedupStore(redis_client)

        assert store.reserve("https://example.com/a") is True

    def test_予約済みのURLを再度予約しようとすると予約は失敗する(self, redis_client):
        store = DedupStore(redis_client)
        store.reserve("https://example.com/a")

        assert store.reserve("https://example.com/a") is False

    def test_予約を解放したURLはその後再び予約できるようになる(self, redis_client):
        store = DedupStore(redis_client)
        store.reserve("https://example.com/a")

        store.release("https://example.com/a")

        assert store.reserve("https://example.com/a") is True

    def test_同一の未予約URLに複数スレッドから同時に予約を試みると成功するのは1回だけになる(self, redis_client):
        store = DedupStore(redis_client)
        thread_count = 8
        barrier = threading.Barrier(thread_count)
        results: list[bool] = [False] * thread_count

        def attempt(index: int) -> None:
            barrier.wait()
            results[index] = store.reserve("https://example.com/race")

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == thread_count - 1


class Test予約の有効期限:
    def test_有効期限が経過したURLはその後再び予約できるようになる(self, redis_client):
        store = DedupStore(redis_client)
        store.reserve("https://example.com/a")
        key = _the_only_key(redis_client)
        redis_client.pexpire(key, 50)
        time.sleep(0.2)

        assert store.reserve("https://example.com/a") is True

    def test_新規に予約したURLの有効期限は30日相当である(self, redis_client):
        store = DedupStore(redis_client)
        store.reserve("https://example.com/a")
        key = _the_only_key(redis_client)

        ttl = redis_client.ttl(key)

        assert _THIRTY_DAYS_SECONDS - 60 <= ttl <= _THIRTY_DAYS_SECONDS
