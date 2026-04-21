from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FetchedItem:
    """RSS フィードから取得した記事データを保持します。

    body は RSS の content:encoded / description から HTML を除去した
    プレーンテキスト。Pub/Sub ペイロードにそのまま載せます。
    """

    source: str
    source_url: str
    title: str
    body: str
    source_published_at: Optional[datetime] = None


@dataclass(frozen=True)
class ArticleEvent:
    """news-article-collected トピックへ publish するイベントペイロード。

    news リポの packages/api-news/ArticleCollectedEvent と形状を一致させます
    (ADR-019)。
    """

    article_id: str
    source: str
    source_url: str
    title: str
    body: str
    source_published_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        payload: dict = {
            "article_id": self.article_id,
            "source": self.source,
            "source_url": self.source_url,
            "title": self.title,
            "body": self.body,
        }
        if self.source_published_at is not None:
            # Go の time.Time JSON parser は RFC3339 を期待するため Z 表記に寄せる
            payload["source_published_at"] = self.source_published_at.isoformat().replace("+00:00", "Z")
        return payload
