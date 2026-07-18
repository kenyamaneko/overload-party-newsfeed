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

    @patch("newsfeed.summarizer.vertexai.init")
    @patch("newsfeed.summarizer.GenerativeModel")
    def test_応答がJSONとして解釈できないときJSONDecodeErrorになる(self, model_cls, init):
        model_cls.return_value = _mock_model("要約: これは JSON ではありません")
        with pytest.raises(json.JSONDecodeError):
            Summarizer("proj", "us-central1").summarize("Title", "body")

    @pytest.mark.parametrize(
        ("response", "match"),
        [
            pytest.param(
                {"tags": []},
                "invalid summary",
                id="summaryキーが欠落しているとき、ValueErrorになる",
            ),
            pytest.param(
                {"summary": 123, "tags": []},
                "invalid summary",
                id="summaryが文字列でない数値123のとき、ValueErrorになる",
            ),
            pytest.param(
                {"summary": "x"},
                "non-list tags",
                id="tagsキーが欠落しているとき、ValueErrorになる",
            ),
        ],
    )
    def test_必須キーの欠落と型不正でValueErrorになる(self, response, match):
        with patch("newsfeed.summarizer.vertexai.init"), \
                patch("newsfeed.summarizer.GenerativeModel") as model_cls:
            model_cls.return_value = _mock_model(json.dumps(response))
            with pytest.raises(ValueError, match=match):
                Summarizer("proj", "us-central1").summarize("Title", "body")

    @patch("newsfeed.summarizer.vertexai.init")
    @patch("newsfeed.summarizer.GenerativeModel")
    def test_タグに数値42が混ざるとき許容タグaiだけが残る(self, model_cls, init):
        model_cls.return_value = _mock_model(
            json.dumps({"summary": "x", "tags": ["ai", 42]}),
        )
        result = Summarizer("proj", "us-central1").summarize("Title", "body")
        assert result.tags == ["ai"]

    @pytest.mark.parametrize(
        "tag",
        [
            pytest.param("compute", id="computeのとき、タグに採用される"),
            pytest.param("network", id="networkのとき、タグに採用される"),
            pytest.param("storage", id="storageのとき、タグに採用される"),
            pytest.param("database", id="databaseのとき、タグに採用される"),
            pytest.param("ai", id="aiのとき、タグに採用される"),
            pytest.param("security", id="securityのとき、タグに採用される"),
            pytest.param("serverless", id="serverlessのとき、タグに採用される"),
            pytest.param("container", id="containerのとき、タグに採用される"),
            pytest.param("devops", id="devopsのとき、タグに採用される"),
            pytest.param("pricing", id="pricingのとき、タグに採用される"),
        ],
    )
    def test_許容タグ語彙が採用される(self, tag):
        with patch("newsfeed.summarizer.vertexai.init"), \
                patch("newsfeed.summarizer.GenerativeModel") as model_cls:
            model_cls.return_value = _mock_model(
                json.dumps({"summary": "x", "tags": [tag]}),
            )
            result = Summarizer("proj", "us-central1").summarize("Title", "body")
        assert result.tags == [tag]


class Test本文の切り詰め:
    @pytest.mark.parametrize(
        "body_length",
        [
            pytest.param(3999, id="本文が3999文字のとき、末尾の文字までプロンプトに含まれる"),
            pytest.param(4000, id="本文が4000文字ちょうどのとき、末尾の文字までプロンプトに含まれる"),
        ],
    )
    def test_上限以下の本文は末尾までプロンプトに含まれる(self, body_length):
        marker = "Ω"
        body = "a" * (body_length - len(marker)) + marker
        with patch("newsfeed.summarizer.vertexai.init"), \
                patch("newsfeed.summarizer.GenerativeModel") as model_cls:
            model = _mock_model(json.dumps({"summary": "x", "tags": []}))
            model_cls.return_value = model
            Summarizer("proj", "us-central1").summarize("Title", body)
        prompt = model.generate_content.call_args[0][0]
        assert marker in prompt

    def test_本文が4001文字のとき4000文字目までが含まれ4001文字目は含まれない(self):
        included_marker = "Ω"
        excluded_marker = "Ψ"
        body = "a" * 3999 + included_marker + excluded_marker
        with patch("newsfeed.summarizer.vertexai.init"), \
                patch("newsfeed.summarizer.GenerativeModel") as model_cls:
            model = _mock_model(json.dumps({"summary": "x", "tags": []}))
            model_cls.return_value = model
            Summarizer("proj", "us-central1").summarize("Title", body)
        prompt = model.generate_content.call_args[0][0]
        assert included_marker in prompt
        assert excluded_marker not in prompt
