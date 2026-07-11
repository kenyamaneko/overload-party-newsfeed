"""newsfeed のログ出力設定。"""
import json
import logging
import sys
from datetime import datetime, timezone

from newsfeed.config import APP_ENV_LOCAL, APP_ENV_PRODUCTION

_LOCAL_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class CloudLoggingFormatter(logging.Formatter):
    """ログレコードを Cloud Logging 互換の 1 行 JSON に整形する。"""

    def format(self, record: logging.LogRecord) -> str:
        """ログレコードを Cloud Logging 互換の 1 行 JSON 文字列に変換する。

        Args:
            record: 整形対象のログレコード。

        Returns:
            Cloud Logging が severity として解釈できる 1 行 JSON 文字列。
        """
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        payload = {
            "severity": record.levelname,
            "message": message,
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "logger": record.name,
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(app_env: str) -> None:
    """APP_ENV に応じてルートロガーの出力形式を設定する。

    Args:
        app_env: 実行環境。APP_ENV_PRODUCTION なら Cloud Logging 互換 JSON、
            APP_ENV_LOCAL ならテキストで出力する。

    Raises:
        ValueError: app_env が APP_ENV_LOCAL / APP_ENV_PRODUCTION のいずれでもない場合。
    """
    if app_env == APP_ENV_PRODUCTION:
        formatter: logging.Formatter = CloudLoggingFormatter()
    elif app_env == APP_ENV_LOCAL:
        formatter = logging.Formatter(_LOCAL_TEXT_FORMAT)
    else:
        raise ValueError(
            f"APP_ENV must be one of {(APP_ENV_LOCAL, APP_ENV_PRODUCTION)}, got: {app_env!r}"
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # 二重ログや既定ハンドラーとの混在を防ぐため、既存ハンドラーを置き換える。
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
