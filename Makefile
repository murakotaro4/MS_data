.DEFAULT_GOAL := help
SHELL := bash

MSDATA := msData.json

.PHONY: help setup format lint test validate validate-strict update normalize ci scrape-index scrape-details scrape-all import-details labels audit-labels

help:
	@echo "Available targets:"
	@echo "  setup             Create venv and sync dev deps (uv)"
	@echo "  format            Run black formatter"
	@echo "  lint              Run ruff linter"
	@echo "  test              Run pytest"
	@echo "  validate          Schema/typo/duplicate checks"
	@echo "  validate-strict   Same as validate, fail on typos"
	@echo "  update            Normalize/merge msData.json; INPUT=<json> optional"
	@echo "  normalize         Normalize existing msData.json in-place"
	@echo "  ci                Lint + test + validate-strict"
	@echo "  scrape-index      Fetch index (MS一覧) to cache/index.json"
	@echo "  scrape-details    Fetch details -> cache/details.jsonl (from cache/index.json)"
	@echo "  scrape-all        Index+details in one shot"
	@echo "  import-details    JSONL -> JSON array -> msData.json update"
	@echo "  labels            Extract raw/normalized row labels (cache-aware)"
	@echo "  audit-labels      Aggregate labels_raw.jsonl into Markdown report"

setup:
	uv venv
	uv sync --dev

format:
	uv run black .

lint:
	uv run ruff .

test:
	uv run pytest -q

validate:
	uv run python scripts/validate_msdata.py $(MSDATA)

validate-strict:
	uv run python scripts/validate_msdata.py $(MSDATA) --fail-on-typo

update:
	@if [ -n "$(INPUT)" ]; then \
		uv run python scripts/update_msdata.py -i "$(INPUT)"; \
	else \
		uv run python scripts/update_msdata.py -i; \
	fi

normalize:
	uv run python scripts/update_msdata.py -i

ci: lint test validate-strict

TTL ?= 7d
RATE ?= 1.0
LIMIT ?= 0
NO_NET ?=
FORCE ?=

scrape-index:
	uv run python scripts/scrape_msdata.py index --url https://w.atwiki.jp/battle-operation2/pages/377.html --out cache/index.json --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

scrape-details:
	uv run python scripts/scrape_msdata.py details --in cache/index.json --out cache/details.jsonl --rate $(RATE) --limit $(LIMIT) --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

scrape-all:
	uv run python scripts/scrape_msdata.py all --out cache/details.jsonl --rate $(RATE)

import-details:
	jq -s '.' cache/details.jsonl > cache/details.json
	uv run python scripts/update_msdata.py -i cache/details.json

labels:
	uv run python scripts/scrape_msdata.py labels --in cache/index.json --out cache/labels_raw.jsonl --rate $(RATE) --limit $(LIMIT) --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

audit-labels:
	uv run python scripts/audit_labels.py --in cache/labels_raw.jsonl --out reports/label_audit_$(shell date +%Y%m%d).md
