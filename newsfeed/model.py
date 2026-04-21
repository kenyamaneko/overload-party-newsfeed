from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FetchedItem:
    """RSS フィードから取得した記事データ。

    body は RSS の content:encoded / description から HTML を除去した
    プレーンテキスト。Vertex AI 要約の入力にもなる。
    """

    source: str
    source_url: str
    title: str
    body: str
    source_published_at: Optional[datetime] = None


@dataclass(frozen=True)
class SummarizeResult:
    """Vertex AI の要約出力。"""

    summary: str
    tags: list[str]


@dataclass(frozen=True)
class ArticleEvent:
    """news-article-collected トピックへ publish するイベントペイロード。

    news リポの packages/api-news/ArticleCollectedEvent と形状を一致させる
    (ADR-020 §イベント契約の復帰)。
    """

    article_id: str
    source: str
    source_url: str
    tags: list[str]
    title: str
    summary: str
    body: str
    source_published_at: Optional[datetime] = None
    lang: str = "ja"

    def to_dict(self) -> dict:
        payload: dict = {
            "article_id": self.article_id,
            "source": self.source,
            "source_url": self.source_url,
            "tags": self.tags,
            "translations": [
                {
                    "lang": self.lang,
                    "title": self.title,
                    "summary": self.summary,
                    "body": self.body,
                }
            ],
        }
        if self.source_published_at is not None:
            # Go の time.Time JSON parser は RFC3339 を期待するため Z 表記に寄せる
            payload["source_published_at"] = self.source_published_at.isoformat().replace("+00:00", "Z")
        return payload
