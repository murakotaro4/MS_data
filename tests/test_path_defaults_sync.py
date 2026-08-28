from __future__ import annotations

import argparse
from pathlib import Path
from types import ModuleType

import pytest

from ms_data import tasks
from ms_data.audit import (
    audit_index_vs_msdata,
    audit_labels,
    audit_official_overrides,
    detect_msdata_rollbacks,
)
from ms_data.core import paths
from ms_data.pipeline import generate_provenance, update_msdata
from ms_data.reporting import build_atwiki_quality_report, prune_reports
from ms_data.scraping import scrape_msdata
from ms_data.validation import (
    validate_generated_reports,
    validate_msdata,
    validate_official_overrides_schema,
    validate_report_contract,
)


def _as_posix(value: str | Path) -> str:
    return value.as_posix() if isinstance(value, Path) else Path(value).as_posix()


PATH_DEFAULTS = (
    (paths.MSDATA, tasks.DEFAULT_MSDATA),
    (paths.INDEX_JSON, tasks.DEFAULT_INDEX_OUT),
    (paths.DETAILS_JSONL, tasks.DEFAULT_DETAILS_OUT),
    (paths.DETAILS_JSON, tasks.DEFAULT_DETAILS_JSON),
    (paths.HTML_CACHE_DIR, tasks.DEFAULT_HTML_DIR),
    (paths.REPORTS_DIR, tasks.DEFAULT_REPORTS_DIR),
    (paths.LABELS_RAW_JSONL, tasks.DEFAULT_LABELS_OUT),
    (paths.OFFICIAL_OVERRIDES_DIR, tasks.DEFAULT_OVERRIDES_DIR),
    (paths.OFFICIAL_OVERRIDES_SCHEMA, tasks.DEFAULT_OFFICIAL_OVERRIDES_SCHEMA),
    (paths.REPORTS_MANIFEST, tasks.DEFAULT_REPORTS_MANIFEST),
    (paths.REPORT_SCHEMAS_DIR, tasks.DEFAULT_REPORT_SCHEMA_DIR),
    (paths.CHANGED_INDEX_JSON, tasks.DEFAULT_CHANGED_INDEX_OUT),
    (paths.CHANGED_INDEX_META_JSON, tasks.DEFAULT_CHANGED_META_OUT),
    (paths.DETAIL_FETCH_STATE_JSON, tasks.DEFAULT_DETAIL_FETCH_STATE),
    (paths.FETCH_STATS_JSON, tasks.DEFAULT_FETCH_STATS),
    (
        paths.FIELD_COMPLETENESS_ALLOWLIST,
        tasks.DEFAULT_FIELD_COMPLETENESS_ALLOWLIST,
    ),
)


@pytest.mark.parametrize(("canonical", "task_default"), PATH_DEFAULTS)
def test_tasks_path_defaults_are_posix_aliases(
    canonical: Path, task_default: str
) -> None:
    assert isinstance(canonical, Path)
    assert task_default == canonical.as_posix()


@pytest.mark.parametrize(
    ("argv", "expected"),
    (
        (
            ["index"],
            {
                "out": paths.INDEX_JSON,
                "fetch_stats_out": paths.FETCH_STATS_JSON,
            },
        ),
        (
            ["details", "--in", "input.json"],
            {
                "out": paths.DETAILS_JSONL,
                "detail_fetch_state_out": paths.DETAIL_FETCH_STATE_JSON,
                "fetch_stats_out": paths.FETCH_STATS_JSON,
            },
        ),
        (
            ["all"],
            {
                "out": paths.DETAILS_JSONL,
                "detail_fetch_state_out": paths.DETAIL_FETCH_STATE_JSON,
                "fetch_stats_out": paths.FETCH_STATS_JSON,
            },
        ),
        (
            ["detect-changed", "--in", "input.json"],
            {
                "out": paths.CHANGED_INDEX_JSON,
                "meta_out": paths.CHANGED_INDEX_META_JSON,
                "reports_dir": paths.REPORTS_DIR,
                "msdata": paths.MSDATA,
                "detail_fetch_state": paths.DETAIL_FETCH_STATE_JSON,
            },
        ),
        (
            ["labels", "--in", "input.json"],
            {"out": paths.LABELS_RAW_JSONL},
        ),
    ),
)
def test_scrape_msdata_argparse_path_defaults(
    argv: list[str], expected: dict[str, Path]
) -> None:
    args = scrape_msdata.build_parser().parse_args(argv)
    for attribute, canonical in expected.items():
        assert _as_posix(getattr(args, attribute)) == canonical.as_posix()


class _ParsedArgs(Exception):
    def __init__(self, namespace: argparse.Namespace) -> None:
        super().__init__()
        self.namespace = namespace


def _capture_main_args(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    argv: list[str],
) -> argparse.Namespace:
    original = argparse.ArgumentParser.parse_args

    def capture(
        parser: argparse.ArgumentParser,
        args: list[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        parsed = original(parser, args, namespace)
        raise _ParsedArgs(parsed)

    with monkeypatch.context() as context:
        context.setattr(argparse.ArgumentParser, "parse_args", capture)
        with pytest.raises(_ParsedArgs) as captured:
            module.main(argv)
    return captured.value.namespace


@pytest.mark.parametrize(
    ("module", "argv", "expected"),
    (
        (
            build_atwiki_quality_report,
            ["--report-date", "20260829", "--source-run-id", "1", "--out", "x"],
            {
                "index": paths.INDEX_JSON,
                "changed_index": paths.CHANGED_INDEX_JSON,
                "changed_meta": paths.CHANGED_INDEX_META_JSON,
                "detail_fetch_state": paths.DETAIL_FETCH_STATE_JSON,
                "details_json": paths.DETAILS_JSON,
                "details_jsonl": paths.DETAILS_JSONL,
                "current_msdata": paths.MSDATA,
                "fetch_stats": paths.FETCH_STATS_JSON,
            },
        ),
        (
            update_msdata,
            [],
            {
                "output": paths.MSDATA,
                "official_overrides_dir": paths.OFFICIAL_OVERRIDES_DIR,
            },
        ),
        (
            validate_msdata,
            [],
            {"path": paths.MSDATA, "schema": paths.MSDATA_SCHEMA},
        ),
        (
            validate_official_overrides_schema,
            [],
            {
                "overrides_dir": paths.OFFICIAL_OVERRIDES_DIR,
                "schema": paths.OFFICIAL_OVERRIDES_SCHEMA,
            },
        ),
        (
            validate_generated_reports,
            [],
            {
                "reports_dir": paths.REPORTS_DIR,
                "schema_dir": paths.REPORT_SCHEMAS_DIR,
            },
        ),
        (
            validate_report_contract,
            ["--mode", "ci"],
            {
                "manifest": paths.REPORTS_MANIFEST,
                "reports_dir": paths.REPORTS_DIR,
            },
        ),
        (prune_reports, [], {"manifest": paths.REPORTS_MANIFEST}),
        (
            audit_index_vs_msdata,
            [],
            {"index": paths.INDEX_JSON, "ms": paths.MSDATA},
        ),
        (audit_labels, [], {"input": paths.LABELS_RAW_JSONL}),
        (
            detect_msdata_rollbacks,
            ["--old", "old.json", "--new", "new.json", "--out", "out.md"],
            {"official_overrides_dir": paths.OFFICIAL_OVERRIDES_DIR},
        ),
        (
            audit_official_overrides,
            ["--out", "out.md"],
            {
                "overrides_dir": paths.OFFICIAL_OVERRIDES_DIR,
                "current": paths.MSDATA,
            },
        ),
    ),
)
def test_main_argparse_path_defaults(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    argv: list[str],
    expected: dict[str, Path],
) -> None:
    args = _capture_main_args(monkeypatch, module, argv)
    for attribute, canonical in expected.items():
        assert _as_posix(getattr(args, attribute)) == canonical.as_posix()


def test_generate_provenance_argparse_path_defaults() -> None:
    args = generate_provenance.parse_args(
        ["--date", "20260829", "--diff", "diff.md", "--out", "out.json"]
    )
    expected = {
        "index": paths.INDEX_JSON,
        "details_jsonl": paths.DETAILS_JSONL,
        "details_json": paths.DETAILS_JSON,
        "msdata": paths.MSDATA,
        "html_dir": paths.HTML_CACHE_DIR,
    }
    for attribute, canonical in expected.items():
        assert _as_posix(getattr(args, attribute)) == canonical.as_posix()


def test_load_official_overrides_default_remains_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: Path | None = None

    def fake_loader(
        directory: Path, *, valid_value_keys: set[str]
    ) -> dict[str, dict[str, update_msdata.OfficialOverrideValue]]:
        nonlocal received
        directory.exists()
        received = directory
        assert valid_value_keys == update_msdata.OFFICIAL_OVERRIDE_VALUE_KEYS
        return {}

    monkeypatch.setattr(
        update_msdata._official_overrides, "load_official_overrides", fake_loader
    )

    assert update_msdata.load_official_overrides() == {}
    assert isinstance(received, Path)
    assert received == paths.OFFICIAL_OVERRIDES_DIR
