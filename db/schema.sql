CREATE SCHEMA IF NOT EXISTS newsfeed;

CREATE TABLE IF NOT EXISTS newsfeed.news_articles (
    article_id   VARCHAR(26) PRIMARY KEY,               -- ULID
    source       VARCHAR(20) NOT NULL,                   -- ソース種別（AWS / Azure / Google Cloud / Oracle 等）
    source_url   TEXT        NOT NULL UNIQUE,            -- 元記事 URL（UNIQUE で重複取得を防止）
    title        TEXT        NOT NULL,                   -- 記事タイトル
    summary      TEXT,                                   -- AI 生成の要約
    tags         TEXT[]      NOT NULL DEFAULT '{}',      -- タグ配列（ファクション / カードタイプとの関連付け用）
    raw_gcs_path TEXT,                                   -- GCS 上の生データパス
    published_at TIMESTAMPTZ,                            -- 元記事の公開日時（取得できない場合は NULL）
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()      -- 取得日時
);
