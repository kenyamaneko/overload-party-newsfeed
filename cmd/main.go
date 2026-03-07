package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/oklog/ulid/v2"

	"github.com/kenyamaneko/overload-party-newsfeed/internal/fetcher"
	"github.com/kenyamaneko/overload-party-newsfeed/internal/repository"
	"github.com/kenyamaneko/overload-party-newsfeed/internal/storage"
	"github.com/kenyamaneko/overload-party-newsfeed/internal/summarizer"
)

func main() {
	if err := run(); err != nil {
		log.Fatalf("newsfeed job failed: %v", err)
	}
}

func run() error {
	ctx := context.Background()

	cfg, err := loadConfig()
	if err != nil {
		return err
	}

	// --- Dependencies ---
	pool, err := pgxpool.New(ctx, cfg.databaseURL)
	if err != nil {
		return fmt.Errorf("pgxpool.New: %w", err)
	}
	defer pool.Close()

	gcs, err := storage.NewGCSStorage(ctx, cfg.gcsBucket)
	if err != nil {
		return fmt.Errorf("NewGCSStorage: %w", err)
	}
	defer gcs.Close()

	sum, err := summarizer.New(ctx, cfg.gcpProject, cfg.vertexLocation)
	if err != nil {
		return fmt.Errorf("summarizer.New: %w", err)
	}
	defer sum.Close()

	repo := repository.NewNewsRepo(pool)

	// --- Step 1: Fetch RSS feeds ---
	log.Println("step 1: fetching RSS feeds")
	items := fetcher.FetchAll(ctx, fetcher.DefaultSources)
	log.Printf("step 1: fetched %d items total", len(items))

	// --- Step 2: Dedup, save to GCS, insert stub, summarize ---
	var (
		skipped    int
		inserted   int
		summarized int
		errCount   int
	)

	for _, item := range items {
		exists, err := repo.Exists(ctx, item.SourceURL)
		if err != nil {
			log.Printf("dedup check failed for %s: %v", item.SourceURL, err)
			errCount++
			continue
		}
		if exists {
			skipped++
			continue
		}

		articleID := ulid.Make().String()

		// Save raw data to GCS.
		gcsPath, err := gcs.Save(ctx, articleID, item)
		if err != nil {
			log.Printf("gcs.Save failed for %s: %v", item.SourceURL, err)
			errCount++
			continue
		}

		// Insert article stub (no summary yet).
		article := fetcher.ToArticle(item, articleID)
		article.RawGCSPath = &gcsPath
		article.FetchedAt = time.Now().UTC()

		if err := repo.Insert(ctx, article); err != nil {
			log.Printf("repo.Insert failed for %s: %v", item.SourceURL, err)
			errCount++
			continue
		}
		inserted++

		// Summarize with Vertex AI.
		result, err := sum.Summarize(ctx, item.Title, item.Content)
		if err != nil {
			// Non-fatal: article is saved, summary will be retried next run.
			log.Printf("summarizer failed for %s: %v", item.SourceURL, err)
			errCount++
			continue
		}

		if err := repo.UpdateSummary(ctx, articleID, result.Summary, result.Tags); err != nil {
			log.Printf("UpdateSummary failed for %s: %v", articleID, err)
			errCount++
			continue
		}
		summarized++
	}

	log.Printf("step 2: inserted=%d summarized=%d skipped=%d errors=%d",
		inserted, summarized, skipped, errCount)

	// --- Step 3: Retry unsummarized articles from previous runs ---
	log.Println("step 3: retrying unsummarized articles")
	retried, retryErr := retryUnsummarized(ctx, repo, gcs, sum)
	log.Printf("step 3: retried=%d errors=%d", retried, retryErr)

	return nil
}

func retryUnsummarized(ctx context.Context, repo *repository.NewsRepo, gcs *storage.GCSStorage, sum *summarizer.Summarizer) (int, int) {
	articles, err := repo.ListUnsummarized(ctx, 50)
	if err != nil {
		log.Printf("ListUnsummarized failed: %v", err)
		return 0, 1
	}

	succeeded, failed := 0, 0
	for _, a := range articles {
		content := ""
		if a.RawGCSPath != nil {
			c, err := gcs.LoadContent(ctx, *a.RawGCSPath)
			if err != nil {
				log.Printf("retry: LoadContent failed for %s: %v", a.ArticleID, err)
				// Fall through with empty content rather than skipping entirely.
			} else {
				content = c
			}
		}

		result, err := sum.Summarize(ctx, a.Title, content)
		if err != nil {
			log.Printf("retry summarize failed for %s: %v", a.ArticleID, err)
			failed++
			continue
		}
		if err := repo.UpdateSummary(ctx, a.ArticleID, result.Summary, result.Tags); err != nil {
			log.Printf("retry UpdateSummary failed for %s: %v", a.ArticleID, err)
			failed++
			continue
		}
		succeeded++
	}
	return succeeded, failed
}

type config struct {
	databaseURL    string
	gcsBucket      string
	gcpProject     string
	vertexLocation string
}

func loadConfig() (config, error) {
	cfg := config{
		databaseURL:    os.Getenv("DATABASE_URL"),
		gcsBucket:      os.Getenv("GCS_BUCKET"),
		gcpProject:     os.Getenv("GCP_PROJECT"),
		vertexLocation: getEnvOrDefault("VERTEX_LOCATION", "us-central1"),
	}

	var missing []string
	if cfg.databaseURL == "" {
		missing = append(missing, "DATABASE_URL")
	}
	if cfg.gcsBucket == "" {
		missing = append(missing, "GCS_BUCKET")
	}
	if cfg.gcpProject == "" {
		missing = append(missing, "GCP_PROJECT")
	}
	if len(missing) > 0 {
		return config{}, fmt.Errorf("missing required env vars: %v", missing)
	}
	return cfg, nil
}

func getEnvOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

