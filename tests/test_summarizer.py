import json
from unittest.mock import MagicMock, patch

import pytest

from newsfeed.summarizer import Summarizer, _parse_response


class TestParseResponse:
    def test_clean_json(self):
        raw = '{"summary": "This is a summary.", "tags": ["ai", "compute"]}'
        result = _parse_response(raw)
        assert result.summary == "This is a summary."
        assert result.tags == ["ai", "compute"]

    def test_markdown_code_fence(self):
        raw = '```json\n{"summary": "Fenced summary.", "tags": ["storage"]}\n```'
        result = _parse_response(raw)
        assert result.summary == "Fenced summary."
        assert result.tags == ["storage"]

    def test_raises_on_empty_summary(self):
        raw = '{"summary": "", "tags": []}'
        with pytest.raises(ValueError, match="empty summary"):
            _parse_response(raw)

    def test_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("not json at all")


class TestSummarize:
    @patch("newsfeed.summarizer.GenerativeModel")
    @patch("newsfeed.summarizer.vertexai.init")
    def test_raises_on_empty_response_text(self, mock_init, mock_model_cls):
        mock_model = MagicMock()
        mock_model.generate_content.return_value.text = ""
        mock_model_cls.return_value = mock_model

        summarizer = Summarizer(project="test-project", location="us-central1")
        with pytest.raises(ValueError, match="empty response"):
            summarizer.summarize("title", "content")

    @patch("newsfeed.summarizer.GenerativeModel")
    @patch("newsfeed.summarizer.vertexai.init")
    def test_raises_on_none_response_text(self, mock_init, mock_model_cls):
        mock_model = MagicMock()
        mock_model.generate_content.return_value.text = None
        mock_model_cls.return_value = mock_model

        summarizer = Summarizer(project="test-project", location="us-central1")
        with pytest.raises(ValueError, match="empty response"):
            summarizer.summarize("title", "content")
