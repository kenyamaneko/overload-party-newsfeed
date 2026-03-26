CREATE TABLE IF NOT EXISTS news_articles (
    article_id   VARCHAR(26) PRIMARY KEY,
    source       VARCHAR(20) NOT NULL,
    source_url   TEXT        NOT NULL UNIQUE,
    title        TEXT        NOT NULL,
    summary      TEXT,
    tags         TEXT[]      NOT NULL DEFAULT '{}',
    raw_gcs_path TEXT,
    published_at TIMESTAMPTZ,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
