# overload-party-newsfeed

クラウドニュース収集 Cloud Run Job。AWS / Azure / Google Cloud / Oracle Cloud の公式 RSS を定期取得し、Upstash Redis で同一 URL の再処理を抑止したうえで、Vertex AI Gemini で日本語要約・タグ付けして `news-article-collected` Pub/Sub トピックへ publish する。

詳細は [サービス設計書](docs/ARCHITECTURE.md) を参照。

## サービス間連携

```
Cloud Scheduler (2 時間おき)
  └─ Newsfeed (Cloud Run Job)
       ├─ RSS (AWS / Azure / Google Cloud / OCI)
       ├─ Upstash Redis (source_url dedup, TTL 30d)
       ├─ Vertex AI Gemini 2.5 Flash (日本語要約 + タグ付け)
       └─ Pub/Sub publish
            └─ news-article-collected → News (overload-party-news)
```

- REST エンドポイントなし（バッチジョブ）
- 記事の永続化・校閲・配信は News サービスの責務 (ADR-020)

## 環境変数

| 変数名 | 必須 | 説明 |
|---|---|---|
| `APP_ENV` | はい | `local` / `production` の 2 値のみ。`production` のとき Upstash 接続情報を Secret Manager から取得する (dev/stg/prod の区別は `GOOGLE_CLOUD_PROJECT` で吸収) |
| `GOOGLE_CLOUD_PROJECT` | はい | Pub/Sub / Vertex AI / Secret Manager の対象プロジェクト |
| `VERTEX_LOCATION` | はい | Vertex AI リージョン (例: `us-central1`) |
| `UPSTASH_REDIS_URL` | `APP_ENV=local` 時のみ | ローカル Valkey の接続 URL (例: `redis://localhost:6379/0`) |
| `PUBSUB_EMULATOR_HOST` | `APP_ENV=local` 時のみ | ローカル Pub/Sub emulator のホスト (例: `localhost:8085`) |

必須変数が未設定なら起動時に即 fail する。トピック名は `news-article-collected` に固定（契約定数として実装側でハードコード）。

## Secret Manager（本番）

本番環境では Upstash Redis 接続情報を以下のシークレットから取得する（`APP_ENV=production` のとき）:

| Secret ID | 内容 |
|---|---|
| `newsfeed-upstash-redis-endpoint` | `host:port` 形式の Upstash エンドポイント |
| `newsfeed-upstash-redis-password` | Upstash `default` ユーザーのパスワード |

newsfeed Cloud Run Job のサービスアカウントに `roles/secretmanager.secretAccessor` / `roles/aiplatform.user` / `roles/pubsub.publisher` を付与する (ADR-020)。

Upstash DB 名は環境ごとに別インスタンス: `overload-party-{dev,stg,prod}-newsfeed`。

## ローカル開発

```bash
make up         # Valkey + Pub/Sub emulator を起動
make test       # pytest 実行
make run-local  # .env.local を読み込んでジョブを実行
make down       # 停止と volume 削除
```

`.env.local` は `.env.local.example` をコピーして作る。ローカルでは Secret Manager を経由しないため env 直読み。
