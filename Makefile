.PHONY: up down test lint run-local help

up: ## Start local Valkey + Pub/Sub emulator
	# pubsub-init は one-shot (exit 0) なので --wait の対象にせず別ステップで走らせる
	docker compose up -d --wait redis pubsub
	docker compose up pubsub-init

down: ## Stop local deps and wipe state
	docker compose down -v

test: up ## Run pytest against local Valkey + Pub/Sub emulator
	pytest tests/ -v

lint: ## Run ruff
	ruff check newsfeed/ tests/

run-local: up ## Run Cloud Run Job locally against local deps
	set -a && . ./.env.local && set +a && python main.py

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
