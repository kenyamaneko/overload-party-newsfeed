"""記事イベントの Pub/Sub publisher。"""
import json

from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.publisher.exceptions import MessageTooLargeError

from newsfeed.model import ArticleEvent


class PublishError(Exception):
    """イベントの publish に失敗した場合に送出されます。"""


class ArticlePublisher:
    """ArticleEvent を指定されたトピックへ publish します。"""

    def __init__(
        self,
        project_id: str,
        topic: str,
        client: pubsub_v1.PublisherClient | None = None,
    ) -> None:
        """publish 先を決めて publisher を用意します。

        Args:
            project_id: publish 先トピックを持つプロジェクト。
            topic: publish 先トピックの名前。
            client: publish に使うクライアント。省略時は既定の資格情報で作成する。
        """
        self._client = client or pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project_id, topic)

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
