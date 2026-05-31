"""official_overrides の適用状態を監査する。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts import update_msdata


def _load_records(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"record file must be a JSON array: {path}")
    records: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"record must be an object: {path}#{index}")
        name = item.get("MS名")
        if isinstance(name, str) and name.strip():
            records[name] = item
    return records


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


def build_audit(
    *,
    overrides: dict[str, dict[str, update_msdata.OfficialOverrideValue]],
    current_records: dict[str, dict[str, Any]],
    raw_records: dict[str, dict[str, Any]],
    before_records: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    raw_available = bool(raw_records)

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
            rows.append(
                {
                    "MS名": name,
                    "field": field,
                    "status": status,
                    "before": before_value,
                    "raw": raw_value,
                    "current": current_value,
                    "override": override_value,
                    "stale": stale_value,
                }
            )
    return rows, counts


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


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


def render_markdown(rows: list[dict[str, Any]], counts: Counter[str]) -> str:
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
    parser.add_argument("--fail-on-protected-rollback", action="store_true")
    args = parser.parse_args(argv)

    overrides = update_msdata.load_official_overrides(args.overrides_dir)
    current_records = _load_records(args.current)
    raw_records = _load_records(args.raw)
    before_records = _load_records(args.before)
    rows, counts = build_audit(
        overrides=overrides,
        current_records=current_records,
        raw_records=raw_records,
        before_records=before_records,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(rows, counts), encoding="utf-8")

    if args.fail_on_protected_rollback and counts.get("protected_rollback", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
