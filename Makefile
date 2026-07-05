.PHONY: run down test lint help

run: ## Run the job + infra in compose (batch: fetch→dedup→summarize→publish を 1 周)
	docker compose up --build

down: ## Stop the local stack and remove volumes
	docker compose down -v

test: ## Run pytest (Testcontainers starts Valkey; requires Docker)
	pytest tests/ -v

lint: ## Run ruff
	ruff check newsfeed/ tests/

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
