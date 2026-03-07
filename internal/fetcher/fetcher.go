package fetcher

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/mmcdole/gofeed"

	"github.com/kenyamaneko/overload-party-newsfeed/internal/model"
)

// FeedSource defines a single RSS feed to poll.
type FeedSource struct {
	Name string // "aws" | "azure" | "gcp" | "oci"
	URL  string
}

// DefaultSources is the list of cloud provider RSS feeds.
var DefaultSources = []FeedSource{
	{Name: "aws", URL: "https://aws.amazon.com/blogs/aws/feed/"},
	{Name: "azure", URL: "https://azure.microsoft.com/en-us/blog/feed/"},
	{Name: "gcp", URL: "https://cloud.google.com/blog/feed"},
	{Name: "oci", URL: "https://blogs.oracle.com/cloud-infrastructure/rss"},
}

// FetchedItem is a raw item from an RSS feed before dedup/storage.
type FetchedItem struct {
	Source      string
	SourceURL   string
	Title       string
	Content     string // article body or description
	PublishedAt *time.Time
}

// FetchAll fetches all configured RSS feeds and returns the raw items.
// Errors for individual feeds are logged and skipped rather than aborting the job.
func FetchAll(ctx context.Context, sources []FeedSource) []FetchedItem {
	fp := gofeed.NewParser()
	var items []FetchedItem

	for _, src := range sources {
		feed, err := fp.ParseURLWithContext(src.URL, ctx)
		if err != nil {
			log.Printf("fetcher: failed to parse feed %s (%s): %v", src.Name, src.URL, err)
			continue
		}

		for _, item := range feed.Items {
			fi := FetchedItem{
				Source:    src.Name,
				SourceURL: canonicalURL(item),
				Title:     item.Title,
				Content:   itemContent(item),
			}
			if item.PublishedParsed != nil {
				t := *item.PublishedParsed
				fi.PublishedAt = &t
			}
			if fi.SourceURL == "" || fi.Title == "" {
				continue
			}
			items = append(items, fi)
		}

		log.Printf("fetcher: %s — fetched %d items", src.Name, len(feed.Items))
	}

	return items
}

// ToArticle converts a FetchedItem to a model.NewsArticle stub (no summary yet).
func ToArticle(item FetchedItem, articleID string) model.NewsArticle {
	return model.NewsArticle{
		ArticleID:   articleID,
		Source:      item.Source,
		SourceURL:   item.SourceURL,
		Title:       item.Title,
		PublishedAt: item.PublishedAt,
	}
}

func canonicalURL(item *gofeed.Item) string {
	if item.Link != "" {
		return item.Link
	}
	if item.GUID != "" {
		return item.GUID
	}
	return ""
}

func itemContent(item *gofeed.Item) string {
	if item.Content != "" {
		return item.Content
	}
	if item.Description != "" {
		return item.Description
	}
	return fmt.Sprintf("Title: %s\n\nPublished: %s", item.Title, item.Published)
}
