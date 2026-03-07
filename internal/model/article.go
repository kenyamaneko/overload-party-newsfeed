package model

import "time"

type NewsArticle struct {
	ArticleID   string
	Source      string // "aws" | "azure" | "gcp" | "oci"
	SourceURL   string
	Title       string
	Summary     *string // nil = AI要約未完了
	Tags        []string
	RawGCSPath  *string
	PublishedAt *time.Time
	FetchedAt   time.Time
}
