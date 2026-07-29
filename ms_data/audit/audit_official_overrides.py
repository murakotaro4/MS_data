"""official_overrides の適用状態を監査する。"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ms_data.core.dates import JST
from ms_data.core.records import load_records_by_name
from ms_data.gh.outputs import append_step_summary, write_github_output
from ms_data.reporting.rendering import value_text as _value_text
from ms_data.pipeline import update_msdata


def _load_records(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    return load_records_by_name(path)


def _classify(
    *,
    before_value: Any,
    raw_value: Any,
    current_value: Any,
    override_value: Any,
    stale_value: Any,
    raw_available: bool,
) -> str:
    if current_value is None:
        return "missing_current"
    if stale_value is not None and current_value == stale_value:
        return "protected_rollback"
    if current_value != override_value:
        return "source_changed"
    if raw_available and raw_value == override_value:
        return "upstream_current"
    if raw_available and raw_value == stale_value:
        return "protected_by_override"
    if before_value == override_value:
        return "already_protected"
    return "current_matches_override"


def _parse_date(value: str) -> date:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date()
    return date.fromisoformat(value)


def _today(value: str | None) -> date:
    if value:
        return _parse_date(value)
    return datetime.now(JST).date()


def _date_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def load_lifecycle_metadata(
    directory: Path,
) -> dict[tuple[str, str], dict[str, str]]:
    """override 値単位の期限メタデータを読み込む。"""

    if not directory.exists() or not directory.is_dir():
        return {}

    metadata: dict[tuple[str, str], dict[str, str]] = {}
    for path in sorted(directory.glob("*.json")):
        data = update_msdata.load_json(path)
        if not isinstance(data, dict):
            continue
        if data.get("active", True) is False:
            continue

        file_review_after = _date_text(data.get("review_after"))
        file_remove_after = _date_text(data.get("remove_after"))
        entries = data.get("overrides", data.get("records", []))
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("MS名")
            raw_values = entry.get("values")
            if not isinstance(raw_name, str) or not isinstance(raw_values, dict):
                continue
            values = update_msdata.apply_key_aliases(dict(raw_values))
            name = update_msdata.normalize_ms_name(raw_name)
            review_after = _date_text(entry.get("review_after")) or file_review_after
            remove_after = _date_text(entry.get("remove_after")) or file_remove_after
            for field in values:
                metadata[(name, field)] = {
                    "file": path.name,
                    "review_after": review_after,
                    "remove_after": remove_after,
                }
    return metadata


def classify_lifecycle(meta: dict[str, str], today: date) -> str:
    remove_after = meta.get("remove_after", "")
    review_after = meta.get("review_after", "")
    if remove_after and today >= _parse_date(remove_after):
        return "remove_due"
    if review_after and today >= _parse_date(review_after):
        return "review_due"
    if remove_after or review_after:
        return "scheduled"
    return "not_set"


def build_audit(
    *,
    overrides: dict[str, dict[str, update_msdata.OfficialOverrideValue]],
    current_records: dict[str, dict[str, Any]],
    raw_records: dict[str, dict[str, Any]],
    before_records: dict[str, dict[str, Any]],
    lifecycle_metadata: dict[tuple[str, str], dict[str, str]] | None = None,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    lifecycle_counts: Counter[str] = Counter()
    raw_available = bool(raw_records)
    lifecycle_metadata = lifecycle_metadata or {}
    today = today or datetime.now(JST).date()

    for name in sorted(overrides):
        for field in sorted(overrides[name]):
            spec = overrides[name][field]
            override_value = spec.get("value")
            stale_value = spec.get("stale_value")
            before_value = before_records.get(name, {}).get(field)
            raw_value = raw_records.get(name, {}).get(field)
            current_value = current_records.get(name, {}).get(field)
            status = _classify(
                before_value=before_value,
                raw_value=raw_value,
                current_value=current_value,
                override_value=override_value,
                stale_value=stale_value,
                raw_available=raw_available,
            )
            counts[status] += 1
            lifecycle = lifecycle_metadata.get((name, field), {})
            lifecycle_status = classify_lifecycle(lifecycle, today)
            lifecycle_counts[lifecycle_status] += 1
            rows.append(
                {
                    "MS名": name,
                    "field": field,
                    "status": status,
                    "lifecycle": lifecycle_status,
                    "review_after": lifecycle.get("review_after", ""),
                    "remove_after": lifecycle.get("remove_after", ""),
                    "override_file": lifecycle.get("file", ""),
                    "before": before_value,
                    "raw": raw_value,
                    "current": current_value,
                    "override": override_value,
                    "stale": stale_value,
                }
            )
    return rows, counts, lifecycle_counts


def _append_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    lines.append("| MS名 | 項目 | 状態 | 変更前 | 取得値 | 現在値 | override | stale |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    if not rows:
        lines.append("| なし |  |  |  |  |  |  |  |")
        return
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["MS名"]),
                    str(row["field"]),
                    str(row["status"]),
                    _value_text(row["before"]),
                    _value_text(row["raw"]),
                    _value_text(row["current"]),
                    _value_text(row["override"]),
                    _value_text(row["stale"]),
                ]
            )
            + " |"
        )


def _append_lifecycle_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    lines.append(
        "| MS名 | 項目 | 期限状態 | review_after | remove_after | 状態 | override | 取得値 |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    if not rows:
        lines.append("| なし |  |  |  |  |  |  |  |")
        return
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["MS名"]),
                    str(row["field"]),
                    str(row["lifecycle"]),
                    str(row["review_after"]),
                    str(row["remove_after"]),
                    str(row["status"]),
                    _value_text(row["override"]),
                    _value_text(row["raw"]),
                ]
            )
            + " |"
        )


def render_markdown(
    rows: list[dict[str, Any]],
    counts: Counter[str],
    lifecycle_counts: Counter[str],
) -> str:
    lines: list[str] = [
        "# official_overrides 監査",
        "",
        "## サマリ",
        "",
    ]
    total = sum(counts.values())
    lines.append(f"- 対象値: {total}")
    for status, count in sorted(counts.items()):
        lines.append(f"- {status}: {count}")
    for status in ("review_due", "remove_due"):
        lines.append(f"- {status}: {lifecycle_counts.get(status, 0)}")
    lines.append("")
    lines.append("## 期限確認")
    lines.append("")
    due_rows = [row for row in rows if row["lifecycle"] in {"review_due", "remove_due"}]
    lines.append(
        "review_after 到達値は再確認、remove_after 到達値は撤去可否を判断してください。"
    )
    _append_lifecycle_table(lines, due_rows)
    lines.append("")
    lines.append("## 撤去候補")
    lines.append("")
    upstream_current = [row for row in rows if row["status"] == "upstream_current"]
    lines.append("取得値が override と一致しているため、次回確認後に撤去候補です。")
    _append_table(lines, upstream_current)
    lines.append("")
    lines.append("## 適用中")
    lines.append("")
    protected = [row for row in rows if row["status"] == "protected_by_override"]
    _append_table(lines, protected)
    lines.append("")
    lines.append("## 要確認")
    lines.append("")
    attention = [
        row
        for row in rows
        if row["status"] in {"protected_rollback", "source_changed", "missing_current"}
    ]
    _append_table(lines, attention)
    lines.append("")
    return "\n".join(lines) + "\n"


def _write_github_output(
    path: Path, counts: Counter[str], lifecycle_counts: Counter[str]
) -> None:
    due_count = lifecycle_counts.get("review_due", 0) + lifecycle_counts.get(
        "remove_due", 0
    )
    values = {
        "protected_rollback": counts.get("protected_rollback", 0),
        "source_changed": counts.get("source_changed", 0),
        "review_due": lifecycle_counts.get("review_due", 0),
        "remove_due": lifecycle_counts.get("remove_due", 0),
        "due_count": due_count,
        "due_summary": (
            f"review_due={lifecycle_counts.get('review_due', 0)},"
            f"remove_due={lifecycle_counts.get('remove_due', 0)}"
        ),
    }
    write_github_output(path, values)


def _append_step_summary(
    counts: Counter[str], lifecycle_counts: Counter[str], path: Path | None = None
) -> None:
    lines = [
        "### official_overrides 期限監査",
        f"- protected_rollback: {counts.get('protected_rollback', 0)}",
        f"- source_changed: {counts.get('source_changed', 0)}",
        f"- review_due: {lifecycle_counts.get('review_due', 0)}",
        f"- remove_due: {lifecycle_counts.get('remove_due', 0)}",
    ]
    append_step_summary(lines, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--overrides-dir",
        type=Path,
        default=update_msdata.OFFICIAL_OVERRIDES_DIR,
    )
    parser.add_argument("--current", type=Path, default=Path("msData.json"))
    parser.add_argument("--raw", type=Path, default=None)
    parser.add_argument("--before", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--today", default=None)
    parser.add_argument("--fail-on-protected-rollback", action="store_true")
    parser.add_argument("--fail-on-remove-due", action="store_true")
    parser.add_argument("--github-output", type=Path, default=None)
    parser.add_argument("--step-summary", type=Path, default=None)
    args = parser.parse_args(argv)

    overrides = update_msdata.load_official_overrides(args.overrides_dir)
    lifecycle_metadata = load_lifecycle_metadata(args.overrides_dir)
    current_records = _load_records(args.current)
    raw_records = _load_records(args.raw)
    before_records = _load_records(args.before)
    rows, counts, lifecycle_counts = build_audit(
        overrides=overrides,
        current_records=current_records,
        raw_records=raw_records,
        before_records=before_records,
        lifecycle_metadata=lifecycle_metadata,
        today=_today(args.today),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render_markdown(rows, counts, lifecycle_counts), encoding="utf-8"
    )
    if args.github_output is not None:
        _write_github_output(args.github_output, counts, lifecycle_counts)
    _append_step_summary(counts, lifecycle_counts, args.step_summary)

    if args.fail_on_protected_rollback and counts.get("protected_rollback", 0) > 0:
        return 1
    if args.fail_on_remove_due and lifecycle_counts.get("remove_due", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
