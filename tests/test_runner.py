from unittest.mock import MagicMock, patch

import pytest

from newsfeed.model import FetchedItem, SummarizeResult
from newsfeed.runner import PublishError, _fetch_and_publish


def _item(n: int) -> FetchedItem:
    return FetchedItem(
        source="aws",
        source_url=f"https://example.com/{n}",
        title=f"Article {n}",
        body=f"body{n}",
    )


def _summarizer(summary: str = "要約", tags=None) -> MagicMock:
    m = MagicMock()
    m.summarize.return_value = SummarizeResult(summary=summary, tags=tags or [])
    return m


class Test取得から配信までの処理:
    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_要約とpublishの前に予約する(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1)]
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        # 予約 → 要約 → publish の順で呼ばれること
        dedup.reserve.assert_called_once_with("https://example.com/1")
        summarizer.summarize.assert_called_once()
        publisher.publish.assert_called_once()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_既に予約済みの記事はスキップする(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        # 1 件目は seen、2 件目は新規
        dedup.reserve.side_effect = [False, True]
        summarizer = _summarizer()
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        # 既に seen の記事は要約/publish に進まない
        assert summarizer.summarize.call_count == 1
        assert publisher.publish.call_count == 1

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_要約失敗時はマーカーを解放する(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1)]
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = MagicMock()
        summarizer.summarize.side_effect = RuntimeError("vertex down")
        publisher = MagicMock()

        with pytest.raises(PublishError):
            _fetch_and_publish(dedup, summarizer, publisher)

        dedup.release.assert_called_once_with("https://example.com/1")
        publisher.publish.assert_not_called()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_publish失敗時はマーカーを解放する(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1)]
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()
        publisher.publish.side_effect = RuntimeError("pubsub down")

        with pytest.raises(PublishError):
            _fetch_and_publish(dedup, summarizer, publisher)

        dedup.release.assert_called_once_with("https://example.com/1")

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_個別失敗後も残りの記事の処理を継続する(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2), _item(3)]
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()
        publisher.publish.side_effect = [RuntimeError("fail"), None, None]

        with pytest.raises(PublishError, match="1 article"):
            _fetch_and_publish(dedup, summarizer, publisher)

        # 1 件失敗後も残り 2 件の publish が試行される
        assert publisher.publish.call_count == 3

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_全件成功時は各記事をpublishしマーカーを解放しない(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1), _item(2)]
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer()
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        assert publisher.publish.call_count == 2
        dedup.release.assert_not_called()

    @patch("newsfeed.runner.fetch_all")
    @patch("newsfeed.runner.ULID")
    def test_イベントに要約とタグを載せる(self, mock_ulid, mock_fetch_all):
        mock_fetch_all.return_value = [_item(1)]
        mock_ulid.return_value = "01ABC"

        dedup = MagicMock()
        dedup.reserve.return_value = True
        summarizer = _summarizer(summary="要約テキスト", tags=["ai", "compute"])
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        event = publisher.publish.call_args[0][0]
        assert event.article_id == "01ABC"
        assert event.summary == "要約テキスト"
        assert event.tags == ["ai", "compute"]
        assert event.title == "Article 1"
        assert event.body == "body1"

    @patch("newsfeed.runner.fetch_all")
    def test_取得記事が0件のとき要約も配信も行われず正常終了する(self, mock_fetch_all):
        mock_fetch_all.return_value = []

        dedup = MagicMock()
        summarizer = _summarizer()
        publisher = MagicMock()

        _fetch_and_publish(dedup, summarizer, publisher)

        summarizer.summarize.assert_not_called()
        publisher.publish.assert_not_called()
