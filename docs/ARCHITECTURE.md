# Newsfeed サービス設計

本ドキュメントは **コードを読んでも一見しては分からない設計意図** だけを残す。フロー順序・環境変数一覧・RSS URL 等は [README.md](../README.md) と実装を一次情報とする。

## Newsfeed の責務境界

newsfeed は **RSS 取得と `news-article-collected` への publish** のみを担う Cloud Run Job。以下の副作用は**持たない**:

- DB 書き込み（news サービスが所有、ADR-019）
- AI 要約生成（news の ingest 側で Vertex AI を実行、ADR-019）
- 生 JSON アーカイブ（ADR-019 で廃止）

責務縮退により newsfeed の障害面は「RSS 取得」と「Pub/Sub publish」の 2 点に閉じる。Vertex AI quota や Cloud SQL 可用性は newsfeed の動作に影響しない。

## 冪等性は news に委譲する

newsfeed はローカル dedup を持たない。同一 `source_url` の記事が複数回 publish されうる設計で、重複排除は news 側の `ON CONFLICT DO NOTHING`（親記事・翻訳の両方）に委ねる。

ローカル dedup を持たせない理由:

- dedup 状態を永続化する先を newsfeed から消せる（GCS も廃止）
- 2 時間周期・1 回あたり数十件の規模では、news 側 dedup のコストが無視できる
- Vertex AI 呼び出しコストは news 側で発生するため、newsfeed 再実行では増えない

## body はプレーンテキストで送る

RSS の `content:encoded` は HTML タグ付きで、そのまま送ると news の管理 UI（`html/template` ベースのテキストエリア）で運用者が HTML をそのまま読むことになる。また XSS 対策を news 側に寄せる必要が出る。

newsfeed 側で HTML タグを除去したプレーンテキストに正規化してから publish する。`content:encoded` が無い場合は `description` にフォールバックする（どちらも RSS パーサ (`feedparser`) が取り出せる）。

## 障害ドメインを記事単位に閉じる

個別記事の publish 失敗は **ジョブ全体を中断させない**が、**失敗件数 ≥ 1 ならジョブ終了時に exit 1**。握りつぶしではなく、「1 記事の失敗を他記事の処理に波及させない」という責務境界の話。

| 障害 | 挙動 |
|---|---|
| 必須環境変数の未設定 | `load_config()` が例外 → exit 1 |
| Pub/Sub クライアントの初期化失敗 | exit 1 |
| 全 RSS ソース取得失敗 (`FetchError`) | exit 1（Cloud Run Job 失敗として記録） |
| 個別 RSS ソース取得失敗 | 構造化ログ出力、残りのソースで続行 |
| 個別記事の publish 失敗 | 構造化ログ出力 (source / article_id / source_url / エラー)、次の記事へ続行、**errors カウント** |
| ジョブ終了時に errors ≥ 1 | exit 1（部分成功でも失敗として扱う） |

「失敗したら即中断」ではなく「続行して最後に exit 1」を選ぶ理由:

- 冪等性は news 側の `ON CONFLICT DO NOTHING` で担保されているため、続行しても重複副作用は生まれない
- 即中断だと特定記事の恒常的失敗が他記事の publish を永久にブロックする。続行派では失敗記事だけが毎周期警告になり、他記事は通り続ける
- 監視の観点では、exit 1 + 構造化ログで失敗内容（どの記事が何故失敗したか）を可視化できる

## イベント契約

publish する `news-article-collected` ペイロードの仕様は ADR-019 を正とし、news リポの `packages/api-news/ArticleCollectedEvent` 型と一致させる。型パッケージが受信側 (news) に置かれている経緯は ADR-019 §パッケージ境界 を参照。
