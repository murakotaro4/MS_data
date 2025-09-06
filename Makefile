.DEFAULT_GOAL := help
SHELL := bash

MSDATA := msData.json

.PHONY: help setup format lint test validate validate-strict update normalize ci scrape-index scrape-details scrape-all import-details labels audit-labels skills skills-table owners-table build-skills build-param-skills build-owners-flat audit-skills preview-params

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
	@echo "  skills            Extract core system skills -> cache/skills.json"
	@echo "  skills-table      Extract strict table rows -> cache/skills_table.json"
	@echo "  owners-table      Extract owners reverse-index table rows -> cache/owners_table.json"
	@echo "  build-skills      Build data/skills_catalog.json & data/skill_owners.json"
	@echo "  build-param-skills Build data/skills_params.json (parameter-only)"
	@echo "  build-owners-flat Build data/skill_owners_flat.json (skill/series/ms_level)"
	@echo "  preview-params    Derive parameter-only preview per MS -> derived/ms_params_preview.json"
	@echo "  audit-skills      Audit owners vs msData.json -> reports/skill_owners_audit_*.md"

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
	uv run python -m scripts.validate_msdata $(MSDATA)

validate-strict:
	uv run python -m scripts.validate_msdata $(MSDATA) --fail-on-typo

update:
	@if [ -n "$(INPUT)" ]; then \
		uv run python -m scripts.update_msdata -i "$(INPUT)"; \
	else \
		uv run python -m scripts.update_msdata -i; \
	fi

normalize:
	uv run python -m scripts.update_msdata -i

ci: lint test validate-strict

TTL ?= 7d
RATE ?= 1.0
LIMIT ?= 0
NO_NET ?=
FORCE ?=

scrape-index:
	uv run python -m scripts.scrape_msdata index --url https://w.atwiki.jp/battle-operation2/pages/377.html --out cache/index.json --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

scrape-details:
	uv run python -m scripts.scrape_msdata details --in cache/index.json --out cache/details.jsonl --rate $(RATE) --limit $(LIMIT) --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

scrape-all:
	uv run python -m scripts.scrape_msdata all --out cache/details.jsonl --rate $(RATE)

import-details:
	jq -s '.' cache/details.jsonl > cache/details.json
	uv run python -m scripts.update_msdata -i cache/details.json

labels:
	uv run python -m scripts.scrape_msdata labels --in cache/index.json --out cache/labels_raw.jsonl --rate $(RATE) --limit $(LIMIT) --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

audit-labels:
	uv run python -m scripts.audit_labels --in cache/labels_raw.jsonl --out reports/label_audit_$(shell date +%Y%m%d).md

skills:
	uv run python -m scripts.extract_skills all --out cache/skills.json --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

skills-table:
	uv run python -m scripts.extract_skills table --out cache/skills_table.json --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

owners-table:
	uv run python -m scripts.extract_skills owners-table --out cache/owners_table.json --ttl $(TTL) $(if $(NO_NET),--no-network,) $(if $(FORCE),--force,)

build-skills:
	uv run python -m scripts.build_skills --in cache/skills.json --out-catalog data/skills_catalog.json --out-owners data/skill_owners.json

audit-skills:
	uv run python -m scripts.audit_skills --owners data/skill_owners.json --msdata $(MSDATA)

build-param-skills:
	uv run python -m scripts.build_param_skills --in cache/skills_table.json --out data/skills_params.json --policy data/skills_policy.json --audit-out reports/skills_params_audit.json

build-owners-flat:
	uv run python -m scripts.build_owners_flat --in cache/owners_table.json --msdata $(MSDATA) --policy data/skills_policy.json --out data/skill_owners_flat.json --audit-out reports/owners_flat_audit.json

preview-params:
	uv run python -m scripts.preview_params --msdata $(MSDATA) --owners data/skill_owners_flat.json --params data/skills_params.json --out derived/ms_params_preview.json
