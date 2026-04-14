# newsfeed スキーマ - データ設計

> **DDL の SSoT:** `db/schema.sql`

## 設計概要

newsfeed スキーマはクラウドニュース記事の収集結果を格納する。Cloud Run Job が定期実行され、各クラウドプロバイダーの公式ブログ等から記事を取得・要約して保存する。ops の fetch-schemas.py がスキーマ名を `newsfeed.` プレフィックスで wrap して適用する。

---

## テーブル構成

### news_articles

ニュース記事。

- **PK:** `article_id` (VARCHAR(26), ULID)
- **UNIQUE:** `source_url`

<!-- BEGIN GENERATED: news_articles -->
| カラム名 | 型 | Nullable | 説明 |
|---|---|---|---|
| `article_id` | VARCHAR(26) | No | ULID |
| `source` | VARCHAR(20) | No | ソース種別（AWS / Azure / Google Cloud / Oracle 等） |
| `source_url` | TEXT | No | 元記事 URL（UNIQUE で重複取得を防止） |
| `title` | TEXT | No | 記事タイトル |
| `summary` | TEXT | Yes | AI 生成の要約 |
| `tags` | TEXT[] | No | タグ配列（ファクション / カードタイプとの関連付け用） |
| `raw_gcs_path` | TEXT | Yes | GCS 上の生データパス |
| `published_at` | TIMESTAMPTZ | Yes | 元記事の公開日時（取得できない場合は NULL） |
| `fetched_at` | TIMESTAMPTZ | No | 取得日時 |
<!-- END GENERATED: news_articles -->

**設計判断:**
- `source_url` に UNIQUE 制約を張ることで、同一記事の重複取得を冪等に処理する（`ON CONFLICT DO NOTHING`）
- `tags` を TEXT 配列にしているのは、タグ数が可変かつ検索時は `@>` 演算子で十分なため

---

## テーブル間リレーション

```
news_articles (PK: article_id)
  （他テーブルへの参照なし。独立したテーブル）
```

---

## インデックス戦略

現時点で明示的なセカンダリインデックスは PK と UNIQUE 制約のみ。記事一覧のページネーションが必要になった場合は `(fetched_at DESC)` や `(source, fetched_at DESC)` を検討する。
