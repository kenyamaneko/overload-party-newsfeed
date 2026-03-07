# overload-party-newsfeed 仕様メモ

Python書き直し前の現行 Go 実装の仕様を記録する。

---

## 概要

Cloud Run Job として動作するバッチプログラム。
Cloud Scheduler から2時間おきに起動され、クラウド各社の公式 RSS フィードを取得・要約して PostgreSQL に保存する。

---

## 処理フロー

```
起動
 │
 ├─ Step 1: RSS 取得
 │    └─ 4ソース分を順番にフェッチ（並列ではない）
 │
 ├─ Step 2: 新規記事の処理（1件ずつループ）
 │    ├─ 重複チェック (source_url で EXISTS クエリ)
 │    ├─ 重複あり → スキップ
 │    └─ 重複なし →
 │         ├─ ULID で article_id を採番
 │         ├─ GCS に生データ保存 → raw_gcs_path を取得
 │         ├─ DB にスタブ挿入（summary=NULL）
 │         └─ Vertex AI で要約 → DB の summary/tags を UPDATE
 │              ※ 要約失敗はエラーログを出して continue（記事スタブは残る）
 │
 └─ Step 3: 前回失敗分のリトライ
      ├─ summary IS NULL な記事を最大50件取得（fetched_at ASC）
      ├─ GCS から content を読み直す（失敗しても空文字で続行）
      └─ Vertex AI で要約 → DB を UPDATE
```

---

## RSSフィードソース

| キー名 | URL |
|--------|-----|
| `aws`  | `https://aws.amazon.com/blogs/aws/feed/` |
| `azure`| `https://azure.microsoft.com/en-us/blog/feed/` |
| `gcp`  | `https://cloud.google.com/blog/feed` |
| `oci`  | `https://blogs.oracle.com/cloud-infrastructure/rss` |

---

## データモデル

### FetchedItem（RSS 取得後の中間データ）

| フィールド | 型 | 説明 |
|-----------|----|----|
| source | string | "aws" / "azure" / "gcp" / "oci" |
| source_url | string | `item.link` を優先、なければ `item.guid` |
| title | string | |
| content | string | `item.content` → `item.description` → "Title: ...\n\nPublished: ..." の順でフォールバック |
| published_at | *time | nullable |

source_url または title が空の場合はその記事をスキップ。

### NewsArticle（DB モデル）

| フィールド | 型 | DB カラム | 説明 |
|-----------|----|-----------|----|
| article_id | string | `article_id` VARCHAR(26) PK | ULID |
| source | string | `source` VARCHAR(20) | |
| source_url | string | `source_url` TEXT UNIQUE | |
| title | string | `title` TEXT | |
| summary | *string | `summary` TEXT | NULL = 要約未完了 |
| tags | []string | `tags` TEXT[] | |
| raw_gcs_path | *string | `raw_gcs_path` TEXT | `gs://bucket/...` 形式 |
| published_at | *time | `published_at` TIMESTAMPTZ | |
| fetched_at | time | `fetched_at` TIMESTAMPTZ | |

---

## GCS 保存仕様

### パス形式
```
raw/{source}/{YYYY-MM-DD}/{article_id}.json
```
日付は UTC の実行時刻から生成。

### JSON 構造（rawPayload）
```json
{
  "article_id": "...",
  "source": "aws",
  "source_url": "https://...",
  "title": "...",
  "content": "...",
  "published_at": "2025-01-01T00:00:00Z",  // omitempty
  "fetched_at": "2025-01-01T00:00:00Z"
}
```
Content-Type: `application/json`

### リトライ時の読み込み
- `gs://{bucket}/` プレフィックスを除去して object path を取得
- JSON をパースして `content` フィールドのみ返す
- 読み込み失敗時は空文字で続行（スキップしない）

---

## DB 操作

| 操作 | SQL | 備考 |
|------|-----|------|
| 重複チェック | `SELECT EXISTS(SELECT 1 FROM news_articles WHERE source_url = $1)` | |
| スタブ挿入 | `INSERT ... ON CONFLICT (source_url) DO NOTHING` | |
| 要約更新 | `UPDATE news_articles SET summary=$2, tags=$3 WHERE article_id=$1` | RowsAffected=0 はエラー |
| 未要約一覧 | `SELECT ... WHERE summary IS NULL ORDER BY fetched_at ASC LIMIT $1` | limit=50 固定 |

---

## Vertex AI 呼び出し仕様

- モデル: `gemini-2.0-flash-001`
- ResponseMIMEType: `application/json`
- content が 4000 文字超の場合は 4000 文字に切り詰めて `...` を付加

### プロンプト（日本語）
```
あなたはクラウド技術の専門家です。以下のクラウドサービスに関する記事を日本語で要約してください。

# 記事タイトル
{title}

# 記事内容
{content}

# 出力形式（JSON）
{
  "summary": "3〜4文の日本語要約",
  "tags": ["タグ1", "タグ2", "タグ3"]  // compute / network / storage / database / ai / security / serverless / container / devops / pricing から該当するものを選択
}

JSONのみを返してください。
```

### レスポンスパース
- markdown コードフェンス (` ```json ` / ` ``` `) を除去してからパース
- `summary` が空文字の場合はエラー

---

## 環境変数

| 変数名 | 必須 | デフォルト | 説明 |
|--------|------|-----------|------|
| `DATABASE_URL` | ✅ | - | PostgreSQL 接続文字列 |
| `GCS_BUCKET` | ✅ | - | 生データ保存先バケット名 |
| `GCP_PROJECT` | ✅ | - | GCP プロジェクト ID |
| `VERTEX_LOCATION` | | `us-central1` | Vertex AI リージョン |

---

## エラーハンドリング方針

- **個別フィードの取得失敗** → ログ出力してそのフィードをスキップ、他は続行
- **重複チェック失敗** → ログ出力して該当記事をスキップ
- **GCS 保存失敗** → ログ出力して該当記事をスキップ
- **DB 挿入失敗** → ログ出力して該当記事をスキップ
- **Vertex AI 要約失敗** → ログ出力して continue（DB のスタブは残り次回リトライ対象になる）
- **要約更新失敗** → ログ出力して continue
- ジョブ全体は `run()` がエラーを返した場合のみ `log.Fatalf` で終了（現状 `run()` は常に `nil` を返す）

---

## Dockerfile

- マルチステージビルド
- ビルドステージ: `golang:1.25-alpine`
- 実行ステージ: `gcr.io/distroless/static-debian12`（シェルなし・最小イメージ）
- バイナリ: `/newsfeed`

---

## ディレクトリ構成（現行 Go）

```
cmd/main.go                          # エントリポイント・ジョブオーケストレーション
internal/
  fetcher/fetcher.go                 # RSS 取得・FetchedItem 変換
  model/article.go                   # NewsArticle 型定義
  repository/pg_news_repo.go         # PostgreSQL CRUD
  storage/gcs.go                     # GCS 保存・読み込み
  summarizer/summarizer.go           # Vertex AI Gemini 呼び出し
Dockerfile
go.mod / go.sum
```
