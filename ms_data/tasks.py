#!/usr/bin/env python3
"""タスクランナー: `uv run python -m ms_data.tasks <target>` の実装。

各 task_* 関数が1ターゲットに対応し、環境変数で入出力パスや動作を
上書きできる（例: `MSDATA=path/to.json uv run python -m ms_data.tasks validate`）。
ターゲット一覧は TASKS（または `tasks help`）を参照。
実処理は各モジュールにあり、ここではサブプロセスとして起動するだけ。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

from ms_data.core.env import env_flag as _env_flag
from ms_data.core.env import env_float as _env_float
from ms_data.core.env import env_int as _env_int
from ms_data.core.env import env_str as _env_str
from ms_data.core.json_io import load_json as _load_json_file


INDEX_URL = "https://w.atwiki.jp/battle-operation2/pages/377.html"

# 既定パス・既定値（対応する環境変数で上書き可能）
DEFAULT_MSDATA = "msData.json"  # MSDATA
DEFAULT_TTL = "7d"  # TTL
DEFAULT_INDEX_OUT = "cache/index.json"  # INDEX_OUT
DEFAULT_DETAILS_OUT = "cache/details.jsonl"  # DETAILS_OUT
DEFAULT_DETAILS_JSON = "cache/details.json"  # DETAILS_JSON
DEFAULT_HTML_DIR = "cache/html"  # HTML_DIR
DEFAULT_REPORTS_DIR = "reports"  # REPORTS_DIR
DEFAULT_LABELS_OUT = "cache/labels_raw.jsonl"  # LABELS_OUT
DEFAULT_OVERRIDES_DIR = "data/official_overrides"  # OFFICIAL_OVERRIDES_DIR
DEFAULT_SKILLS_OUT = "cache/skills.json"  # SKILLS_OUT
DEFAULT_SKILLS_TABLE_OUT = "cache/skills_table.json"  # SKILLS_TABLE_OUT
DEFAULT_OWNERS_TABLE_OUT = "cache/owners_table.json"  # OWNERS_TABLE_OUT
DEFAULT_SKILLS_POLICY = "data/skills_policy.json"  # SKILLS_POLICY
DEFAULT_SKILL_OWNERS_OUT = "data/skill_owners.json"  # SKILL_OWNERS_OUT
DEFAULT_SKILL_OWNERS_FLAT_OUT = "data/skill_owners_flat.json"  # SKILL_OWNERS_FLAT_OUT
DEFAULT_SKILLS_PARAMS_OUT = "data/skills_params.json"  # SKILLS_PARAMS_OUT


# ---------------------------------------------------------------------------
# 共通ヘルパー
# ---------------------------------------------------------------------------


def _env(name: str, default: str) -> str:
    """default 付き env_str の str 確定版（戻り値が None にならない）。"""
    return _env_str(name, default) or default


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _run(*args: str) -> int:
    completed = subprocess.run(args, check=False)
    return int(completed.returncode)


def _run_python_module(module: str, *args: str) -> int:
    return _run(sys.executable, "-m", module, *args)


def _require_env(name: str) -> str:
    """必須の環境変数を取得する（未設定なら即終了）。"""
    value = _env_str(name)
    if value is None:
        raise SystemExit(f"ERROR: environment variable {name} is required")
    return value


def _network_flags() -> list[str]:
    """NO_NET / FORCE 環境変数をスクレイパー共通の CLI フラグに変換する。"""
    flags: list[str] = []
    if _env_flag("NO_NET"):
        flags.append("--no-network")
    if _env_flag("FORCE"):
        flags.append("--force")
    return flags


def _report_date() -> str:
    return _env("REPORT_DATE", _today())


def _provenance_out() -> str:
    return _env("PROVENANCE_OUT", f"reports/provenance_{_report_date()}.json")


def _raw_snapshot_file() -> str:
    return _env("RAW_SNAPSHOT_FILE", f"raw_snapshot_{_report_date()}_runlocal.tar.xz")


def _changed_index_out() -> str:
    return _env("CHANGED_INDEX_OUT", "cache/index_changed.json")


def _changed_meta_out() -> str:
    return _env("CHANGED_META_OUT", "cache/index_changed_meta.json")


def _detail_fetch_state() -> str:
    return _env("DETAIL_FETCH_STATE", "cache/detail_fetch_state.json")


def _fast_ttl() -> str:
    return _env("FAST_TTL", _env("TTL", "1h"))


def _can_use_changed_only(changed_index: list[dict], meta: dict) -> bool:
    """detect-changed の結果が --changed-only での詳細取得に安全かを判定する。

    fast_path でない、または「更新があった」以外の理由（新規・コスト変更等）が
    混ざっている場合は、セマンティック変化なしでもレコード再生成が必要なため
    changed-only は使えない。
    """
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


# ---------------------------------------------------------------------------
# 開発ツール・品質チェック
# ---------------------------------------------------------------------------


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


def task_test_cov() -> int:
    # 計測対象・レポート形式は pyproject.toml の [tool.coverage.*] に一元管理
    return _run_python_module("pytest", "-q", "--cov")


def task_ci() -> int:
    """品質チェック一括（lint / カバレッジ付きテスト / 各種検証）。"""
    for task_name in (
        "validate-report-contract",
        "validate-generated-reports",
        "validate-official-overrides-schema",
        "verify-snapshot-restore",
        "lint",
        "test-cov",
        "validate-strict",
        "validate-skills",
    ):
        rc = TASKS[task_name]()
        if rc != 0:
            return rc
    return 0


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------


def task_validate() -> int:
    return _run_python_module(
        "ms_data.validation.validate_msdata", _env("MSDATA", DEFAULT_MSDATA)
    )


def task_validate_strict() -> int:
    return _run_python_module(
        "ms_data.validation.validate_msdata",
        _env("MSDATA", DEFAULT_MSDATA),
        "--fail-on-typo",
    )


def task_validate_skills() -> int:
    return _run_python_module("ms_data.validation.validate_skills_data")


def task_validate_official_overrides_schema() -> int:
    return _run_python_module(
        "ms_data.validation.validate_official_overrides_schema",
        "--overrides-dir",
        _env("OFFICIAL_OVERRIDES_DIR", DEFAULT_OVERRIDES_DIR),
        "--schema",
        _env("OFFICIAL_OVERRIDES_SCHEMA", "schema/official_overrides.schema.json"),
    )


def task_validate_report_contract() -> int:
    return _run_python_module(
        "ms_data.validation.validate_report_contract",
        "--mode",
        _env("MODE", "ci"),
        "--manifest",
        _env("REPORTS_MANIFEST", "reports_manifest.yml"),
        "--reports-dir",
        _env("REPORTS_DIR", DEFAULT_REPORTS_DIR),
        "--report-date",
        _env("REPORT_DATE", ""),
        "--source-run-id",
        _env("SOURCE_RUN_ID", ""),
        "--head-ref",
        _env("HEAD_REF", ""),
        "--diff-path",
        _env("DIFF_PATH", ""),
        "--provenance-path",
        _env("PROVENANCE_PATH", ""),
        "--artifact-name",
        _env("ARTIFACT_NAME", ""),
        "--snapshot-file",
        _env("SNAPSHOT_FILE", ""),
        "--release-tag",
        _env("RELEASE_TAG", ""),
    )


def task_validate_generated_reports() -> int:
    return _run_python_module(
        "ms_data.validation.validate_generated_reports",
        "--reports-dir",
        _env("REPORTS_DIR", DEFAULT_REPORTS_DIR),
        "--schema-dir",
        _env("REPORT_SCHEMA_DIR", "schema/reports"),
    )


# ---------------------------------------------------------------------------
# スクレイピング・差分検出
# ---------------------------------------------------------------------------


def task_scrape_index() -> int:
    args = [
        "index",
        "--url",
        _env("INDEX_URL", INDEX_URL),
        "--out",
        _env("INDEX_OUT", DEFAULT_INDEX_OUT),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        *_network_flags(),
    ]
    return _run_python_module("ms_data.scraping.scrape_msdata", *args)


def task_scrape_details() -> int:
    args = [
        "details",
        "--in",
        _env("DETAILS_IN", DEFAULT_INDEX_OUT),
        "--out",
        _env("DETAILS_OUT", DEFAULT_DETAILS_OUT),
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        "--detail-fetch-state-out",
        _detail_fetch_state(),
        *_network_flags(),
    ]
    if _env_flag("CHANGED_ONLY"):
        args.append("--changed-only")
    return _run_python_module("ms_data.scraping.scrape_msdata", *args)


def task_scrape_all() -> int:
    args = [
        "all",
        "--out",
        _env("DETAILS_OUT", DEFAULT_DETAILS_OUT),
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        "--detail-fetch-state-out",
        _detail_fetch_state(),
        *_network_flags(),
    ]
    if _env_flag("CHANGED_ONLY"):
        args.append("--changed-only")
    return _run_python_module("ms_data.scraping.scrape_msdata", *args)


def task_detect_changed() -> int:
    args = [
        "detect-changed",
        "--in",
        _env("INDEX_OUT", DEFAULT_INDEX_OUT),
        "--out",
        _changed_index_out(),
        "--meta-out",
        _changed_meta_out(),
        "--reports-dir",
        _env("REPORTS_DIR", DEFAULT_REPORTS_DIR),
        "--msdata",
        _env("MSDATA", DEFAULT_MSDATA),
        "--freshness-window",
        _env("FRESHNESS_WINDOW", "1h"),
        "--detail-fetch-state",
        _detail_fetch_state(),
        "--stale-detail-days",
        _env("STALE_DETAIL_DAYS", "14"),
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
    if _env_flag("REVALIDATE"):
        args.append("--revalidate")
    return _run_python_module("ms_data.scraping.scrape_msdata", *args)


def task_update_fast() -> int:
    """差分のみ取得する高速更新（毎日の自動更新が使う一気通貫フロー）。

    流れ:
    1. index 取得（FAST_TTL、既定 1h）
    2. detect-changed で再取得候補を選定 → 候補ゼロなら終了
    3. 候補理由がすべて recent_update なら --changed-only + TTL 0s で
       詳細取得（セマンティック変化のないページはパースをスキップ）。
       それ以外の理由が混ざる場合は通常取得
    4. 取得結果があれば import-details → validate-strict
    """
    ttl = _fast_ttl()
    rate = str(_env_float("RATE", 2.0))
    limit = str(_env_int("LIMIT", 0))

    rc = _run_python_module(
        "ms_data.scraping.scrape_msdata",
        "index",
        "--url",
        _env("INDEX_URL", INDEX_URL),
        "--out",
        _env("INDEX_OUT", DEFAULT_INDEX_OUT),
        "--ttl",
        ttl,
        *_network_flags(),
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
        _env("DETAILS_OUT", DEFAULT_DETAILS_OUT),
        "--rate",
        rate,
        "--limit",
        limit,
        "--ttl",
        detail_ttl,
        "--detail-fetch-state-out",
        _detail_fetch_state(),
        *_network_flags(),
    ]
    if use_changed_only:
        details_args.append("--changed-only")

    rc = _run_python_module(
        "ms_data.scraping.scrape_msdata",
        *details_args,
    )
    if rc != 0:
        return rc

    details_jsonl = Path(_env("DETAILS_OUT", DEFAULT_DETAILS_OUT))
    if not details_jsonl.exists() or details_jsonl.stat().st_size == 0:
        print("update-fast: details output is empty, skip import/validate")
        return 0

    rc = task_import_details()
    if rc != 0:
        return rc
    return task_validate_strict()


def task_labels() -> int:
    args = [
        "labels",
        "--in",
        _env("INDEX_OUT", DEFAULT_INDEX_OUT),
        "--out",
        _env("LABELS_OUT", DEFAULT_LABELS_OUT),
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        *_network_flags(),
    ]
    return _run_python_module("ms_data.scraping.scrape_msdata", *args)


# ---------------------------------------------------------------------------
# 取込・正規化
# ---------------------------------------------------------------------------


def task_update() -> int:
    args = ["-i"]
    input_path = _env_str("INPUT")
    if input_path:
        args.append(input_path)
    return _run_python_module("ms_data.pipeline.update_msdata", *args)


def task_normalize() -> int:
    return _run_python_module("ms_data.pipeline.update_msdata", "-i")


def task_import_details() -> int:
    """details.jsonl → details.json 変換 → msData.json へマージ。"""
    details_jsonl = _env("DETAILS_OUT", DEFAULT_DETAILS_OUT)
    details_json = _env("DETAILS_JSON", DEFAULT_DETAILS_JSON)
    rc = _run_python_module(
        "ms_data.pipeline.jsonl_to_json", details_jsonl, details_json
    )
    if rc != 0:
        return rc
    return _run_python_module("ms_data.pipeline.update_msdata", "-i", details_json)


# ---------------------------------------------------------------------------
# レポート・プロビナンス・スナップショット
# ---------------------------------------------------------------------------


def task_report_diff() -> int:
    return _run_python_module(
        "ms_data.reporting.report_msdata_diff",
        "--old",
        _require_env("OLD"),
        "--new",
        _require_env("NEW"),
        "--out",
        _require_env("OUT"),
    )


def task_provenance() -> int:
    report_date = _report_date()
    args = [
        "--date",
        report_date,
        "--index",
        _env("INDEX_OUT", DEFAULT_INDEX_OUT),
        "--details-jsonl",
        _env("DETAILS_OUT", DEFAULT_DETAILS_OUT),
        "--details-json",
        _env("DETAILS_JSON", DEFAULT_DETAILS_JSON),
        "--msdata",
        _env("MSDATA", DEFAULT_MSDATA),
        "--diff",
        _env("DIFF_OUT", f"reports/diff_msdata_{report_date}.md"),
        "--html-dir",
        _env("HTML_DIR", DEFAULT_HTML_DIR),
        "--out",
        _provenance_out(),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        "--rate",
        str(_env_float("RATE", 2.0)),
        "--limit",
        str(_env_int("LIMIT", 0)),
        "--artifact-name",
        _env("RAW_ARTIFACT_NAME", f"raw-snapshot-{report_date}-run-local"),
        "--artifact-retention-days",
        str(_env_int("ARTIFACT_RETENTION_DAYS", 90)),
    ]
    return _run_python_module("ms_data.pipeline.generate_provenance", *args)


def task_snapshot() -> int:
    """プロビナンス生成後、取得物一式を tar.xz にアーカイブする。"""
    rc = task_provenance()
    if rc != 0:
        return rc

    report_date = _report_date()
    snapshot_path = Path(_raw_snapshot_file())
    files = [
        Path(_env("HTML_DIR", DEFAULT_HTML_DIR)),
        Path(_env("INDEX_OUT", DEFAULT_INDEX_OUT)),
        Path(_env("DETAILS_OUT", DEFAULT_DETAILS_OUT)),
        Path(_env("DETAILS_JSON", DEFAULT_DETAILS_JSON)),
        Path(_provenance_out()),
    ]
    diff_path = Path(_env("DIFF_OUT", f"reports/diff_msdata_{report_date}.md"))
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
        "ms_data.pipeline.restore_snapshot",
        "--snapshot",
        _require_env("SNAPSHOT"),
        "--out-dir",
        _env("OUT_DIR", "."),
    )


def task_verify_snapshot_restore() -> int:
    return _run_python_module(
        "ms_data.validation.verify_snapshot_restore",
        "--root",
        _env("ROOT", "."),
    )


def task_atwiki_quality_report() -> int:
    report_date = _report_date()
    return _run_python_module(
        "ms_data.reporting.build_atwiki_quality_report",
        "--report-date",
        report_date,
        "--source-run-id",
        _env("GITHUB_RUN_ID", "local"),
        "--index",
        _env("INDEX_OUT", DEFAULT_INDEX_OUT),
        "--changed-index",
        _changed_index_out(),
        "--changed-meta",
        _changed_meta_out(),
        "--detail-fetch-state",
        _detail_fetch_state(),
        "--details-json",
        _env("DETAILS_JSON", DEFAULT_DETAILS_JSON),
        "--details-jsonl",
        _env("DETAILS_OUT", DEFAULT_DETAILS_OUT),
        "--before-msdata",
        _env("BEFORE", "msData.before.json"),
        "--current-msdata",
        _env("MSDATA", DEFAULT_MSDATA),
        "--out",
        _env("ATWIKI_QUALITY_OUT", f"reports/atwiki_quality_{report_date}.json"),
    )


# ---------------------------------------------------------------------------
# 監査
# ---------------------------------------------------------------------------


def task_audit_labels() -> int:
    report_date = _report_date()
    return _run_python_module(
        "ms_data.audit.audit_labels",
        "--in",
        _env("LABELS_OUT", DEFAULT_LABELS_OUT),
        "--out",
        _env("AUDIT_LABELS_OUT", f"reports/label_audit_{report_date}.md"),
    )


def task_audit_index() -> int:
    report_date = _report_date()
    return _run_python_module(
        "ms_data.audit.audit_index_vs_msdata",
        "--index",
        _env("INDEX_OUT", DEFAULT_INDEX_OUT),
        "--ms",
        _env("MSDATA", DEFAULT_MSDATA),
        "--out",
        _env("AUDIT_INDEX_OUT", f"reports/index_ms_audit_{report_date}.md"),
    )


def task_rollback_guard() -> int:
    report_date = _report_date()
    args = [
        "--old",
        _require_env("OLD"),
        "--new",
        _require_env("NEW"),
        "--official-overrides-dir",
        _env("OFFICIAL_OVERRIDES_DIR", DEFAULT_OVERRIDES_DIR),
        "--out",
        _env("ROLLBACK_GUARD_OUT", f"reports/rollback_guard_{report_date}.md"),
    ]
    if _env_flag("FAIL_ON_PROTECTED_ROLLBACK"):
        args.append("--fail-on-protected-rollback")
    return _run_python_module("ms_data.audit.detect_msdata_rollbacks", *args)


def task_audit_official_overrides() -> int:
    report_date = _report_date()
    args = [
        "--overrides-dir",
        _env("OFFICIAL_OVERRIDES_DIR", DEFAULT_OVERRIDES_DIR),
        "--current",
        _env("CURRENT", DEFAULT_MSDATA),
        "--out",
        _env(
            "OFFICIAL_OVERRIDES_AUDIT_OUT",
            f"reports/official_overrides_audit_{report_date}.md",
        ),
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
    return _run_python_module("ms_data.audit.audit_official_overrides", *args)


def task_audit_field_completeness() -> int:
    report_date = _report_date()
    reports_dir = _env("REPORTS_DIR", DEFAULT_REPORTS_DIR)
    args = [
        "--msdata",
        _env("MSDATA", DEFAULT_MSDATA),
        "--allowlist",
        _env(
            "FIELD_COMPLETENESS_ALLOWLIST",
            "data/field_completeness_allowlist.json",
        ),
        "--out",
        f"{reports_dir}/field_completeness_{report_date}.md",
    ]
    today = _env_str("TODAY")
    if today:
        args.extend(["--today", today])
    if _env_flag("FAIL_ON_FINDINGS"):
        args.append("--fail-on-findings")
    return _run_python_module("ms_data.audit.audit_field_completeness", *args)


def task_audit_skills() -> int:
    return _run_python_module(
        "ms_data.audit.audit_skills",
        "--owners",
        _env("SKILL_OWNERS_OUT", DEFAULT_SKILL_OWNERS_OUT),
        "--msdata",
        _env("MSDATA", DEFAULT_MSDATA),
    )


# ---------------------------------------------------------------------------
# スキルデータ
# ---------------------------------------------------------------------------


def task_skills() -> int:
    args = [
        "all",
        "--out",
        _env("SKILLS_OUT", DEFAULT_SKILLS_OUT),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        *_network_flags(),
    ]
    return _run_python_module("ms_data.scraping.extract_skills", *args)


def task_skills_table() -> int:
    args = [
        "table",
        "--out",
        _env("SKILLS_TABLE_OUT", DEFAULT_SKILLS_TABLE_OUT),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        *_network_flags(),
    ]
    return _run_python_module("ms_data.scraping.extract_skills", *args)


def task_owners_table() -> int:
    args = [
        "owners-table",
        "--out",
        _env("OWNERS_TABLE_OUT", DEFAULT_OWNERS_TABLE_OUT),
        "--ttl",
        _env("TTL", DEFAULT_TTL),
        *_network_flags(),
    ]
    return _run_python_module("ms_data.scraping.extract_skills", *args)


def task_build_skills() -> int:
    return _run_python_module(
        "ms_data.skills.build_skills",
        "--in",
        _env("SKILLS_OUT", DEFAULT_SKILLS_OUT),
        "--out-catalog",
        _env("SKILLS_CATALOG_OUT", "data/skills_catalog.json"),
        "--out-owners",
        _env("SKILL_OWNERS_OUT", DEFAULT_SKILL_OWNERS_OUT),
    )


def task_build_param_skills() -> int:
    return _run_python_module(
        "ms_data.skills.build_param_skills",
        "--in",
        _env("SKILLS_TABLE_OUT", DEFAULT_SKILLS_TABLE_OUT),
        "--out",
        _env("SKILLS_PARAMS_OUT", DEFAULT_SKILLS_PARAMS_OUT),
        "--policy",
        _env("SKILLS_POLICY", DEFAULT_SKILLS_POLICY),
        "--audit-out",
        _env("SKILLS_PARAMS_AUDIT_OUT", "reports/skills_params_audit.json"),
    )


def task_build_owners_flat() -> int:
    return _run_python_module(
        "ms_data.skills.build_owners_flat",
        "--in",
        _env("OWNERS_TABLE_OUT", DEFAULT_OWNERS_TABLE_OUT),
        "--msdata",
        _env("MSDATA", DEFAULT_MSDATA),
        "--policy",
        _env("SKILLS_POLICY", DEFAULT_SKILLS_POLICY),
        "--out",
        _env("SKILL_OWNERS_FLAT_OUT", DEFAULT_SKILL_OWNERS_FLAT_OUT),
        "--audit-out",
        _env("OWNERS_FLAT_AUDIT_OUT", "reports/owners_flat_audit.json"),
    )


def task_preview_params() -> int:
    return _run_python_module(
        "ms_data.skills.preview_params",
        "--msdata",
        _env("MSDATA", DEFAULT_MSDATA),
        "--owners",
        _env("SKILL_OWNERS_FLAT_OUT", DEFAULT_SKILL_OWNERS_FLAT_OUT),
        "--params",
        _env("SKILLS_PARAMS_OUT", DEFAULT_SKILLS_PARAMS_OUT),
        "--out",
        _env("PREVIEW_PARAMS_OUT", "derived/ms_params_preview.json"),
    )


TASKS: dict[str, Callable[[], int]] = {
    "help": task_help,
    "setup": task_setup,
    "format": task_format,
    "lint": task_lint,
    "test": task_test,
    "test-cov": task_test_cov,
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
    "audit-field-completeness": task_audit_field_completeness,
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
