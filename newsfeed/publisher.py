"""news-article-collected トピックへの Pub/Sub publisher。

トピック名は news リポ (packages/api-news/news.go) の TopicArticleCollected
と一致させる必要があるが、newsfeed は Go パッケージを consume できないため
本ファイル内で契約定数としてハードコードする (ADR-020 §パッケージ境界を継承)。
"""
import json
import logging

from google.cloud import pubsub_v1

from newsfeed.model import ArticleEvent

logger = logging.getLogger(__name__)

TOPIC_NAME = "news-article-collected"


class ArticlePublisher:
    """ArticleEvent を news-article-collected トピックへ publish します。"""

    def __init__(self, project_id: str, client: pubsub_v1.PublisherClient | None = None) -> None:
        self._client = client or pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project_id, TOPIC_NAME)

    def publish(self, event: ArticleEvent) -> None:
        """1 件のイベントを publish し、サーバ側 ACK を待機します。

        publish 失敗 (ネットワーク / IAM / 存在しないトピック等) は例外として
        呼び出し元に伝播します。呼び出し元で記事単位の失敗として扱ってください。
        """
        data = json.dumps(event.to_dict(), ensure_ascii=False).encode("utf-8")
        future = self._client.publish(self._topic_path, data)
        # future.result() でサーバ側 ACK を待機。publish 失敗時は例外を送出する。
        future.result()
