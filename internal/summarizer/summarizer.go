package summarizer

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"cloud.google.com/go/vertexai/genai"
)

const model = "gemini-2.0-flash-001"

// Summarizer calls Vertex AI Gemini to summarize cloud news articles.
type Summarizer struct {
	client   *genai.Client
	location string
}

func New(ctx context.Context, projectID, location string) (*Summarizer, error) {
	client, err := genai.NewClient(ctx, projectID, location)
	if err != nil {
		return nil, fmt.Errorf("summarizer: genai.NewClient: %w", err)
	}
	return &Summarizer{client: client, location: location}, nil
}

func (s *Summarizer) Close() error {
	return s.client.Close()
}

// Result holds the AI-generated summary and extracted tags.
type Result struct {
	Summary string
	Tags    []string
}

// Summarize sends the article title + content to Gemini and returns a Result.
func (s *Summarizer) Summarize(ctx context.Context, title, content string) (Result, error) {
	m := s.client.GenerativeModel(model)
	m.GenerationConfig.ResponseMIMEType = "application/json"

	prompt := buildPrompt(title, content)
	resp, err := m.GenerateContent(ctx, genai.Text(prompt))
	if err != nil {
		return Result{}, fmt.Errorf("summarizer.Summarize: GenerateContent: %w", err)
	}

	raw := extractText(resp)
	return parseResponse(raw)
}

func buildPrompt(title, content string) string {
	// Truncate content to keep within token limits (~4000 chars ≈ ~1000 tokens).
	if len(content) > 4000 {
		content = content[:4000] + "..."
	}

	return fmt.Sprintf(`あなたはクラウド技術の専門家です。以下のクラウドサービスに関する記事を日本語で要約してください。

# 記事タイトル
%s

# 記事内容
%s

# 出力形式（JSON）
{
  "summary": "3〜4文の日本語要約",
  "tags": ["タグ1", "タグ2", "タグ3"]  // compute / network / storage / database / ai / security / serverless / container / devops / pricing から該当するものを選択
}

JSONのみを返してください。`, title, content)
}

func extractText(resp *genai.GenerateContentResponse) string {
	if resp == nil || len(resp.Candidates) == 0 {
		return ""
	}
	var sb strings.Builder
	for _, part := range resp.Candidates[0].Content.Parts {
		if t, ok := part.(genai.Text); ok {
			sb.WriteString(string(t))
		}
	}
	return sb.String()
}

type aiResponse struct {
	Summary string   `json:"summary"`
	Tags    []string `json:"tags"`
}

func parseResponse(raw string) (Result, error) {
	// Strip possible markdown code fences.
	raw = strings.TrimSpace(raw)
	raw = strings.TrimPrefix(raw, "```json")
	raw = strings.TrimPrefix(raw, "```")
	raw = strings.TrimSuffix(raw, "```")
	raw = strings.TrimSpace(raw)

	var r aiResponse
	if err := json.Unmarshal([]byte(raw), &r); err != nil {
		return Result{}, fmt.Errorf("summarizer: parse response: %w (raw: %q)", err, raw)
	}
	if r.Summary == "" {
		return Result{}, fmt.Errorf("summarizer: empty summary in response")
	}
	return Result{Summary: r.Summary, Tags: r.Tags}, nil
}
