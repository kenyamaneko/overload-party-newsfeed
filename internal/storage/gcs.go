package storage

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"cloud.google.com/go/storage"

	"github.com/kenyamaneko/overload-party-newsfeed/internal/fetcher"
)

// GCSStorage handles writing raw article data to Google Cloud Storage.
type GCSStorage struct {
	client *storage.Client
	bucket string
}

func NewGCSStorage(ctx context.Context, bucket string) (*GCSStorage, error) {
	client, err := storage.NewClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("storage.NewClient: %w", err)
	}
	return &GCSStorage{client: client, bucket: bucket}, nil
}

func (g *GCSStorage) Close() error {
	return g.client.Close()
}

// rawPayload is the JSON structure written to GCS.
type rawPayload struct {
	ArticleID   string     `json:"article_id"`
	Source      string     `json:"source"`
	SourceURL   string     `json:"source_url"`
	Title       string     `json:"title"`
	Content     string     `json:"content"`
	PublishedAt *time.Time `json:"published_at,omitempty"`
	FetchedAt   time.Time  `json:"fetched_at"`
}

// LoadContent reads the article content field from a previously saved raw GCS object.
// gcsPath must be a full gs://bucket/object path.
func (g *GCSStorage) LoadContent(ctx context.Context, gcsPath string) (string, error) {
	// Strip "gs://{bucket}/" prefix to get the object path.
	prefix := fmt.Sprintf("gs://%s/", g.bucket)
	objPath := strings.TrimPrefix(gcsPath, prefix)
	if objPath == gcsPath {
		return "", fmt.Errorf("gcs: path %q does not belong to bucket %q", gcsPath, g.bucket)
	}

	r, err := g.client.Bucket(g.bucket).Object(objPath).NewReader(ctx)
	if err != nil {
		return "", fmt.Errorf("gcs: NewReader %s: %w", objPath, err)
	}
	defer r.Close()

	var payload rawPayload
	if err := json.NewDecoder(r).Decode(&payload); err != nil {
		return "", fmt.Errorf("gcs: decode %s: %w", objPath, err)
	}
	return payload.Content, nil
}

// Save writes the raw fetched item to GCS and returns the object path.
// Path format: raw/{source}/{YYYY-MM-DD}/{articleID}.json
func (g *GCSStorage) Save(ctx context.Context, articleID string, item fetcher.FetchedItem) (string, error) {
	date := time.Now().UTC().Format("2006-01-02")
	objPath := fmt.Sprintf("raw/%s/%s/%s.json", item.Source, date, articleID)

	payload := rawPayload{
		ArticleID:   articleID,
		Source:      item.Source,
		SourceURL:   item.SourceURL,
		Title:       item.Title,
		Content:     item.Content,
		PublishedAt: item.PublishedAt,
		FetchedAt:   time.Now().UTC(),
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("json.Marshal: %w", err)
	}

	obj := g.client.Bucket(g.bucket).Object(objPath)
	w := obj.NewWriter(ctx)
	w.ContentType = "application/json"

	if _, err := w.Write(data); err != nil {
		w.Close()
		return "", fmt.Errorf("gcs write %s: %w", objPath, err)
	}
	if err := w.Close(); err != nil {
		return "", fmt.Errorf("gcs close %s: %w", objPath, err)
	}

	return fmt.Sprintf("gs://%s/%s", g.bucket, objPath), nil
}
