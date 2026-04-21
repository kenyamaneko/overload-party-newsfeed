"""newsfeed パイプラインの実行時設定。

APP_ENV は 'local' / 'production' の 2 値のみ (matchmaking と同じ)。
- local: UPSTASH_REDIS_URL を env var から直読み
- production: GCP Secret Manager から Upstash 接続情報を取得

dev / stg / prod の区別は GOOGLE_CLOUD_PROJECT (別プロジェクト) で吸収し、
APP_ENV では「Secret Manager を経由するかどうか」だけを切り替える
(ADR-020 §Secret Manager)。
"""
import os
from dataclasses import dataclass
from urllib.parse import quote

from newsfeed.secret_manager import SecretAccessor

_REDIS_ENDPOINT_SECRET = "newsfeed-upstash-redis-endpoint"
_REDIS_PASSWORD_SECRET = "newsfeed-upstash-redis-password"

APP_ENV_LOCAL = "local"
APP_ENV_PRODUCTION = "production"
_VALID_APP_ENVS = (APP_ENV_LOCAL, APP_ENV_PRODUCTION)


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
    if app_env not in _VALID_APP_ENVS:
        raise ValueError(
            f"APP_ENV must be one of {_VALID_APP_ENVS}, got: {app_env!r}"
        )

    redis_url = _load_redis_url(app_env, project)

    return Config(
        google_cloud_project=project,
        redis_url=redis_url,
        vertex_location=vertex_location,
    )


def _load_redis_url(app_env: str, project_id: str) -> str:
    if app_env == APP_ENV_LOCAL:
        url = os.environ.get("UPSTASH_REDIS_URL")
        if not url:
            raise ValueError("missing required env var (APP_ENV=local): UPSTASH_REDIS_URL")
        return url

    accessor = SecretAccessor(project_id)
    endpoint = accessor.access(_REDIS_ENDPOINT_SECRET)
    password = accessor.access(_REDIS_PASSWORD_SECRET)
    # Upstash は TLS 必須のため rediss://。パスワードは URL エンコードする
    return f"rediss://default:{quote(password, safe='')}@{endpoint}"
