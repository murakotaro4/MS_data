#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from ms_data.core.env import env_flag as _env_flag
from ms_data.core.env import env_float as _env_float
from ms_data.core.env import env_int as _env_int
from ms_data.core.env import env_str as _env_str
from ms_data.core.json_io import load_json as _load_json_file


INDEX_URL = "https://w.atwiki.jp/battle-operation2/pages/377.html"


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _run(*args: str) -> int:
    completed = subprocess.run(args, check=False)
    return int(completed.returncode)


def _run_python_module(module: str, *args: str) -> int:
    return _run(sys.executable, "-m", module, *args)


def _require_env(name: str) -> str:
    value = _env_str(name)
    if value is None:
        raise SystemExit(f"ERROR: environment variable {name} is required")
    return value


def _report_date() -> str:
    return _env_str("REPORT_DATE", _today()) or _today()


def _provenance_out() -> str:
    return _env_str("PROVENANCE_OUT", f"reports/provenance_{_report_date()}.json") or ""


def _raw_snapshot_file() -> str:
    return (
        _env_str("RAW_SNAPSHOT_FILE", f"raw_snapshot_{_report_date()}_runlocal.tar.xz")
        or ""
    )


def _changed_index_out() -> str:
    return _env_str("CHANGED_INDEX_OUT", "cache/index_changed.json") or ""


def _changed_meta_out() -> str:
    return _env_str("CHANGED_META_OUT", "cache/index_changed_meta.json") or ""


def _detail_fetch_state() -> str:
    return _env_str("DETAIL_FETCH_STATE", "cache/detail_fetch_state.json") or ""


def _fast_ttl() -> str:
    return _env_str("FAST_TTL", _env_str("TTL", "1h")) or "1h"


def _can_use_changed_only(changed_index: list[dict], meta: dict) -> bool:
    if not bool(meta.get("fast_path", False)):
        return False
    changed_only_safe_reasons = {"recent_update"}
    for item in changed_index:
        reasons = item.get("change_reasons")
        if not isinstance(reasons, list):
            return False
        if set(reasons) - changed_only_safe_reasons:
            return False
    return True


def task_help() -> int:
    for name in sorted(TASKS):
        print(name)
    return 0


def task_setup() -> int:
    rc = _run("uv", "venv")
    if rc != 0:
        return rc
    return _run("uv", "sync", "--dev")


def task_format() -> int:
    return _run_python_module("black", ".")


def task_lint() -> int:
    return _run_python_module("ruff", "check", ".")


def task_test() -> int:
    return _run_python_module("pytest", "-q")


def task_validate() -> int:
    msdata = _env_str("MSDATA", "msData.json") or "msData.json"
    return _run_python_module("ms_data.validation.validate_msdata", msdata)


def task_validate_strict() -> int:
    msdata = _env_str("MSDATA", "msData.json") or "msData.json"
    return _run_python_module("ms_data.validation.validate_msdata", msdata, "--fail-on-typo")


def task_validate_skills() -> int:
    return _run_python_module("ms_data.validation.validate_skills_data")


def task_update() -> int:
    args = ["-i"]
    input_path = _env_str("INPUT")
    if input_path:
        args.append(input_path)
    return _run_python_module("scripts.update_msdata", *args)


def task_normalize() -> int:
    return _run_python_module("scripts.update_msdata", "-i")


def task_ci() -> int:
    for task_name in (
        "validate-report-contract",
        "validate-generated-reports",
        "validate-official-overrides-schema",
        "verify-snapshot-restore",
        "lint",
        "test",
        "validate-strict",
        "validate-skills",
    ):
        rc = TASKS[task_name]()
        if rc != 0:
            return rc
    return 0


def task_scrape_index() -> int:
    args = [
        "index",
        "--url",
        _env_str("INDEX_URL", INDEX_URL) or INDEX_URL,
        "--out",
        _env_str("INDEX_OUT", "cache/index.json") or "cache/index.json",
        "--ttl",
        _env_str("TTL", "7d") or "7d",
    ]
    if _env_flag("NO_NET"):
        args.append("--no-network")
    if _env_flag("FORCE"):
        args.append("--force")
    return _run_python_module("scripts.scrape_msdata", *args)


def task_scrape_details() -> int:
    args = [
        "details",
        "--in",
        _env_str("DETAILS_IN", "cache/index.json") or "cache/index.json",
        "--out",
        _env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl",
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--ttl",
        _env_str("TTL", "7d") or "7d",
        "--detail-fetch-state-out",
        _detail_fetch_state(),
    ]
    if _env_flag("NO_NET"):
        args.append("--no-network")
    if _env_flag("FORCE"):
        args.append("--force")
    if _env_flag("CHANGED_ONLY"):
        args.append("--changed-only")
    return _run_python_module("scripts.scrape_msdata", *args)


def task_scrape_all() -> int:
    args = [
        "all",
        "--out",
        _env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl",
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--ttl",
        _env_str("TTL", "7d") or "7d",
        "--detail-fetch-state-out",
        _detail_fetch_state(),
    ]
    if _env_flag("NO_NET"):
        args.append("--no-network")
    if _env_flag("FORCE"):
        args.append("--force")
    if _env_flag("CHANGED_ONLY"):
        args.append("--changed-only")
    return _run_python_module("scripts.scrape_msdata", *args)


def task_detect_changed() -> int:
    args = [
        "detect-changed",
        "--in",
        _env_str("INDEX_OUT", "cache/index.json") or "cache/index.json",
        "--out",
        _changed_index_out(),
        "--meta-out",
        _changed_meta_out(),
        "--reports-dir",
        _env_str("REPORTS_DIR", "reports") or "reports",
        "--msdata",
        _env_str("MSDATA", "msData.json") or "msData.json",
        "--freshness-window",
        _env_str("FRESHNESS_WINDOW", "1h") or "1h",
        "--detail-fetch-state",
        _detail_fetch_state(),
        "--stale-detail-days",
        _env_str("STALE_DETAIL_DAYS", "14") or "14",
        "--min-age-coverage",
        str(_env_float("MIN_AGE_COVERAGE", 0.95)),
    ]
    previous_provenance = _env_str("PREVIOUS_PROVENANCE")
    if previous_provenance:
        args.extend(["--previous-provenance", previous_provenance])
    now_value = _env_str("NOW")
    if now_value:
        args.extend(["--now", now_value])
    if _env_flag("FORCE_FULL"):
        args.append("--force-full")
    return _run_python_module("scripts.scrape_msdata", *args)


def task_update_fast() -> int:
    ttl = _fast_ttl()
    rate = str(_env_float("RATE", 2.0))
    limit = str(_env_int("LIMIT", 0))

    rc = _run_python_module(
        "scripts.scrape_msdata",
        "index",
        "--url",
        _env_str("INDEX_URL", INDEX_URL) or INDEX_URL,
        "--out",
        _env_str("INDEX_OUT", "cache/index.json") or "cache/index.json",
        "--ttl",
        ttl,
        *(["--no-network"] if _env_flag("NO_NET") else []),
        *(["--force"] if _env_flag("FORCE") else []),
    )
    if rc != 0:
        return rc

    rc = task_detect_changed()
    if rc != 0:
        return rc

    try:
        changed_index = _load_json_file(Path(_changed_index_out()))
        meta = _load_json_file(Path(_changed_meta_out()))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to read detect-changed outputs: {exc}", file=sys.stderr)
        return 1

    if not isinstance(changed_index, list) or not isinstance(meta, dict):
        print(
            "ERROR: invalid detect-changed output shape "
            f"(index={type(changed_index).__name__}, meta={type(meta).__name__})",
            file=sys.stderr,
        )
        return 1

    candidate_count = int(meta.get("candidate_count", 0))
    if candidate_count <= 0:
        print("update-fast: no candidate pages, skip details/import/validate")
        return 0

    use_changed_only = (
        isinstance(changed_index, list)
        and _can_use_changed_only(changed_index, meta)
        and not _env_flag("NO_NET")
    )
    detail_ttl = "0s" if use_changed_only else ttl

    details_args = [
        "details",
        "--in",
        _changed_index_out(),
        "--out",
        _env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl",
        "--rate",
        rate,
        "--limit",
        limit,
        "--ttl",
        detail_ttl,
        "--detail-fetch-state-out",
        _detail_fetch_state(),
        *(["--no-network"] if _env_flag("NO_NET") else []),
        *(["--force"] if _env_flag("FORCE") else []),
    ]
    if use_changed_only:
        details_args.append("--changed-only")

    rc = _run_python_module(
        "scripts.scrape_msdata",
        *details_args,
    )
    if rc != 0:
        return rc

    details_jsonl = Path(
        _env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl"
    )
    if not details_jsonl.exists() or details_jsonl.stat().st_size == 0:
        print("update-fast: details output is empty, skip import/validate")
        return 0

    rc = task_import_details()
    if rc != 0:
        return rc
    return task_validate_strict()


def task_import_details() -> int:
    details_jsonl = (
        _env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl"
    )
    details_json = (
        _env_str("DETAILS_JSON", "cache/details.json") or "cache/details.json"
    )
    rc = _run_python_module("scripts.jsonl_to_json", details_jsonl, details_json)
    if rc != 0:
        return rc
    return _run_python_module("scripts.update_msdata", "-i", details_json)


def task_labels() -> int:
    args = [
        "labels",
        "--in",
        _env_str("INDEX_OUT", "cache/index.json") or "cache/index.json",
        "--out",
        _env_str("LABELS_OUT", "cache/labels_raw.jsonl") or "cache/labels_raw.jsonl",
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--ttl",
        _env_str("TTL", "7d") or "7d",
    ]
    if _env_flag("NO_NET"):
        args.append("--no-network")
    if _env_flag("FORCE"):
        args.append("--force")
    return _run_python_module("scripts.scrape_msdata", *args)


def task_audit_labels() -> int:
    report_date = _report_date()
    return _run_python_module(
        "scripts.audit_labels",
        "--in",
        _env_str("LABELS_OUT", "cache/labels_raw.jsonl") or "cache/labels_raw.jsonl",
        "--out",
        _env_str("AUDIT_LABELS_OUT", f"reports/label_audit_{report_date}.md") or "",
    )


def task_report_diff() -> int:
    return _run_python_module(
        "scripts.report_msdata_diff",
        "--old",
        _require_env("OLD"),
        "--new",
        _require_env("NEW"),
        "--out",
        _require_env("OUT"),
    )


def task_provenance() -> int:
    report_date = _report_date()
    msdata = _env_str("MSDATA", "msData.json") or "msData.json"
    args = [
        "--date",
        report_date,
        "--index",
        _env_str("INDEX_OUT", "cache/index.json") or "cache/index.json",
        "--details-jsonl",
        _env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl",
        "--details-json",
        _env_str("DETAILS_JSON", "cache/details.json") or "cache/details.json",
        "--msdata",
        msdata,
        "--diff",
        _env_str("DIFF_OUT", f"reports/diff_msdata_{report_date}.md")
        or f"reports/diff_msdata_{report_date}.md",
        "--html-dir",
        _env_str("HTML_DIR", "cache/html") or "cache/html",
        "--out",
        _provenance_out(),
        "--ttl",
        _env_str("TTL", "7d") or "7d",
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--artifact-name",
        _env_str("RAW_ARTIFACT_NAME", f"raw-snapshot-{report_date}-run-local")
        or f"raw-snapshot-{report_date}-run-local",
        "--artifact-retention-days",
        str(_env_int("ARTIFACT_RETENTION_DAYS", 90)),
    ]
    return _run_python_module("scripts.generate_provenance", *args)


def task_snapshot() -> int:
    rc = task_provenance()
    if rc != 0:
        return rc

    report_date = _report_date()
    snapshot_path = Path(_raw_snapshot_file())
    files = [
        Path(_env_str("HTML_DIR", "cache/html") or "cache/html"),
        Path(_env_str("INDEX_OUT", "cache/index.json") or "cache/index.json"),
        Path(_env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl"),
        Path(_env_str("DETAILS_JSON", "cache/details.json") or "cache/details.json"),
        Path(_provenance_out()),
    ]
    diff_path = Path(
        _env_str("DIFF_OUT", f"reports/diff_msdata_{report_date}.md")
        or f"reports/diff_msdata_{report_date}.md"
    )
    if diff_path.exists():
        files.append(diff_path)

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(snapshot_path, "w:xz") as archive:
        for path in files:
            if path.exists():
                archive.add(path, arcname=path.as_posix())
    print(f"snapshot created: {snapshot_path}")
    return 0


def task_restore_snapshot() -> int:
    return _run_python_module(
        "scripts.restore_snapshot",
        "--snapshot",
        _require_env("SNAPSHOT"),
        "--out-dir",
        _env_str("OUT_DIR", ".") or ".",
    )


def task_verify_snapshot_restore() -> int:
    return _run_python_module(
        "ms_data.validation.verify_snapshot_restore",
        "--root",
        _env_str("ROOT", ".") or ".",
    )


def task_audit_index() -> int:
    report_date = _report_date()
    msdata = _env_str("MSDATA", "msData.json") or "msData.json"
    return _run_python_module(
        "scripts.audit_index_vs_msdata",
        "--index",
        _env_str("INDEX_OUT", "cache/index.json") or "cache/index.json",
        "--ms",
        msdata,
        "--out",
        _env_str("AUDIT_INDEX_OUT", f"reports/index_ms_audit_{report_date}.md") or "",
    )


def task_rollback_guard() -> int:
    report_date = _report_date()
    args = [
        "--old",
        _require_env("OLD"),
        "--new",
        _require_env("NEW"),
        "--official-overrides-dir",
        _env_str("OFFICIAL_OVERRIDES_DIR", "data/official_overrides")
        or "data/official_overrides",
        "--out",
        _env_str("ROLLBACK_GUARD_OUT", f"reports/rollback_guard_{report_date}.md")
        or f"reports/rollback_guard_{report_date}.md",
    ]
    if _env_flag("FAIL_ON_PROTECTED_ROLLBACK"):
        args.append("--fail-on-protected-rollback")
    return _run_python_module("scripts.detect_msdata_rollbacks", *args)


def task_audit_official_overrides() -> int:
    report_date = _report_date()
    args = [
        "--overrides-dir",
        _env_str("OFFICIAL_OVERRIDES_DIR", "data/official_overrides")
        or "data/official_overrides",
        "--current",
        _env_str("CURRENT", "msData.json") or "msData.json",
        "--out",
        _env_str(
            "OFFICIAL_OVERRIDES_AUDIT_OUT",
            f"reports/official_overrides_audit_{report_date}.md",
        )
        or f"reports/official_overrides_audit_{report_date}.md",
    ]
    raw = _env_str("RAW")
    before = _env_str("BEFORE")
    if raw:
        args.extend(["--raw", raw])
    if before:
        args.extend(["--before", before])
    today = _env_str("TODAY")
    if today:
        args.extend(["--today", today])
    if _env_flag("FAIL_ON_PROTECTED_ROLLBACK"):
        args.append("--fail-on-protected-rollback")
    if _env_flag("FAIL_ON_REMOVE_DUE"):
        args.append("--fail-on-remove-due")
    return _run_python_module("scripts.audit_official_overrides", *args)


def task_validate_official_overrides_schema() -> int:
    return _run_python_module(
        "ms_data.validation.validate_official_overrides_schema",
        "--overrides-dir",
        _env_str("OFFICIAL_OVERRIDES_DIR", "data/official_overrides")
        or "data/official_overrides",
        "--schema",
        _env_str("OFFICIAL_OVERRIDES_SCHEMA", "schema/official_overrides.schema.json")
        or "schema/official_overrides.schema.json",
    )


def task_atwiki_quality_report() -> int:
    report_date = _report_date()
    return _run_python_module(
        "scripts.build_atwiki_quality_report",
        "--report-date",
        report_date,
        "--source-run-id",
        _env_str("GITHUB_RUN_ID", "local") or "local",
        "--index",
        _env_str("INDEX_OUT", "cache/index.json") or "cache/index.json",
        "--changed-index",
        _env_str("CHANGED_INDEX_OUT", "cache/index_changed.json")
        or "cache/index_changed.json",
        "--changed-meta",
        _env_str("CHANGED_META_OUT", "cache/index_changed_meta.json")
        or "cache/index_changed_meta.json",
        "--detail-fetch-state",
        _env_str("DETAIL_FETCH_STATE", "cache/detail_fetch_state.json")
        or "cache/detail_fetch_state.json",
        "--details-json",
        _env_str("DETAILS_JSON", "cache/details.json") or "cache/details.json",
        "--details-jsonl",
        _env_str("DETAILS_OUT", "cache/details.jsonl") or "cache/details.jsonl",
        "--before-msdata",
        _env_str("BEFORE", "msData.before.json") or "msData.before.json",
        "--current-msdata",
        _env_str("MSDATA", "msData.json") or "msData.json",
        "--out",
        _env_str("ATWIKI_QUALITY_OUT", f"reports/atwiki_quality_{report_date}.json")
        or f"reports/atwiki_quality_{report_date}.json",
    )


def task_skills() -> int:
    args = [
        "all",
        "--out",
        _env_str("SKILLS_OUT", "cache/skills.json") or "cache/skills.json",
        "--ttl",
        _env_str("TTL", "7d") or "7d",
    ]
    if _env_flag("NO_NET"):
        args.append("--no-network")
    if _env_flag("FORCE"):
        args.append("--force")
    return _run_python_module("scripts.extract_skills", *args)


def task_skills_table() -> int:
    args = [
        "table",
        "--out",
        _env_str("SKILLS_TABLE_OUT", "cache/skills_table.json")
        or "cache/skills_table.json",
        "--ttl",
        _env_str("TTL", "7d") or "7d",
    ]
    if _env_flag("NO_NET"):
        args.append("--no-network")
    if _env_flag("FORCE"):
        args.append("--force")
    return _run_python_module("scripts.extract_skills", *args)


def task_owners_table() -> int:
    args = [
        "owners-table",
        "--out",
        _env_str("OWNERS_TABLE_OUT", "cache/owners_table.json")
        or "cache/owners_table.json",
        "--ttl",
        _env_str("TTL", "7d") or "7d",
    ]
    if _env_flag("NO_NET"):
        args.append("--no-network")
    if _env_flag("FORCE"):
        args.append("--force")
    return _run_python_module("scripts.extract_skills", *args)


def task_build_skills() -> int:
    return _run_python_module(
        "scripts.build_skills",
        "--in",
        _env_str("SKILLS_OUT", "cache/skills.json") or "cache/skills.json",
        "--out-catalog",
        _env_str("SKILLS_CATALOG_OUT", "data/skills_catalog.json")
        or "data/skills_catalog.json",
        "--out-owners",
        _env_str("SKILL_OWNERS_OUT", "data/skill_owners.json")
        or "data/skill_owners.json",
    )


def task_build_param_skills() -> int:
    return _run_python_module(
        "scripts.build_param_skills",
        "--in",
        _env_str("SKILLS_TABLE_OUT", "cache/skills_table.json")
        or "cache/skills_table.json",
        "--out",
        _env_str("SKILLS_PARAMS_OUT", "data/skills_params.json")
        or "data/skills_params.json",
        "--policy",
        _env_str("SKILLS_POLICY", "data/skills_policy.json")
        or "data/skills_policy.json",
        "--audit-out",
        _env_str("SKILLS_PARAMS_AUDIT_OUT", "reports/skills_params_audit.json")
        or "reports/skills_params_audit.json",
    )


def task_build_owners_flat() -> int:
    return _run_python_module(
        "scripts.build_owners_flat",
        "--in",
        _env_str("OWNERS_TABLE_OUT", "cache/owners_table.json")
        or "cache/owners_table.json",
        "--msdata",
        _env_str("MSDATA", "msData.json") or "msData.json",
        "--policy",
        _env_str("SKILLS_POLICY", "data/skills_policy.json")
        or "data/skills_policy.json",
        "--out",
        _env_str("SKILL_OWNERS_FLAT_OUT", "data/skill_owners_flat.json")
        or "data/skill_owners_flat.json",
        "--audit-out",
        _env_str("OWNERS_FLAT_AUDIT_OUT", "reports/owners_flat_audit.json")
        or "reports/owners_flat_audit.json",
    )


def task_audit_skills() -> int:
    return _run_python_module(
        "scripts.audit_skills",
        "--owners",
        _env_str("SKILL_OWNERS_OUT", "data/skill_owners.json")
        or "data/skill_owners.json",
        "--msdata",
        _env_str("MSDATA", "msData.json") or "msData.json",
    )


def task_preview_params() -> int:
    return _run_python_module(
        "scripts.preview_params",
        "--msdata",
        _env_str("MSDATA", "msData.json") or "msData.json",
        "--owners",
        _env_str("SKILL_OWNERS_FLAT_OUT", "data/skill_owners_flat.json")
        or "data/skill_owners_flat.json",
        "--params",
        _env_str("SKILLS_PARAMS_OUT", "data/skills_params.json")
        or "data/skills_params.json",
        "--out",
        _env_str("PREVIEW_PARAMS_OUT", "derived/ms_params_preview.json")
        or "derived/ms_params_preview.json",
    )


def task_validate_report_contract() -> int:
    mode = _env_str("MODE", "ci") or "ci"
    args = [
        "--mode",
        mode,
        "--manifest",
        _env_str("REPORTS_MANIFEST", "reports_manifest.yml") or "reports_manifest.yml",
        "--reports-dir",
        _env_str("REPORTS_DIR", "reports") or "reports",
        "--report-date",
        _env_str("REPORT_DATE", "") or "",
        "--source-run-id",
        _env_str("SOURCE_RUN_ID", "") or "",
        "--head-ref",
        _env_str("HEAD_REF", "") or "",
        "--diff-path",
        _env_str("DIFF_PATH", "") or "",
        "--provenance-path",
        _env_str("PROVENANCE_PATH", "") or "",
        "--artifact-name",
        _env_str("ARTIFACT_NAME", "") or "",
        "--snapshot-file",
        _env_str("SNAPSHOT_FILE", "") or "",
        "--release-tag",
        _env_str("RELEASE_TAG", "") or "",
    ]
    return _run_python_module("ms_data.validation.validate_report_contract", *args)


def task_validate_generated_reports() -> int:
    return _run_python_module(
        "ms_data.validation.validate_generated_reports",
        "--reports-dir",
        _env_str("REPORTS_DIR", "reports") or "reports",
        "--schema-dir",
        _env_str("REPORT_SCHEMA_DIR", "schema/reports") or "schema/reports",
    )


TASKS: dict[str, Callable[[], int]] = {
    "help": task_help,
    "setup": task_setup,
    "format": task_format,
    "lint": task_lint,
    "test": task_test,
    "validate": task_validate,
    "validate-strict": task_validate_strict,
    "validate-skills": task_validate_skills,
    "update": task_update,
    "normalize": task_normalize,
    "ci": task_ci,
    "scrape-index": task_scrape_index,
    "scrape-details": task_scrape_details,
    "scrape-all": task_scrape_all,
    "detect-changed": task_detect_changed,
    "update-fast": task_update_fast,
    "import-details": task_import_details,
    "labels": task_labels,
    "audit-labels": task_audit_labels,
    "report-diff": task_report_diff,
    "provenance": task_provenance,
    "snapshot": task_snapshot,
    "restore-snapshot": task_restore_snapshot,
    "verify-snapshot-restore": task_verify_snapshot_restore,
    "audit-index": task_audit_index,
    "rollback-guard": task_rollback_guard,
    "audit-official-overrides": task_audit_official_overrides,
    "validate-official-overrides-schema": task_validate_official_overrides_schema,
    "atwiki-quality-report": task_atwiki_quality_report,
    "skills": task_skills,
    "skills-table": task_skills_table,
    "owners-table": task_owners_table,
    "build-skills": task_build_skills,
    "build-param-skills": task_build_param_skills,
    "build-owners-flat": task_build_owners_flat,
    "audit-skills": task_audit_skills,
    "preview-params": task_preview_params,
    "validate-report-contract": task_validate_report_contract,
    "validate-generated-reports": task_validate_generated_reports,
}


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args or args[0] in {"-h", "--help"}:
        return task_help()

    target = args[0]
    if target not in TASKS:
        print(f"ERROR: unknown target: {target}", file=sys.stderr)
        print("Available targets:", file=sys.stderr)
        for name in sorted(TASKS):
            print(f"  - {name}", file=sys.stderr)
        return 2

    for extra in args[1:]:
        if "=" not in extra:
            print(f"ERROR: unsupported argument: {extra}", file=sys.stderr)
            return 2
        key, value = extra.split("=", 1)
        os.environ[key] = value

    return TASKS[target]()


if __name__ == "__main__":
    raise SystemExit(main())
