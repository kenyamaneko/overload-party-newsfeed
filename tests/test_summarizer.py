import json
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import GoogleAPIError

from newsfeed.summarizer import SummarizeError, Summarizer


def _summarizer_with_response(text: str | None = None, side_effect: Exception | None = None) -> Summarizer:
    """モデル呼び出しを代用に差し替えた Summarizer を組み立てる。

    Args:
        text: generate_content が返す応答テキスト。side_effect 指定時は無視される。
        side_effect: generate_content 呼び出し自体を失敗させる例外。

    Returns:
        vertexai.init / GenerativeModel を差し替え済みの Summarizer。
    """
    mock_model = MagicMock()
    if side_effect is not None:
        mock_model.generate_content.side_effect = side_effect
    else:
        mock_model.generate_content.return_value = MagicMock(text=text)
    with patch("newsfeed.summarizer.vertexai.init"), \
            patch("newsfeed.summarizer.GenerativeModel", return_value=mock_model):
        return Summarizer("test-project", "us-central1")


class Test要約とタグの生成:
    def test_モデルが要約とタグを含むJSONを返したとき要約文字列とタグがそのまま結果になる(self):
        summarizer = _summarizer_with_response(
            text=json.dumps({"summary": "クラウドの新機能について", "tags": ["compute", "network"]}),
        )

        result = summarizer.summarize("title", "body")

        assert result.summary == "クラウドの新機能について"
        assert result.tags == ["compute", "network"]

    def test_モデルが返したタグに許容タグ以外が含まれるときそのタグは結果から除外される(self):
        summarizer = _summarizer_with_response(
            text=json.dumps({"summary": "要約", "tags": ["compute", "not-an-allowed-tag"]}),
        )

        result = summarizer.summarize("title", "body")

        assert result.tags == ["compute"]

    def test_モデルが返したタグの配列が空のとき結果のタグも空になる(self):
        summarizer = _summarizer_with_response(text=json.dumps({"summary": "要約", "tags": []}))

        result = summarizer.summarize("title", "body")

        assert result.tags == []


class Test要約の失敗:
    def test_モデルの応答がJSONとして解釈できない文字列のときJSON解釈失敗を理由とする例外になる(self):
        summarizer = _summarizer_with_response(text="this is not json")

        with pytest.raises(SummarizeError, match="JSON"):
            summarizer.summarize("title", "body")

    @pytest.mark.parametrize(
        "response_body",
        [
            pytest.param({"tags": ["compute"]}, id="要約文字列のキーが無いとき"),
            pytest.param({"summary": "", "tags": ["compute"]}, id="要約文字列が空文字列のとき"),
        ],
    )
    def test_モデルの応答に要約文字列が無いとき要約が無いことを理由とする例外になる(self, response_body):
        summarizer = _summarizer_with_response(text=json.dumps(response_body))

        with pytest.raises(SummarizeError, match="summary"):
            summarizer.summarize("title", "body")

    @pytest.mark.parametrize(
        "tags_value",
        [
            pytest.param("compute", id="タグが文字列のとき"),
            pytest.param({"tag": "compute"}, id="タグがオブジェクトのとき"),
        ],
    )
    def test_モデルの応答のタグが配列形式でないときタグの形式が不正であることを理由とする例外になる(self, tags_value):
        summarizer = _summarizer_with_response(text=json.dumps({"summary": "要約", "tags": tags_value}))

        with pytest.raises(SummarizeError, match="tags"):
            summarizer.summarize("title", "body")

    def test_モデルの呼び出し自体が失敗したときモデルの呼び出し失敗を理由とする例外になり元の例外を保持する(self):
        api_error = GoogleAPIError("quota exceeded")
        summarizer = _summarizer_with_response(side_effect=api_error)

        with pytest.raises(SummarizeError) as excinfo:
            summarizer.summarize("title", "body")

        assert excinfo.value.__cause__ is api_error
