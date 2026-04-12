# Newsfeed サービス設計

このドキュメントは newsfeed サービスの内部動作を説明する。サービスの概要・環境変数は [README.md](../README.md) を参照。

## パイプライン

Cloud Scheduler が 2 時間おきに Cloud Run Job をトリガーし、以下のパイプラインを 1 回実行する:

```
1. RSS フィード取得 (fetch_all)
   ├─ AWS   https://aws.amazon.com/blogs/aws/feed/
   ├─ Azure https://azure.microsoft.com/en-us/blog/feed/
   ├─ GCP   https://cloud.google.com/blog/feed
   └─ OCI   https://blogs.oracle.com/cloud-infrastructure/rss
           │
           ▼ list[FetchedItem]
2. 記事ごとのループ (per article, 独立)
   ├─ 2a. GCS upload (raw/{source}/{date}/{ulid}.json)
   ├─ 2b. Vertex AI Gemini 2.0 Flash で日本語要約 + タグ抽出
   └─ 2c. DB INSERT (newsfeed.news_articles)
           │
           ▼
3. 集計ログ (inserted / duplicates / errors)
```

### 各記事の処理はアトミック

1 記事の処理 (GCS upload -> 要約 -> DB INSERT) のいずれかのステップが失敗した場合、その記事の DB 行は作成されない。`summary IS NULL` の部分行は存在しない。失敗した記事は次回実行時に `source_url` の UNIQUE 制約 + `ON CONFLICT DO NOTHING` により冪等に再取得される。

### Vertex AI 要約

- モデル: `gemini-2.0-flash-001`
- 入力: 記事タイトル + 本文 (4000 文字で切り詰め)
- 出力: JSON `{"summary": "...", "tags": [...]}`
- タグは `compute / network / storage / database / ai / security / serverless / container / devops / pricing` から選択
- `response_mime_type="application/json"` で JSON 出力を強制

## 冪等性

`INSERT ... ON CONFLICT (source_url) DO NOTHING RETURNING article_id` を使用する。

- `RETURNING` が行を返す: 新規挿入 -> inserted カウント
- `RETURNING` が空: `source_url` が既存 -> duplicate カウント (no-op)

この設計により:

- 同一記事の再取得は安全 (冪等)
- check-then-act の TOCTOU 問題が発生しない (単一 SQL 文)
- 並行ジョブ実行でも整合性が保たれる

## 全ソース失敗時の FetchError

`fetch_all` は各 RSS ソースを順に取得し、個別ソースの失敗はログに記録して次のソースに進む。

全ソースが失敗した場合 (success_count == 0 かつ failure_count > 0):

1. `FetchError` 例外を raise
2. `main.py` が例外を catch し `sys.exit(1)` で終了
3. Cloud Run Job がジョブ失敗として記録

一部のソースだけ失敗した場合は正常終了する。成功したソースの記事のみ処理し、失敗ソースの記事は次回実行で取得される。

## エラーハンドリング

| 障害 | 挙動 |
|---|---|
| 必須環境変数の未設定 | `load_config()` が `ValueError` を raise -> exit 1 |
| 全 RSS ソース失敗 | `FetchError` -> exit 1 (Cloud Run Job 失敗) |
| 個別 RSS ソース失敗 | ログ出力、残りのソースで続行 |
| GCS upload 失敗 (個別記事) | ログ出力、その記事をスキップ、errors カウント |
| Vertex AI 要約失敗 (個別記事) | ログ出力、その記事をスキップ、errors カウント |
| DB INSERT 失敗 (個別記事) | ログ出力、その記事をスキップ、errors カウント |
| DB 接続失敗 | `psycopg2.connect` が例外 -> exit 1 |
