.DEFAULT_GOAL := help
SHELL := bash

MSDATA := msData.json

.PHONY: help setup format lint test validate validate-strict validate-skills update normalize ci scrape-index scrape-details scrape-all import-details labels audit-labels report-diff audit-index skills skills-table owners-table build-skills build-param-skills build-owners-flat audit-skills preview-params provenance snapshot validate-report-contract

help:
	@echo "Available targets:"
	@echo "  setup             Create venv and sync dev deps (uv)"
	@echo "  format            Run black formatter"
	@echo "  lint              Run ruff linter"
	@echo "  test              Run pytest"
	@echo "  validate          Schema/typo/duplicate checks"
	@echo "  validate-strict   Same as validate, fail on typos"
	@echo "  validate-skills   Validate committed skills JSON files"
	@echo "  update            Normalize/merge msData.json; INPUT=<json> optional"
	@echo "  normalize         Normalize existing msData.json in-place"
	@echo "  ci                Lint + test + validate-strict + validate-skills"
	@echo "  scrape-index      Fetch index (MS一覧) to cache/index.json"
	@echo "  scrape-details    Fetch details -> cache/details.jsonl (from cache/index.json)"
	@echo "  scrape-all        Index+details in one shot"
	@echo "  import-details    JSONL -> JSON array -> msData.json update"
	@echo "  labels            Extract raw/normalized row labels (cache-aware)"
	@echo "  audit-labels      Aggregate labels_raw.jsonl into Markdown report"
	@echo "  report-diff       Generate diff report between two msData.json files"
	@echo "  provenance        Generate reports/provenance_YYYYMMDD.json"
	@echo "  snapshot          Create raw_snapshot_YYYYMMDD_runlocal.tar.xz"
	@echo "  validate-report-contract Validate reports naming/contract"
	@echo "  audit-index       Compare index.json vs msData.json (names/attr/cost)"
	@echo "  skills            Extract core system skills -> cache/skills.json"
	@echo "  skills-table      Extract strict table rows -> cache/skills_table.json"
	@echo "  owners-table      Extract owners reverse-index table rows -> cache/owners_table.json"
	@echo "  build-skills      Build data/skills_catalog.json & data/skill_owners.json"
	@echo "  build-param-skills Build data/skills_params.json (parameter-only)"
	@echo "  build-owners-flat Build data/skill_owners_flat.json (skill/series/ms_level)"
	@echo "  preview-params    Derive parameter-only preview per MS -> derived/ms_params_preview.json"
	@echo "  audit-skills      Audit owners vs msData.json -> reports/skill_owners_audit_*.md"

setup:
	uv run python -m scripts.tasks setup

format:
	uv run python -m scripts.tasks format

lint:
	uv run python -m scripts.tasks lint

test:
	uv run python -m scripts.tasks test

validate:
	MSDATA="$(MSDATA)" uv run python -m scripts.tasks validate

validate-strict:
	MSDATA="$(MSDATA)" uv run python -m scripts.tasks validate-strict

validate-skills:
	uv run python -m scripts.tasks validate-skills

update:
	INPUT="$(INPUT)" uv run python -m scripts.tasks update

normalize:
	uv run python -m scripts.tasks normalize

ci:
	uv run python -m scripts.tasks ci

TTL ?= 7d
RATE ?= 2.0
LIMIT ?= 0
NO_NET ?=
FORCE ?=
REPORT_DATE ?= $(shell date +%Y%m%d)
PROVENANCE_OUT ?= reports/provenance_$(REPORT_DATE).json
RAW_SNAPSHOT_FILE ?= raw_snapshot_$(REPORT_DATE)_runlocal.tar.xz

scrape-index:
	TTL="$(TTL)" NO_NET="$(NO_NET)" FORCE="$(FORCE)" uv run python -m scripts.tasks scrape-index

scrape-details:
	TTL="$(TTL)" RATE="$(RATE)" LIMIT="$(LIMIT)" NO_NET="$(NO_NET)" FORCE="$(FORCE)" uv run python -m scripts.tasks scrape-details

scrape-all:
	RATE="$(RATE)" LIMIT="$(LIMIT)" uv run python -m scripts.tasks scrape-all

import-details:
	uv run python -m scripts.tasks import-details

labels:
	TTL="$(TTL)" RATE="$(RATE)" LIMIT="$(LIMIT)" NO_NET="$(NO_NET)" FORCE="$(FORCE)" uv run python -m scripts.tasks labels

audit-labels:
	REPORT_DATE="$(REPORT_DATE)" uv run python -m scripts.tasks audit-labels

report-diff:
	OLD="$(OLD)" NEW="$(NEW)" OUT="$(OUT)" uv run python -m scripts.tasks report-diff

provenance:
	REPORT_DATE="$(REPORT_DATE)" PROVENANCE_OUT="$(PROVENANCE_OUT)" MSDATA="$(MSDATA)" TTL="$(TTL)" RATE="$(RATE)" LIMIT="$(LIMIT)" uv run python -m scripts.tasks provenance

snapshot:
	REPORT_DATE="$(REPORT_DATE)" PROVENANCE_OUT="$(PROVENANCE_OUT)" RAW_SNAPSHOT_FILE="$(RAW_SNAPSHOT_FILE)" MSDATA="$(MSDATA)" TTL="$(TTL)" RATE="$(RATE)" LIMIT="$(LIMIT)" uv run python -m scripts.tasks snapshot

# Index vs msData audit (names, presence, attr/cost)
audit-index:
	REPORT_DATE="$(REPORT_DATE)" MSDATA="$(MSDATA)" uv run python -m scripts.tasks audit-index

skills:
	TTL="$(TTL)" NO_NET="$(NO_NET)" FORCE="$(FORCE)" uv run python -m scripts.tasks skills

skills-table:
	TTL="$(TTL)" NO_NET="$(NO_NET)" FORCE="$(FORCE)" uv run python -m scripts.tasks skills-table

owners-table:
	TTL="$(TTL)" NO_NET="$(NO_NET)" FORCE="$(FORCE)" uv run python -m scripts.tasks owners-table

build-skills:
	uv run python -m scripts.tasks build-skills

audit-skills:
	MSDATA="$(MSDATA)" uv run python -m scripts.tasks audit-skills

build-param-skills:
	uv run python -m scripts.tasks build-param-skills

build-owners-flat:
	MSDATA="$(MSDATA)" uv run python -m scripts.tasks build-owners-flat

preview-params:
	MSDATA="$(MSDATA)" uv run python -m scripts.tasks preview-params

validate-report-contract:
	MODE="$(MODE)" REPORT_DATE="$(REPORT_DATE)" SOURCE_RUN_ID="$(SOURCE_RUN_ID)" HEAD_REF="$(HEAD_REF)" DIFF_PATH="$(DIFF_PATH)" PROVENANCE_PATH="$(PROVENANCE_PATH)" ARTIFACT_NAME="$(ARTIFACT_NAME)" SNAPSHOT_FILE="$(SNAPSHOT_FILE)" RELEASE_TAG="$(RELEASE_TAG)" uv run python -m scripts.tasks validate-report-contract
