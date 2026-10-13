.DEFAULT_GOAL := help
# Container engine: `make up ENGINE=podman` works too.
ENGINE ?= docker
.PHONY: help install lint format typecheck test bench check up down docker-build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install dependencies and git hooks
	uv sync
	uv run pre-commit install

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-format code
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Strict type checking
	uv run mypy

test: ## Run unit and integration tests with coverage
	uv run pytest

bench: ## Measure instrumentation overhead
	uv run python benchmarks/overhead.py

check: lint typecheck test ## Everything CI runs, except the Docker build

docker-build: ## Build the demo image
	$(ENGINE) build -t llmobs-demo:local .

up: ## Start demo app, traffic, collector, Prometheus, Tempo and Grafana
	$(ENGINE) build -t llmobs-demo:local .
	$(ENGINE) compose up -d --no-build
	@echo "Grafana: http://localhost:$${GRAFANA_PORT:-3000}"

down: ## Stop the stack
	$(ENGINE) compose down
