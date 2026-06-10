"""msData 更新差分から巻き戻り候補を検出する。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ms_data.core.records import load_records_by_name as _load_records
from ms_data.reporting.rendering import value_text as _value_text
from ms_data.pipeline import update_msdata


NUMERIC_GUARD_FIELDS = {
    "HP",
    "スピード",
    "高速移動",
    "スラスター",
    "射撃補正",
    "格闘補正",
    "耐実弾補正",
    "耐ビーム補正",
    "耐格闘補正",
    "近スロット",
    "中スロット",
    "遠スロット",
    "再出撃時間",
}


def _base_name(name: str) -> str:
    return re.sub(r"_LV\d+$", "", name)


def detect_protected_rollbacks(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, update_msdata.OfficialOverrideValue]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for name in sorted(overrides):
        old_record = old.get(name, {})
        new_record = new.get(name, {})
        for field, spec in sorted(overrides[name].items()):
            if "stale_value" not in spec:
                continue
            override_value = spec.get("value")
            stale_value = spec.get("stale_value")
            old_value = old_record.get(field)
            new_value = new_record.get(field)
            if old_value == override_value and new_value == stale_value:
                findings.append(
                    {
                        "type": "protected_rollback",
                        "MS名": name,
                        "field": field,
                        "old": old_value,
                        "new": new_value,
                        "override": override_value,
                        "stale": stale_value,
                    }
                )
    return findings


def detect_numeric_changes(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for name in sorted(set(old) & set(new)):
        old_record = old[name]
        new_record = new[name]
        for field in sorted(NUMERIC_GUARD_FIELDS):
            old_value = old_record.get(field)
            new_value = new_record.get(field)
            if (
                isinstance(old_value, int)
                and isinstance(new_value, int)
                and new_value != old_value
            ):
                changes.append(
                    {
                        "type": (
                            "numeric_decrease"
                            if new_value < old_value
                            else "numeric_increase"
                        ),
                        "MS名": name,
                        "field": field,
                        "old": old_value,
                        "new": new_value,
                    }
                )
    return changes


def detect_mixed_level_changes(
    numeric_changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in numeric_changes:
        grouped[(_base_name(str(row["MS名"])), str(row["field"]))].append(row)

    warnings: list[dict[str, Any]] = []
    for (base, field), rows in grouped.items():
        has_decrease = any(int(row["new"]) < int(row["old"]) for row in rows)
        has_increase = any(int(row["new"]) > int(row["old"]) for row in rows)
        if has_decrease and has_increase:
            warnings.append(
                {
                    "type": "mixed_level_change",
                    "base": base,
                    "field": field,
                    "rows": rows,
                }
            )
    return warnings


def _append_rows(lines: list[str], rows: list[dict[str, Any]]) -> None:
    lines.append("| 種別 | MS名 | 項目 | 変更前 | 変更後 |")
    lines.append("| --- | --- | --- | --- | --- |")
    if not rows:
        lines.append("| なし |  |  |  |  |")
        return
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["type"]),
                    str(row["MS名"]),
                    str(row["field"]),
                    _value_text(row.get("old")),
                    _value_text(row.get("new")),
                ]
            )
            + " |"
        )


def render_report(
    *,
    protected_rollbacks: list[dict[str, Any]],
    numeric_decreases: list[dict[str, Any]],
    mixed_level_changes: list[dict[str, Any]],
) -> str:
    counts = Counter(
        {
            "protected_rollback": len(protected_rollbacks),
            "numeric_decrease": len(numeric_decreases),
            "mixed_level_change": len(mixed_level_changes),
        }
    )
    lines = [
        "# msData 巻き戻りガード",
        "",
        "## サマリ",
        "",
    ]
    for key in ("protected_rollback", "numeric_decrease", "mixed_level_change"):
        lines.append(f"- {key}: {counts[key]}")
    lines.append("")
    lines.append("## ブロック対象")
    lines.append("")
    _append_rows(lines, protected_rollbacks)
    lines.append("")
    lines.append("## 数値低下の注意候補")
    lines.append("")
    _append_rows(lines, numeric_decreases[:100])
    if len(numeric_decreases) > 100:
        lines.append(f"- 省略: {len(numeric_decreases) - 100} 件")
    lines.append("")
    lines.append("## LV間で増減が混在した候補")
    lines.append("")
    if not mixed_level_changes:
        lines.append("該当なし")
    else:
        for item in mixed_level_changes:
            lines.append(f"### {item['base']} / {item['field']}")
            _append_rows(lines, item["rows"])
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument(
        "--official-overrides-dir",
        type=Path,
        default=update_msdata.OFFICIAL_OVERRIDES_DIR,
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fail-on-protected-rollback", action="store_true")
    args = parser.parse_args(argv)

    old = _load_records(args.old)
    new = _load_records(args.new)
    overrides = update_msdata.load_official_overrides(args.official_overrides_dir)
    protected_rollbacks = detect_protected_rollbacks(old, new, overrides)
    numeric_changes = detect_numeric_changes(old, new)
    numeric_decreases = [
        row for row in numeric_changes if row["type"] == "numeric_decrease"
    ]
    mixed_level_changes = detect_mixed_level_changes(numeric_changes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render_report(
            protected_rollbacks=protected_rollbacks,
            numeric_decreases=numeric_decreases,
            mixed_level_changes=mixed_level_changes,
        ),
        encoding="utf-8",
    )

    if args.fail_on_protected_rollback and protected_rollbacks:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
