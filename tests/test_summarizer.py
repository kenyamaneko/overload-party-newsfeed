import json
from unittest.mock import MagicMock, patch

import pytest

from newsfeed.model import SummarizeResult
from newsfeed.summarizer import Summarizer


def _mock_model(response_text: str) -> MagicMock:
    response = MagicMock()
    response.text = response_text
    model = MagicMock()
    model.generate_content.return_value = response
    return model


class Test記事の要約:
    @patch("newsfeed.summarizer.vertexai.init")
    @patch("newsfeed.summarizer.GenerativeModel")
    def test_要約と正当なタグを返す(self, model_cls, init):
        model_cls.return_value = _mock_model(
            json.dumps({"summary": "要約", "tags": ["ai", "compute"]}),
        )
        result = Summarizer("proj", "us-central1").summarize("Title", "body")
        assert isinstance(result, SummarizeResult)
        assert result.summary == "要約"
        assert result.tags == ["ai", "compute"]

    @patch("newsfeed.summarizer.vertexai.init")
    @patch("newsfeed.summarizer.GenerativeModel")
    def test_許可語彙外のタグを除外する(self, model_cls, init):
        model_cls.return_value = _mock_model(
            json.dumps({"summary": "x", "tags": ["ai", "unknown-tag"]}),
        )
        result = Summarizer("proj", "us-central1").summarize("Title", "body")
        assert result.tags == ["ai"]

    @patch("newsfeed.summarizer.vertexai.init")
    @patch("newsfeed.summarizer.GenerativeModel")
    def test_空のタグリストは正当とする(self, model_cls, init):
        model_cls.return_value = _mock_model(
            json.dumps({"summary": "x", "tags": []}),
        )
        result = Summarizer("proj", "us-central1").summarize("Title", "body")
        assert result.tags == []

    @patch("newsfeed.summarizer.vertexai.init")
    @patch("newsfeed.summarizer.GenerativeModel")
    def test_空の要約はValueErrorになる(self, model_cls, init):
        model_cls.return_value = _mock_model(
            json.dumps({"summary": "", "tags": []}),
        )
        with pytest.raises(ValueError, match="invalid summary"):
            Summarizer("proj", "us-central1").summarize("Title", "body")

    @patch("newsfeed.summarizer.vertexai.init")
    @patch("newsfeed.summarizer.GenerativeModel")
    def test_リストでないtagsはValueErrorになる(self, model_cls, init):
        model_cls.return_value = _mock_model(
            json.dumps({"summary": "x", "tags": "not-a-list"}),
        )
        with pytest.raises(ValueError, match="non-list tags"):
            Summarizer("proj", "us-central1").summarize("Title", "body")
