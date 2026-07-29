"""msData の必須フィールド充足率を監査する。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ms_data.core.dates import JST
from ms_data.core.records import load_records_by_name
from ms_data.gh.outputs import append_step_summary, write_github_output
from ms_data.reporting.rendering import value_text
from ms_data.scraping.detail_page import BASE_REQUIRED


ALLOWLIST_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

REQUIRED_KEYS = frozenset(
    BASE_REQUIRED
    | {
        "属性",
        "コスト",
        "レアリティ",
        "必要階級",
        "再出撃時間",
        "カウンター",
        "格闘判定力",
        "環境適正_地上",
        "環境適正_宇宙",
        "環境適正_水中",
        "出撃_地上可",
        "出撃_宇宙可",
    }
)
NON_EMPTY_KEYS = frozenset({"レアリティ", "カウンター", "格闘判定力"})
PAIR_RULES = (("旋回_地上_通常時", "旋回_宇宙_通常時"),)
IGNORED_FIELD_MARKERS = ("_変形時", "_変身時")
CATEGORIES = (
    "missing_key",
    "empty_value",
    "pair_missing",
    "suppressed",
    "expired",
)


class AllowlistConfigError(ValueError):
    """allowlist の設定が不正。"""


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return not value
    return False


def _parse_allowlist_date(value: Any, *, location: str) -> date:
    if not isinstance(value, str) or not ALLOWLIST_DATE_RE.fullmatch(value):
        raise AllowlistConfigError(f"{location}: YYYY-MM-DD 形式の日付が必要です")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AllowlistConfigError(f"{location}: 不正な日付です: {value}") from exc
    if parsed.isoformat() != value:
        raise AllowlistConfigError(f"{location}: 不正な日付です: {value}")
    return parsed


def _parse_today(value: str | None) -> date:
    if value is None:
        return datetime.now(JST).date()
    try:
        if len(value) == 8 and value.isdigit():
            return datetime.strptime(value, "%Y%m%d").date()
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AllowlistConfigError(f"today: 不正な日付です: {value}") from exc


def load_allowlist(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowlistConfigError(
            f"allowlist を読み込めません: {path}: {exc}"
        ) from exc

    if not isinstance(data, dict) or set(data) != {"version", "entries"}:
        raise AllowlistConfigError(
            "allowlist は version と entries のみを持つ object が必要です"
        )
    version = data["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise AllowlistConfigError("allowlist.version は整数 1 が必要です")
    entries = data["entries"]
    if not isinstance(entries, list):
        raise AllowlistConfigError("allowlist.entries は配列が必要です")

    result: dict[tuple[str, str], dict[str, Any]] = {}
    required_fields = {"MS名", "field", "reason", "review_after"}
    for index, entry in enumerate(entries):
        location = f"entries[{index}]"
        if not isinstance(entry, dict) or set(entry) != required_fields:
            raise AllowlistConfigError(
                f"{location}: {', '.join(sorted(required_fields))} のみが必要です"
            )
        for field in ("MS名", "field", "reason"):
            value = entry[field]
            if not isinstance(value, str) or not value.strip():
                raise AllowlistConfigError(f"{location}.{field}: 非空文字列が必要です")
        review_date = _parse_allowlist_date(
            entry["review_after"], location=f"{location}.review_after"
        )
        key = (entry["MS名"], entry["field"])
        if key in result:
            raise AllowlistConfigError(
                f"{location}: allowlist entry が重複しています: {key[0]} / {key[1]}"
            )
        result[key] = {**entry, "review_date": review_date}
    return result


def _raw_findings(records: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for name in sorted(records):
        record = records[name]
        for field in sorted(REQUIRED_KEYS):
            if any(marker in field for marker in IGNORED_FIELD_MARKERS):
                continue
            if field not in record:
                findings.append(
                    {"category": "missing_key", "MS名": name, "field": field}
                )
            elif (field in NON_EMPTY_KEYS or field == "必要階級") and _is_empty(
                record[field]
            ):
                findings.append(
                    {
                        "category": "empty_value",
                        "MS名": name,
                        "field": field,
                        "value": record[field],
                    }
                )
        for left, right in PAIR_RULES:
            if left not in record and right not in record:
                findings.append(
                    {
                        "category": "pair_missing",
                        "MS名": name,
                        "field": f"{left} / {right}",
                    }
                )
    return findings


def detect_field_completeness(
    records: Mapping[str, Mapping[str, Any]],
    allowlist: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    today: date,
) -> dict[str, list[dict[str, Any]]]:
    """レコードを分類する。入力を書き換えない純粋関数。"""

    classified = {category: [] for category in CATEGORIES}
    expired_keys = {
        key for key, entry in allowlist.items() if entry["review_date"] <= today
    }
    seen_expired: set[tuple[str, str]] = set()

    for finding in _raw_findings(records):
        key = (str(finding["MS名"]), str(finding["field"]))
        allow = allowlist.get(key)
        if allow is not None:
            category = "expired" if key in expired_keys else "suppressed"
            classified[category].append(
                {
                    **finding,
                    "category": category,
                    "reason": allow["reason"],
                    "review_after": allow["review_after"],
                }
            )
            if category == "expired":
                seen_expired.add(key)
            continue

        # 既知欠落は上で suppressed として可視化する。allowlist 非該当だけ、
        # DP 購入対象でない機体の必要階級欠落を正当な例外として除外する。
        if finding["field"] == "必要階級" and _is_empty(records[key[0]].get("必要DP")):
            continue
        classified[str(finding["category"])].append(finding)

    for key in sorted(expired_keys - seen_expired):
        entry = allowlist[key]
        classified["expired"].append(
            {
                "category": "expired",
                "MS名": key[0],
                "field": key[1],
                "reason": entry["reason"],
                "review_after": entry["review_after"],
            }
        )
    return classified


def _append_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    lines.append("| MS名 | 項目 | 分類 | 値 | 理由 | review_after |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    if not rows:
        lines.append("| なし |  |  |  |  |  |")
        return
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["MS名"]),
                    str(row["field"]),
                    str(row["category"]),
                    value_text(row.get("value")),
                    str(row.get("reason", "")),
                    str(row.get("review_after", "")),
                ]
            )
            + " |"
        )


def render_report(classified: Mapping[str, list[dict[str, Any]]]) -> str:
    lines = ["# フィールド充足率監査", "", "## サマリ", ""]
    for category in CATEGORIES:
        lines.append(f"- {category}: {len(classified[category])}")
    for category in CATEGORIES:
        lines.extend(["", f"## {category}", ""])
        _append_table(lines, classified[category])
    return "\n".join(lines) + "\n"


def _counts(classified: Mapping[str, list[dict[str, Any]]]) -> Counter[str]:
    return Counter({category: len(classified[category]) for category in CATEGORIES})


def _write_outputs(path: Path, counts: Counter[str]) -> None:
    findings = sum(counts[category] for category in CATEGORIES[:3])
    values: dict[str, Any] = {
        "field_completeness_findings": findings,
        **{f"field_completeness_{key}": counts[key] for key in CATEGORIES},
        "field_completeness_summary": ",".join(
            f"{key}={counts[key]}" for key in CATEGORIES
        ),
    }
    write_github_output(path, values)


def _write_step_summary(counts: Counter[str], path: Path | None) -> None:
    findings = sum(counts[category] for category in CATEGORIES[:3])
    append_step_summary(
        [
            "### フィールド充足率監査",
            f"- findings: {findings}",
            *(f"- {category}: {counts[category]}" for category in CATEGORIES),
        ],
        path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msdata", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--today", default=None)
    parser.add_argument("--github-output", type=Path, default=None)
    parser.add_argument("--step-summary", type=Path, default=None)
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args(argv)

    try:
        today = _parse_today(args.today)
        allowlist = load_allowlist(args.allowlist)
        records = load_records_by_name(args.msdata)
    except (AllowlistConfigError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    classified = detect_field_completeness(records, allowlist, today=today)
    counts = _counts(classified)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_report(classified), encoding="utf-8")
    if args.github_output is not None:
        _write_outputs(args.github_output, counts)
    _write_step_summary(counts, args.step_summary)

    findings = sum(counts[category] for category in CATEGORIES[:3])
    if args.fail_on_findings and findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
