from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FetchedItem:
    """RSS フィードから取得した生の記事データを保持します。"""

    source: str
    source_url: str
    title: str
    content: str
    published_at: Optional[datetime] = None


@dataclass
class NewsArticle:
    """DB に保存する記事エンティティを表します。"""

    article_id: str
    source: str
    source_url: str
    title: str
    summary: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    raw_gcs_path: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime = field(default=None)

    def __post_init__(self) -> None:
        if self.fetched_at is None:
            raise ValueError("fetched_at is required")


@dataclass(frozen=True)
class SummarizeResult:
    """Vertex AI から返却された要約結果を保持します。"""

    summary: str
    tags: list[str]
