package repository

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/kenyamaneko/overload-party-newsfeed/internal/model"
)

// NewsRepo handles persistence of news articles.
type NewsRepo struct {
	pool *pgxpool.Pool
}

func NewNewsRepo(pool *pgxpool.Pool) *NewsRepo {
	return &NewsRepo{pool: pool}
}

// Exists returns true if an article with the given source_url is already stored.
func (r *NewsRepo) Exists(ctx context.Context, sourceURL string) (bool, error) {
	var exists bool
	err := r.pool.QueryRow(ctx,
		`SELECT EXISTS(SELECT 1 FROM news_articles WHERE source_url = $1)`,
		sourceURL,
	).Scan(&exists)
	if err != nil {
		return false, fmt.Errorf("news_repo.Exists: %w", err)
	}
	return exists, nil
}

// Insert writes a new article. Returns an error if the source_url already exists.
func (r *NewsRepo) Insert(ctx context.Context, a model.NewsArticle) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO news_articles
		  (article_id, source, source_url, title, summary, tags, raw_gcs_path, published_at, fetched_at)
		VALUES
		  ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		ON CONFLICT (source_url) DO NOTHING`,
		a.ArticleID,
		a.Source,
		a.SourceURL,
		a.Title,
		a.Summary,
		a.Tags,
		a.RawGCSPath,
		a.PublishedAt,
		a.FetchedAt,
	)
	if err != nil {
		return fmt.Errorf("news_repo.Insert: %w", err)
	}
	return nil
}

// UpdateSummary sets the summary and tags for an article after AI processing.
func (r *NewsRepo) UpdateSummary(ctx context.Context, articleID string, summary string, tags []string) error {
	tag, err := r.pool.Exec(ctx, `
		UPDATE news_articles
		   SET summary = $2, tags = $3
		 WHERE article_id = $1`,
		articleID, summary, tags,
	)
	if err != nil {
		return fmt.Errorf("news_repo.UpdateSummary: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("news_repo.UpdateSummary: article %s not found", articleID)
	}
	return nil
}

// ListUnsummarized returns articles that have no summary yet (for retry runs).
func (r *NewsRepo) ListUnsummarized(ctx context.Context, limit int) ([]model.NewsArticle, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT article_id, source, source_url, title, raw_gcs_path, published_at, fetched_at
		  FROM news_articles
		 WHERE summary IS NULL
		 ORDER BY fetched_at ASC
		 LIMIT $1`,
		limit,
	)
	if err != nil {
		return nil, fmt.Errorf("news_repo.ListUnsummarized: %w", err)
	}
	defer rows.Close()

	var articles []model.NewsArticle
	for rows.Next() {
		var a model.NewsArticle
		if err := rows.Scan(
			&a.ArticleID, &a.Source, &a.SourceURL, &a.Title,
			&a.RawGCSPath, &a.PublishedAt, &a.FetchedAt,
		); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				break
			}
			return nil, fmt.Errorf("news_repo.ListUnsummarized scan: %w", err)
		}
		articles = append(articles, a)
	}
	return articles, rows.Err()
}
