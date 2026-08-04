"""Vertex AI Gemini による日本語要約とタグ生成 (ADR-020)。

タグ語彙は ADR-020 で固定された 10 種からモデルに選ばせ、許容外のタグは
呼び出し側で捨てる。許容タグが 0 個のケース (該当なし) も空配列として
正常扱いする。
"""
import json

import vertexai
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from vertexai.generative_models import GenerationConfig, GenerativeModel

from newsfeed.model import SummarizeResult


class SummarizeError(Exception):
    """要約の取得に失敗した場合に送出されます。"""


_MODEL = "gemini-2.5-flash"
_MAX_BODY_CHARS = 4000  # プロンプト爆発抑止

_ALLOWED_TAGS = (
    "compute",
    "network",
    "storage",
    "database",
    "ai",
    "security",
    "serverless",
    "container",
    "devops",
    "pricing",
)


class Summarizer:
    """Vertex AI Gemini による要約・タグ生成。"""

    def __init__(self, project_id: str, location: str) -> None:
        vertexai.init(project=project_id, location=location)
        self._model = GenerativeModel(_MODEL)

    def summarize(self, title: str, body: str) -> SummarizeResult:
        """記事のタイトルと本文から日本語の要約とタグを得ます。

        Args:
            title: 記事のタイトル。
            body: 記事の本文。

        Returns:
            日本語の要約と、許容語彙に絞ったタグ。

        Raises:
            SummarizeError: 要約を取得できなかったとき。
        """
        prompt = _build_prompt(title, body)
        try:
            response = self._model.generate_content(
                prompt,
                generation_config=GenerationConfig(response_mime_type="application/json"),
            )
            # 候補が返らなかったときは応答の読み出しで失敗するため、読み出しも変換の対象に含める
            raw = response.text
        except (GoogleAPIError, GoogleAuthError, ValueError) as e:
            raise SummarizeError(f"summarizer: failed to generate content: {e}") from e
        return _parse_response(raw)


def _build_prompt(title: str, body: str) -> str:
    truncated = body[:_MAX_BODY_CHARS]
    allowed = ", ".join(_ALLOWED_TAGS)
    return (
        "以下のクラウドニュース記事を日本語で要約し、タグ付けしてください。\n\n"
        f"タイトル: {title}\n\n"
        f"本文:\n{truncated}\n\n"
        "以下の JSON 形式で出力してください:\n"
        '{\n'
        '  "summary": "日本語で 300 文字以内の要約",\n'
        '  "tags": ["許容タグから 0〜3 個選択 (該当なしなら空配列)"]\n'
        "}\n\n"
        f"許容タグ: {allowed}"
    )


def _parse_response(raw: str) -> SummarizeResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SummarizeError(f"summarizer returned non-JSON response: {raw!r}") from e
    summary = data.get("summary")
    raw_tags = data.get("tags")

    if not isinstance(summary, str) or not summary:
        raise SummarizeError(f"summarizer returned invalid summary: {raw!r}")
    if not isinstance(raw_tags, list):
        raise SummarizeError(f"summarizer returned non-list tags: {raw!r}")

    tags = [t for t in raw_tags if isinstance(t, str) and t in _ALLOWED_TAGS]
    return SummarizeResult(summary=summary, tags=tags)
