SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
VENV ?= .venv
BIN := $(VENV)/bin
PYTHON_VERSION := 3.12
# Optional mutant-name pattern for `make mutate`, e.g. MUTANTS='app.reports*'
MUTANTS ?=

.PHONY: help setup test lint format typecheck check mutate lock run clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## Create .venv with the pinned dev dependencies and the app in editable mode
	$(UV) venv --allow-existing --python $(PYTHON_VERSION) $(VENV)
	$(UV) pip sync --python $(BIN)/python requirements-dev.txt
	$(UV) pip install --python $(BIN)/python --no-deps -e .

test: ## Run the test suite
	$(BIN)/pytest

lint: ## ruff check and ruff format --check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Apply ruff formatting and safe lint fixes
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

typecheck: ## mypy on the app package
	$(BIN)/mypy app

check: lint typecheck test ## lint + typecheck + test (what fleet/tests runs)

mutate: ## Mutation testing with mutmut; scope with MUTANTS='app.reports*'
	$(BIN)/mutmut run $(MUTANTS)
	@$(BIN)/mutmut results | { grep -v ': not checked' || true; }

lock: ## Regenerate requirements*.txt (hash-pinned) from pyproject.toml
	$(UV) pip compile pyproject.toml --generate-hashes --python-version $(PYTHON_VERSION) --no-header -o requirements.txt
	$(UV) pip compile pyproject.toml --extra dev --generate-hashes --python-version $(PYTHON_VERSION) --no-header -o requirements-dev.txt

run: ## Serve the API on http://127.0.0.1:8000
	$(BIN)/uvicorn --factory app.main:create_app

clean: ## Remove the venv, caches and mutation-testing output
	rm -rf $(VENV) mutants .mutmut-cache .pytest_cache .ruff_cache .mypy_cache
