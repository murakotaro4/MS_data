.DEFAULT_GOAL := help
SHELL := bash

MSDATA := msData.json

.PHONY: help setup format lint test validate validate-strict update normalize ci

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

