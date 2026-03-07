import json
import logging
from datetime import datetime, timezone

from google.cloud import storage as gcs_lib

from newsfeed.model import FetchedItem

logger = logging.getLogger(__name__)


class GCSStorage:
    def __init__(self, bucket: str):
        self._client = gcs_lib.Client()
        self._bucket = bucket

    def save(self, article_id: str, item: FetchedItem) -> str:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        obj_path = f"raw/{item.source}/{date}/{article_id}.json"

        payload: dict = {
            "article_id": article_id,
            "source": item.source,
            "source_url": item.source_url,
            "title": item.title,
            "content": item.content,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        if item.published_at is not None:
            payload["published_at"] = item.published_at.isoformat()

        data = json.dumps(payload, ensure_ascii=False)
        blob = self._client.bucket(self._bucket).blob(obj_path)
        blob.upload_from_string(data, content_type="application/json")

        return f"gs://{self._bucket}/{obj_path}"

    def load_content(self, gcs_path: str) -> str:
        prefix = f"gs://{self._bucket}/"
        if not gcs_path.startswith(prefix):
            raise ValueError(
                f"gcs: path {gcs_path!r} does not belong to bucket {self._bucket!r}"
            )
        obj_path = gcs_path[len(prefix):]

        blob = self._client.bucket(self._bucket).blob(obj_path)
        payload = json.loads(blob.download_as_text())
        return payload.get("content", "")
