import os
from dataclasses import dataclass

_REQUIRED_VARS = ("GOOGLE_CLOUD_PROJECT",)


@dataclass(frozen=True)
class Config:
    """newsfeed パイプラインの実行時設定を保持します。"""

    google_cloud_project: str


def load_config() -> Config:
    """環境変数から Config を読み込みます。"""
    missing = [k for k in _REQUIRED_VARS if not os.environ.get(k)]
    if missing:
        raise ValueError(f"missing required env vars: {missing}")
    return Config(
        google_cloud_project=os.environ["GOOGLE_CLOUD_PROJECT"],
    )
