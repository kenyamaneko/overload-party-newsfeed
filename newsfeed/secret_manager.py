"""GCP Secret Manager アクセサ。

本番環境で Upstash Redis 接続情報を取得するために使う (ADR-020)。
Local 開発では config.py が APP_ENV=local で分岐して本モジュールを経由しない。
"""
from google.cloud import secretmanager


class SecretAccessor:
    """指定プロジェクトの Secret Manager から最新版の secret を取得する。"""

    def __init__(self, project_id: str) -> None:
        self._client = secretmanager.SecretManagerServiceClient()
        self._project_id = project_id

    def access(self, secret_id: str) -> str:
        """secret_id の最新版を文字列として返す。見つからない場合は例外。"""
        name = f"projects/{self._project_id}/secrets/{secret_id}/versions/latest"
        response = self._client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
