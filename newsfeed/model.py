from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class FetchedItem:
    """RSS フィードから取得した生の記事データ。"""

    source: str
    source_url: str
    title: str
    content: str
    published_at: Optional[datetime] = None


@dataclass
class NewsArticle:
    """DB に保存する記事エンティティ。"""

    article_id: str
    source: str
    source_url: str
    title: str
    summary: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    raw_gcs_path: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class SummarizeResult:
    """Vertex AI から返却された要約結果。"""

    summary: str
    tags: list[str]
