# セットアップ

## 環境変数

| 変数名 | 必須 | 説明 |
|---|---|---|
| `APP_ENV` | はい | `local` / `production` の 2 値のみ。`production` のとき Upstash 接続情報を Secret Manager から取得する (dev/stg/prod の区別は `GOOGLE_CLOUD_PROJECT` で吸収) |
| `GOOGLE_CLOUD_PROJECT` | はい | Pub/Sub / Vertex AI / Secret Manager の対象プロジェクト |
| `VERTEX_LOCATION` | はい | Vertex AI リージョン (例: `us-central1`) |
| `NEWS_ARTICLE_COLLECTED_TOPIC` | はい | 記事イベントの publish 先トピック名。News 側の受信トピックと同じ `news-article-collected` を設定する |
| `UPSTASH_REDIS_URL` | `APP_ENV=local` 時のみ | ローカル Valkey の接続 URL (例: `redis://localhost:6379/0`) |
| `PUBSUB_EMULATOR_HOST` | `APP_ENV=local` 時のみ | ローカル Pub/Sub emulator のホスト (例: `localhost:8085`) |

必須変数が未設定なら起動時に即 fail する。

## Secret Manager（本番）

本番環境では Upstash Redis 接続情報を以下のシークレットから取得する（`APP_ENV=production` のとき）:

| Secret ID | 内容 |
|---|---|
| `newsfeed-upstash-redis-endpoint` | `host:port` 形式の Upstash エンドポイント |
| `newsfeed-upstash-redis-password` | Upstash `default` ユーザーのパスワード |

newsfeed Cloud Run Job のサービスアカウントに `roles/secretmanager.secretAccessor` / `roles/aiplatform.user` / `roles/pubsub.publisher` を付与する。

Upstash DB 名は環境ごとに別インスタンス: `overload-party-{dev,stg,prod}-newsfeed`。

## ローカル開発

`make run` はジョブ本体とインフラ (Valkey / Pub/Sub emulator) を compose 内で起動する。
インフラはホストへ publish せず内部ネットワークのサービス名 DNS で参照するため、他リポの
ローカルスタックやホスト上の他アプリとポートが衝突しない。newsfeed は API ポートを持たない
バッチのため、ホストへ publish するポートは無い。

```bash
make run   # ジョブ + インフラを compose で起動 (バッチを 1 周して終了)
make down  # 停止して volume を削除
make test  # pytest 実行 (Testcontainers が Valkey を起動; Docker 必須)
make lint  # ruff
```

ソース (`main.py` / `newsfeed/`) は bind-mount しているため、編集して再度 `make run` すれば
イメージを作り直さずに反映される (依存を変えたときだけ `--build` が再ビルドする)。
ローカルでは Secret Manager を経由せず compose の env を直読みする。

要約 (Vertex AI) にはエミュレータが無く実 API を呼ぶため、ジョブを最後まで完走させるには
Google Cloud の認証情報が必要になる。認証なしでは要約ステップで失敗して終了する。
