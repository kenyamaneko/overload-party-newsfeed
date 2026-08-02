from dataclasses import dataclass
from datetime import datetime


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
    source_published_at: datetime | None = None


@dataclass(frozen=True)
class MalformedEntry:
    """本文が空のためスキップした RSS エントリ。"""

    source: str
    title: str


@dataclass(frozen=True)
class FetchResult:
    """全 RSS ソースの取得結果。

    取得できた記事の配信を止めずに失敗をジョブの終了コードへ伝えるため、
    記事と併せて失敗を返す。ソース丸ごとの失敗 (failed_sources) と
    ソース内の一部エントリの失敗 (malformed_entries) は別の事象として扱う。
    """

    items: list[FetchedItem]
    failed_sources: list[str]
    malformed_entries: list[MalformedEntry]


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
    source_published_at: datetime | None = None
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
