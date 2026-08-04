"""パイプラインの実行ロジックが依存する外部境界の interface。

実行ロジックが Pub/Sub・Vertex AI・Redis の具体的な実装へ直接依存しないよう、
必要な操作だけをここで宣言する。
"""
from typing import Protocol

from newsfeed.model import ArticleEvent, SummarizeResult


class DedupStore(Protocol):
    """処理済みの source_url を記録し、同じ記事の再処理を抑止する。"""

    def reserve(self, source_url: str) -> bool:
        """source_url を予約する。

        Args:
            source_url: 予約する記事の URL。

        Returns:
            新規なら True、予約済みなら False。
        """
        ...

    def release(self, source_url: str) -> None:
        """予約を解放し、次周期での再試行を可能にする。

        Args:
            source_url: 解放する記事の URL。
        """
        ...


class Summarizer(Protocol):
    """記事の要約とタグを生成する。"""

    def summarize(self, title: str, body: str) -> SummarizeResult:
        """記事のタイトルと本文から要約とタグを得る。

        Args:
            title: 記事のタイトル。
            body: 記事の本文。

        Returns:
            記事の要約とタグ。
        """
        ...


class ArticlePublisher(Protocol):
    """記事イベントを 1 件ずつ送出する。"""

    def publish(self, event: ArticleEvent) -> None:
        """1 件のイベントを送出する。

        Args:
            event: 送出するイベント。
        """
        ...
