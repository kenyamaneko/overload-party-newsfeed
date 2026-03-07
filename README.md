# overload-party-newsfeed

AWS / Azure / Google Cloud / Oracle Cloud の公式 RSS フィードを定期取得し、Vertex AI Gemini で日本語要約して PostgreSQL に保存する Cloud Run Job。

## 処理フロー

```
Cloud Scheduler (2時間おき)
  ↓
Cloud Run Job
  ├─ 1. RSS 取得 (AWS / Azure / GCP / OCI)
  ├─ 2. DB 重複チェック (source_url)
  ├─ 3. GCS に生データ保存 (raw/{source}/{date}/{ulid}.json)
  ├─ 4. Vertex AI Gemini 2.0 Flash で日本語要約・タグ抽出
  ├─ 5. DB に要約を書き込み (news_articles)
  └─ 6. 前回失敗分のリトライ (summary IS NULL な記事)
```

## ディレクトリ構成

```
cmd/
  main.go                  # エントリポイント・ジョブオーケストレーション
internal/
  fetcher/fetcher.go       # RSS 取得 (gofeed)
  storage/gcs.go           # GCS 生データ保存・読み取り
  repository/pg_news_repo.go  # PostgreSQL CRUD
  summarizer/summarizer.go    # Vertex AI Gemini 呼び出し
  model/article.go         # NewsArticle 型定義
Dockerfile                 # マルチステージビルド (distroless)
```

## 環境変数

| 変数 | 必須 | 説明 |
|------|------|------|
| `DATABASE_URL` | ✅ | PostgreSQL 接続文字列 |
| `GCS_BUCKET` | ✅ | 生データ保存先バケット名 |
| `GCP_PROJECT` | ✅ | GCP プロジェクト ID |
| `VERTEX_LOCATION` | | Vertex AI リージョン（デフォルト: `us-central1`）|

## ローカル実行

```bash
export DATABASE_URL="postgres://..."
export GCS_BUCKET="overload-party-dev-newsfeed"
export GCP_PROJECT="overload-party-dev"

go run ./cmd/main.go
```

## デプロイ

Cloud Run Job と Cloud Scheduler は `overload-party-infra` の `modules/newsfeed` で管理。

```bash
# コンテナイメージのビルド・プッシュ
docker build -t asia-northeast1-docker.pkg.dev/overload-party-shared/overload-party/newsfeed:latest .
docker push asia-northeast1-docker.pkg.dev/overload-party-shared/overload-party/newsfeed:latest

# インフラ適用
cd ../overload-party-infra/environments/dev
terraform apply
```

## DB スキーマ

`news_articles` テーブルは `overload-party-common/db/schema_postgres.sql` で管理。

```sql
CREATE TABLE news_articles (
  article_id   VARCHAR(26) PRIMARY KEY,  -- ULID
  source       VARCHAR(20) NOT NULL,     -- 'aws' | 'azure' | 'gcp' | 'oci'
  source_url   TEXT NOT NULL,
  title        TEXT NOT NULL,
  summary      TEXT,                     -- NULL = 要約未完了（次回リトライ対象）
  tags         TEXT[] NOT NULL DEFAULT '{}',
  raw_gcs_path TEXT,
  published_at TIMESTAMPTZ,
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 関連リポジトリ

| リポジトリ | 役割 |
|-----------|------|
| [overload-party-gateway](https://github.com/kenyamaneko/overload-party-gateway) | `GET /api/v1/cloud-news` で要約済み記事を配信 |
| [overload-party-common](https://github.com/kenyamaneko/overload-party-common) | DB スキーマ管理 |
| [overload-party-infra](https://github.com/kenyamaneko/overload-party-infra) | Cloud Run Job / GCS / Scheduler の Terraform |
