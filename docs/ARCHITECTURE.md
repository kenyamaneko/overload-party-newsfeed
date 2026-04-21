# Newsfeed サービス設計

本ドキュメントは **コードを読んでも一見しては分からない設計意図** だけを残す。フロー順序・環境変数一覧・RSS URL 等は [README.md](../README.md) と実装を一次情報とする。

## Newsfeed の責務境界

newsfeed は次の 4 点を担う Cloud Run Job (ADR-020):

1. RSS 取得
2. **Upstash Redis による source_url ベース dedup** (事前予約、TTL 30d)
3. **Vertex AI Gemini による日本語要約 + タグ付け** (予約成功分のみ)
4. `news-article-collected` への publish

newsfeed は以下を**持たない**:

- DB 書き込み (news が所有)
- 生 JSON アーカイブ (不要と判断)
- 校閲 / 配信 / 翻訳管理 (news が所有)

dedup + 要約を newsfeed 側に寄せた経緯は ADR-020 を参照。

## 冪等性の二段構え

同一 source_url の再処理を防ぐため 2 層で防御する:

1. **一次防御**: newsfeed の Redis `SET NX EX` (事前予約、TTL 30d)。Vertex AI 呼び出し自体を重複させない
2. **二次防御**: news の `INSERT ... ON CONFLICT DO NOTHING` (source_url UNIQUE)。Redis 層をすり抜けた場合の保険

Redis 層が 2h 周期の規模で十分機能するため、通常時は Vertex AI の重複課金が発生しない。

### 失敗時のマーカー解放

要約 or publish が失敗した記事はマーカーを `DEL` で解放して次周期で再試行可能にする:

```
reserve (SETNX)
  ├ False → 既に seen、スキップ
  └ True  → summarize → publish
              ├ 成功: マーカー保持 (30d TTL)
              └ 失敗: DEL でマーカー解放
                       errors カウント → ジョブ終了時 exit 1
```

プロセスクラッシュで `DEL` が走らなかった場合、マーカーは 30d TTL で自動解放される（永続損失なし）。

## body はプレーンテキストで送る

RSS の `content:encoded` は HTML 付き。news の管理 UI で `body` が編集対象テキストエリアに表示されるため、newsfeed 側で HTML を除去したプレーンテキストに正規化する (stdlib `html.parser`)。また、Vertex AI プロンプトの入力としても HTML より plain text の方が扱いが素直。

## 障害ドメインを記事単位に閉じる

個別記事の失敗は**ジョブ全体を中断させない**が、**失敗 ≥ 1 件ならジョブ終了時 exit 1**。握りつぶしではなく「1 記事の失敗を他記事の処理に波及させない」という責務境界の話。

| 障害 | 挙動 |
|---|---|
| 必須環境変数の未設定 | `load_config()` が例外 → exit 1 |
| Secret Manager 取得失敗 | 例外 → exit 1 (本番のみ) |
| Pub/Sub / Redis / Vertex AI クライアント初期化失敗 | exit 1 |
| 全 RSS ソース取得失敗 (`FetchError`) | exit 1 |
| 個別 RSS ソース取得失敗 | 構造化ログ、残りのソースで続行 |
| 個別記事の Vertex AI or publish 失敗 | マーカー `DEL`、構造化ログ、次の記事へ続行、errors カウント |
| ジョブ終了時 errors ≥ 1 | `PublishError` → exit 1 |

「即中断」ではなく「続行して最後に exit 1」を選ぶ理由:

- Redis 層 + news 側 `ON CONFLICT` で冪等性が担保されているため、続行しても重複副作用は生まれない
- 特定記事の恒常的失敗が他記事の publish を永久にブロックしないようにする
- 監視は exit 1 + 構造化ログ (source / article_id / source_url / エラー詳細) で十分可視化できる

## Upstash Redis の運用

matchmaking ([ADR-010](../../overload-party-common/docs/adr/010-matchmaking-queue-upstash-redis.md) / [ADR-012](../../overload-party-common/docs/adr/012-matchmaking-pubsub.md)) と同じ運用パターンに揃えている:

- 環境ごとに別 DB インスタンス (`overload-party-{dev,stg,prod}-newsfeed`)
- 本番は Secret Manager から endpoint と password を別シークレットで取得
- ローカルは docker-compose の Valkey に `UPSTASH_REDIS_URL` で接続
- 接続プロトコルは rediss:// (TLS 1.2+) / redis:// を URL スキームで切り替え
- dedup キー: `newsfeed:seen:{source_url}`、値: `"1"`、TTL: 2592000 秒 (30 日)

## イベント契約

publish する `news-article-collected` ペイロードは news リポの `packages/api-news/ArticleCollectedEvent` と一致させる。型パッケージが受信側 (news) に置かれている経緯は ADR-019 §パッケージ境界 を継承（ADR-020 でも同じ方針）。
