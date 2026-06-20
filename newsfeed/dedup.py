"""Upstash Redis による source_url dedup (ADR-020)。

SET ... NX EX で check+mark をアトミックに行い、TTL 期間内の同一 URL を
再要約・再 publish させない。Vertex AI / publish 失敗時は release() で
マーカーを解放し、次周期の再試行を可能にする。
"""
import redis

_KEY_PREFIX = "newsfeed:seen:"
_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 日 (ADR-020)


class DedupStore:
    """source_url の予約/解放を Redis の SETNX で扱う。"""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def reserve(self, source_url: str) -> bool:
        """source_url を予約する。新規なら True、既存なら False。"""
        key = _KEY_PREFIX + source_url
        # redis-py の set は NX 失敗時に None を返す
        result = self._client.set(key, "1", nx=True, ex=_TTL_SECONDS)
        return bool(result)

    def release(self, source_url: str) -> None:
        """予約を解放する (Vertex AI / publish 失敗時の再試行用)。"""
        key = _KEY_PREFIX + source_url
        self._client.delete(key)


def create_client_from_url(url: str) -> redis.Redis:
    """接続 URL から redis.Redis クライアントを作成する。

    decode_responses=True により全レスポンスが str で返る (bytes/str 分岐の排除)。
    Upstash 本番用 rediss:// と local の redis:// の両方を扱える。
    """
    return redis.from_url(url, decode_responses=True)
