#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


DATE_RE = re.compile(r"^\d{8}$")

# reports_manifest.schema.json の entry.type と一致させる
ALLOWED_MANIFEST_ENTRY_TYPES = frozenset({"generated", "manual"})


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: failed to load manifest {path}: {exc}") from exc


def _error(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def _build_allowed_patterns(
    manifest: dict[str, Any], include_types: set[str]
) -> list[str]:
    patterns: list[str] = []
    for entry in manifest.get("entries", []):
        if entry.get("type") not in include_types:
            continue
        patterns.extend(entry.get("path_patterns", []))
    return patterns


def _matches_any(path: str, patterns: list[str]) -> bool:
    posix_path = PurePosixPath(path)
    return any(posix_path.match(pattern) for pattern in patterns)


def _expected_from_manifest(
    manifest: dict[str, Any], report_date: str, source_run_id: str
) -> dict[str, str]:
    naming = manifest["naming"]
    return {
        "head_ref": naming["head_ref_pattern"].format(report_date=report_date),
        "diff": naming["diff_pattern"].format(report_date=report_date),
        "provenance": naming["provenance_pattern"].format(report_date=report_date),
        "artifact": naming["artifact_pattern"].format(
            report_date=report_date, source_run_id=source_run_id
        ),
        "snapshot": naming["snapshot_pattern"].format(
            report_date=report_date, source_run_id=source_run_id
        ),
        "release_tag": naming["release_tag_pattern"].format(
            report_date=report_date, source_run_id=source_run_id
        ),
    }


def _validate_manifest_shape(manifest: dict[str, Any]) -> int:
    rc = 0
    required_top = {"version", "compatibility", "naming", "entries"}
    missing = required_top - set(manifest.keys())
    if missing:
        _error(f"manifest missing keys: {sorted(missing)}")
        rc = 1
    entries = manifest.get("entries", [])
    if not isinstance(entries, list) or not entries:
        _error("manifest.entries must be a non-empty list")
        rc = 1
    ids: set[str] = set()
    for entry in entries:
        entry_id = entry.get("id")
        if not entry_id:
            _error("entry.id is required")
            rc = 1
            continue
        if entry_id in ids:
            _error(f"entry.id duplicated: {entry_id}")
            rc = 1
        ids.add(entry_id)
        etype = entry.get("type")
        if etype not in ALLOWED_MANIFEST_ENTRY_TYPES:
            _error(
                f"entry.type must be one of {sorted(ALLOWED_MANIFEST_ENTRY_TYPES)}: "
                f"id={entry_id!r} type={etype!r}"
            )
            rc = 1
    return rc


def _validate_date(value: str | None, key: str) -> int:
    if not value:
        _error(f"{key} is required")
        return 1
    if not DATE_RE.match(value):
        _error(f"{key} must be YYYYMMDD: {value}")
        return 1
    return 0


def _validate_data_update(args: argparse.Namespace, manifest: dict[str, Any]) -> int:
    rc = _validate_date(args.report_date, "report_date")
    if not args.source_run_id:
        _error("source_run_id is required")
        rc = 1
    if rc != 0:
        return rc

    expected = _expected_from_manifest(manifest, args.report_date, args.source_run_id)
    checks = {
        "head_ref": args.head_ref,
        "diff": args.diff_path,
        "provenance": args.provenance_path,
        "artifact": args.artifact_name,
        "snapshot": args.snapshot_file,
        "release_tag": args.release_tag,
    }
    for key, actual in checks.items():
        if not actual:
            _error(f"{key} is required")
            rc = 1
            continue
        if actual != expected[key]:
            _error(f"{key} mismatch: expected={expected[key]} actual={actual}")
            rc = 1
    return rc


def _validate_auto_review(args: argparse.Namespace, manifest: dict[str, Any]) -> int:
    rc = _validate_date(args.report_date, "report_date")
    if not args.head_ref:
        _error("head_ref is required")
        return 1
    expected_head = manifest["naming"]["head_ref_pattern"].format(
        report_date=args.report_date
    )
    if args.head_ref != expected_head:
        _error(f"head_ref mismatch: expected={expected_head} actual={args.head_ref}")
        rc = 1
    return rc


def _validate_post_merge(args: argparse.Namespace, manifest: dict[str, Any]) -> int:
    return _validate_data_update(args, manifest)


def _validate_ci(args: argparse.Namespace, manifest: dict[str, Any]) -> int:
    reports_dir = Path(args.reports_dir)
    if not reports_dir.exists():
        return 0
    generated_patterns = _build_allowed_patterns(manifest, {"generated"})
    manual_patterns = _build_allowed_patterns(manifest, {"manual"})
    rc = 0
    for path in reports_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.as_posix()
        if _matches_any(rel, generated_patterns):
            continue
        if _matches_any(rel, manual_patterns):
            continue
        _error(f"report file not listed in manifest allowlist: {rel}")
        rc = 1
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default="reports_manifest.yml")
    ap.add_argument(
        "--mode",
        choices=("ci", "data-update", "post-merge", "auto-review"),
        required=True,
    )
    ap.add_argument("--reports-dir", default="reports")
    ap.add_argument("--report-date", default="")
    ap.add_argument("--source-run-id", default="")
    ap.add_argument("--head-ref", default="")
    ap.add_argument("--diff-path", default="")
    ap.add_argument("--provenance-path", default="")
    ap.add_argument("--artifact-name", default="")
    ap.add_argument("--snapshot-file", default="")
    ap.add_argument("--release-tag", default="")
    args = ap.parse_args(argv)

    manifest = _load_manifest(Path(args.manifest))
    rc = _validate_manifest_shape(manifest)
    if rc != 0:
        return rc

    if args.mode == "ci":
        return _validate_ci(args, manifest)
    if args.mode == "data-update":
        return _validate_data_update(args, manifest)
    if args.mode == "post-merge":
        return _validate_post_merge(args, manifest)
    return _validate_auto_review(args, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
