"""newsfeed パイプラインの実行時設定。

APP_ENV=local のときは env var 直読み、それ以外は GCP Secret Manager から
Upstash Redis 接続情報を取得する (ADR-020 §Secret Manager)。matchmaking の
接続パターンに合わせている。
"""
import os
from dataclasses import dataclass
from urllib.parse import quote

from newsfeed.secret_manager import SecretAccessor

_REDIS_ENDPOINT_SECRET = "newsfeed-upstash-redis-endpoint"
_REDIS_PASSWORD_SECRET = "newsfeed-upstash-redis-password"


@dataclass(frozen=True)
class Config:
    """Cloud Run Job 実行に必要な外部接続情報を保持する。"""

    google_cloud_project: str
    redis_url: str
    vertex_location: str


def load_config() -> Config:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise ValueError("missing required env var: GOOGLE_CLOUD_PROJECT")

    vertex_location = os.environ.get("VERTEX_LOCATION")
    if not vertex_location:
        raise ValueError("missing required env var: VERTEX_LOCATION")

    app_env = os.environ.get("APP_ENV")
    if not app_env:
        raise ValueError("missing required env var: APP_ENV (expected 'local' / 'dev' / 'stg' / 'prod')")

    redis_url = _load_redis_url(app_env, project)

    return Config(
        google_cloud_project=project,
        redis_url=redis_url,
        vertex_location=vertex_location,
    )


def _load_redis_url(app_env: str, project_id: str) -> str:
    if app_env == "local":
        url = os.environ.get("UPSTASH_REDIS_URL")
        if not url:
            raise ValueError("missing required env var (APP_ENV=local): UPSTASH_REDIS_URL")
        return url

    accessor = SecretAccessor(project_id)
    endpoint = accessor.access(_REDIS_ENDPOINT_SECRET)
    password = accessor.access(_REDIS_PASSWORD_SECRET)
    # Upstash は TLS 必須のため rediss://。パスワードは URL エンコードする
    return f"rediss://default:{quote(password, safe='')}@{endpoint}"
