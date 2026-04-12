# overload-party-newsfeed

クラウドニュース収集 Cloud Run Job。AWS / Azure / Google Cloud / Oracle Cloud の公式 RSS フィードを定期取得し、Vertex AI で日本語要約して PostgreSQL に保存する。GKE にはデプロイしない。

## サービス間連携

```
Cloud Scheduler (2時間おき)
  │
  ▼
Newsfeed (この Cloud Run Job)
  ├─ RSS (AWS / Azure / GCP / OCI 公式ブログ)
  ├─ GCS (生データ保存: raw/{source}/{date}/{ulid}.json)
  ├─ Vertex AI Gemini 2.0 Flash (日本語要約 + タグ抽出)
  └─ PostgreSQL (newsfeed スキーマ所有: news_articles)
                │
                ▼ (read-only)
          Gateway → GET /api/v1/cloud-news → クライアント
```

- REST エンドポイントなし (バッチジョブ)
- Gateway は `newsfeed.news_articles` を直接 SELECT して配信する

## 環境変数

全て Cloud Run Job の env に設定する。

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `DATABASE_URL` | はい | --- | PostgreSQL 接続文字列 |
| `GCS_BUCKET` | はい | --- | 生データ保存先 GCS バケット名 |
| `GCP_PROJECT` | はい | --- | GCP プロジェクト ID (Vertex AI 用) |
| `VERTEX_LOCATION` | いいえ | `us-central1` | Vertex AI リージョン |

必須変数が未設定なら起動時に即 fail する。

## 公開パッケージ

| パッケージ | パス | 用途 |
|---|---|---|
| Go module | `packages/newsfeed-constants/` | `CloudNewsSource` enum (aws / google-cloud / azure / oci) |
| npm | `packages/newsfeed-constants-npm/` | 同等の TypeScript 型 |

Newsfeed 自体は Python であり Go パッケージは消費しない。Gateway + client が source enum を共有するためのパッケージ。

SSoT: `data/newsfeed_constants.yaml` -> `python3 scripts/generate_types.py` で再生成。
