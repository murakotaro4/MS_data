#!/usr/bin/env python3
"""
msData.json の差分レポートを Markdown で出力する。

例:
  uv run python scripts/report_msdata_diff.py --old msData.before.json --new msData.json --out reports/diff_msdata_20250115.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def index_by_name(records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        name = rec.get("MS名")
        if isinstance(name, str):
            indexed[name] = rec
    return indexed


def global_keys(records: Iterable[Dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for rec in records:
        keys.update(rec.keys())
    return keys


def diff_summary(old: Dict[str, Dict[str, Any]], new: Dict[str, Dict[str, Any]]) -> Tuple[int, int, int, int, int]:
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys
    changed = {
        k
        for k in common
        if json.dumps(old[k], sort_keys=True, ensure_ascii=False)
        != json.dumps(new[k], sort_keys=True, ensure_ascii=False)
    }
    return (len(old_keys), len(new_keys), len(added), len(removed), len(changed))


def diff_field_counts(
    old: Dict[str, Dict[str, Any]], new: Dict[str, Dict[str, Any]]
) -> Tuple[Counter[str], Counter[str], Counter[str]]:
    changed_fields: Counter[str] = Counter()
    added_fields: Counter[str] = Counter()
    removed_fields: Counter[str] = Counter()

    common = set(old.keys()) & set(new.keys())
    for name in common:
        o = old[name]
        n = new[name]
        o_keys = set(o.keys())
        n_keys = set(n.keys())
        for k in n_keys - o_keys:
            added_fields[k] += 1
        for k in o_keys - n_keys:
            removed_fields[k] += 1
        for k in o_keys & n_keys:
            if o.get(k) != n.get(k):
                changed_fields[k] += 1
    return changed_fields, added_fields, removed_fields


def format_top(counter: Counter[str], limit: int = 20) -> List[str]:
    items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    return [f"- {k}: {v} 件" for k, v in items[:limit]]


def format_list(items: Iterable[str], limit: int) -> Tuple[List[str], bool]:
    data = list(items)
    truncated = len(data) > limit
    head = data[:limit]
    return ([f"  - {x}" for x in head], truncated)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--list-limit", type=int, default=200)
    ap.add_argument("--print-summary", action="store_true")
    args = ap.parse_args(argv)

    old_list = load_json(args.old)
    new_list = load_json(args.new)
    if not isinstance(old_list, list) or not isinstance(new_list, list):
        raise ValueError("old/new は配列(JSON)である必要があります。")

    old_index = index_by_name([e for e in old_list if isinstance(e, dict)])
    new_index = index_by_name([e for e in new_list if isinstance(e, dict)])
    old_count, new_count, added_count, removed_count, changed_count = diff_summary(
        old_index, new_index
    )

    old_keys = global_keys(old_index.values())
    new_keys = global_keys(new_index.values())
    added_keys = sorted(new_keys - old_keys)
    removed_keys = sorted(old_keys - new_keys)

    changed_fields, added_fields, removed_fields = diff_field_counts(old_index, new_index)

    added_records = sorted(set(new_index.keys()) - set(old_index.keys()))
    removed_records = sorted(set(old_index.keys()) - set(new_index.keys()))

    now = datetime.now()
    out_date = now.strftime("%Y%m%d")
    out_dt = now.strftime("%Y-%m-%d %H:%M:%S")

    lines: List[str] = []
    lines.append(f"# msData 差分レポート ({out_date})")
    lines.append("")
    lines.append(f"- 生成日時: {out_dt}")
    lines.append(f"- 比較対象: `{args.old}` → `{args.new}`")
    lines.append("")
    lines.append("## サマリ")
    lines.append(
        f"- レコード数: {old_count} → {new_count} | +{added_count} -{removed_count} ~{changed_count}"
    )
    lines.append(
        f"- グローバル項目数: {len(old_keys)} → {len(new_keys)} | +{len(added_keys)} -{len(removed_keys)}"
    )
    lines.append(
        "- 追加された項目: " + (", ".join(added_keys) if added_keys else "なし")
    )
    lines.append(
        "- 削除された項目: " + (", ".join(removed_keys) if removed_keys else "なし")
    )
    lines.append("")
    lines.append("## 変更項目の頻度（上位）")
    lines.extend(format_top(changed_fields))
    if not changed_fields:
        lines.append("- 変更なし")
    lines.append("")
    lines.append("## レコード単位で新規追加された項目（頻度）")
    lines.extend(format_top(added_fields))
    if not added_fields:
        lines.append("- 追加なし")
    lines.append("")
    lines.append("## レコード単位で削除された項目（頻度）")
    lines.extend(format_top(removed_fields))
    if not removed_fields:
        lines.append("- 削除なし")
    lines.append("")
    lines.append("## 追加レコード一覧")
    lines.append(f"- 件数: {len(added_records)}")
    add_list, add_truncated = format_list(added_records, args.list_limit)
    lines.extend(add_list)
    if add_truncated:
        lines.append(f"  - ...（残り {len(added_records) - args.list_limit} 件）")
    lines.append("")
    lines.append("## 削除レコード一覧")
    lines.append(f"- 件数: {len(removed_records)}")
    del_list, del_truncated = format_list(removed_records, args.list_limit)
    lines.extend(del_list)
    if del_truncated:
        lines.append(f"  - ...（残り {len(removed_records) - args.list_limit} 件）")
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")

    if args.print_summary:
        print(
            f"records: {old_count} -> {new_count} | +{added_count} -{removed_count} ~{changed_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
