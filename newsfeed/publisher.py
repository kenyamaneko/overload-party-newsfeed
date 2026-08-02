"""news-article-collected トピックへの Pub/Sub publisher。

トピック名は news リポ (packages/api-news/news.go) の TopicArticleCollected
と一致させる必要があるが、newsfeed は Go パッケージを consume できないため
本ファイル内で契約定数としてハードコードする (ADR-020 §パッケージ境界を継承)。
"""
import json
import logging

from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.publisher.exceptions import MessageTooLargeError

from newsfeed.model import ArticleEvent

logger = logging.getLogger(__name__)

TOPIC_NAME = "news-article-collected"


class PublishError(Exception):
    """イベントの publish に失敗した場合に送出されます。"""


class ArticlePublisher:
    """ArticleEvent を news-article-collected トピックへ publish します。"""

    def __init__(self, project_id: str, client: pubsub_v1.PublisherClient | None = None) -> None:
        self._client = client or pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project_id, TOPIC_NAME)

    def publish(self, event: ArticleEvent) -> None:
        """1 件のイベントを publish し、サーバ側 ACK を待機します。

        Args:
            event: publish するイベント。

        Raises:
            PublishError: publish に失敗したとき。
        """
        data = json.dumps(event.to_dict(), ensure_ascii=False).encode("utf-8")
        try:
            future = self._client.publish(self._topic_path, data)
            future.result()
        except (GoogleAPIError, GoogleAuthError, MessageTooLargeError) as e:
            raise PublishError(f"publisher: failed to publish {event.article_id}: {e}") from e
