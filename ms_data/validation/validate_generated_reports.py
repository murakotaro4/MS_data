"""生成レポートの最低限の構造契約を検証する。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ms_data.core.json_io import load_json as _load_json


JSON_SCHEMA_REPORTS = {
    "atwiki_quality_*.json": "atwiki_quality.schema.json",
    "provenance_*.json": "provenance.schema.json",
    "auto_review_*.json": "auto_review.schema.json",
}


def _validate_json_report(path: Path, schema_path: Path) -> list[str]:
    schema = _load_json(schema_path)
    data = _load_json(path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    messages: list[str] = []
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{path}: {location}: {error.message}")
    return messages


def _require_text(path: Path, required: list[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [
        f"{path}: required text missing: {item}"
        for item in required
        if item not in text
    ]


def validate_reports(reports_dir: Path, schema_dir: Path) -> list[str]:
    messages: list[str] = []
    if not reports_dir.exists():
        return messages

    for pattern, schema_name in JSON_SCHEMA_REPORTS.items():
        schema_path = schema_dir / schema_name
        if not schema_path.is_file():
            messages.append(f"schema not found: {schema_path}")
            continue
        for path in sorted(reports_dir.rglob(pattern)):
            try:
                messages.extend(_validate_json_report(path, schema_path))
            except (OSError, json.JSONDecodeError) as exc:
                messages.append(f"{path}: JSON validation failed: {exc}")

    for path in sorted(reports_dir.rglob("rollback_guard_*.md")):
        messages.extend(
            _require_text(
                path,
                [
                    "# msData 巻き戻りガード",
                    "- protected_rollback:",
                    "- numeric_decrease:",
                    "- mixed_level_change:",
                ],
            )
        )

    for path in sorted(reports_dir.rglob("official_overrides_audit_*.md")):
        messages.extend(
            _require_text(
                path,
                [
                    "# official_overrides 監査",
                    "- review_due:",
                    "- remove_due:",
                    "## 期限確認",
                ],
            )
        )

    for path in sorted(reports_dir.rglob("field_completeness_*.md")):
        messages.extend(
            _require_text(
                path,
                [
                    "# フィールド充足率監査",
                    "## サマリ",
                    "- missing_key:",
                    "- empty_value:",
                    "- pair_missing:",
                    "- suppressed:",
                    "- expired:",
                    "## missing_key",
                    "## empty_value",
                    "## pair_missing",
                    "## suppressed",
                    "## expired",
                ],
            )
        )

    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--schema-dir", type=Path, default=Path("schema/reports"))
    args = parser.parse_args(argv)

    messages = validate_reports(args.reports_dir, args.schema_dir)
    for message in messages:
        print(f"ERROR: {message}", file=sys.stderr)
    if messages:
        return 1
    print("OK: generated reports contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
