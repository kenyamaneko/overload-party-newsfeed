import json
import logging

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from newsfeed.model import SummarizeResult

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.0-flash-001"
_MAX_CONTENT_CHARS = 4000


class Summarizer:
    def __init__(self, project: str, location: str):
        vertexai.init(project=project, location=location)
        self._model = GenerativeModel(_MODEL)

    def summarize(self, title: str, content: str) -> SummarizeResult:
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS] + "..."

        prompt = _build_prompt(title, content)
        response = self._model.generate_content(
            prompt,
            generation_config=GenerationConfig(response_mime_type="application/json"),
        )
        return _parse_response(response.text)


def _build_prompt(title: str, content: str) -> str:
    return f"""あなたはクラウド技術の専門家です。以下のクラウドサービスに関する記事を日本語で要約してください。

# 記事タイトル
{title}

# 記事内容
{content}

# 出力形式（JSON）
{{
  "summary": "3〜4文の日本語要約",
  "tags": ["タグ1", "タグ2", "タグ3"]  // compute / network / storage / database / ai / security / serverless / container / devops / pricing から該当するものを選択
}}

JSONのみを返してください。"""


def _parse_response(raw: str) -> SummarizeResult:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(raw)
    if not data.get("summary"):
        raise ValueError("summarizer: empty summary in response")
    return SummarizeResult(summary=data["summary"], tags=data.get("tags", []))
