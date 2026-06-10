#!/usr/bin/env python3
"""
msData.json の差分レポートを Markdown で出力する。

例:
  uv run python -m ms_data.reporting.report_msdata_diff --old msData.before.json --new msData.json --out reports/diff_msdata_20250115.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ms_data.core import json_io

# Markdown 特殊文字のエスケープ用正規表現
_MD_ESCAPE = re.compile(r"([\\`*_\[\]()#+\-.!|<>])")


def _escape_md(s: str) -> str:
    """Markdown の特殊文字をエスケープ。"""
    return _MD_ESCAPE.sub(r"\\\1", s)


def load_json(path: Path) -> Any:
    """JSON ファイルを読み込む。失敗時はエラーメッセージを表示して終了。"""
    try:
        return json_io.load_json(path)
    except OSError as e:
        print(f"エラー: {path} を開けません: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    except json.JSONDecodeError as e:
        print(f"エラー: {path} の JSON パースに失敗: {e}", file=sys.stderr)
        raise SystemExit(1) from e


def index_by_name(
    records: Iterable[Any],
) -> Tuple[Dict[str, Dict[str, Any]], Counter[str], int]:
    """レコードを MS名 でインデックス化。重複カウンタと不正レコード数を返す。"""
    indexed: Dict[str, Dict[str, Any]] = {}
    name_counts: Counter[str] = Counter()
    invalid_count = 0
    for rec in records:
        if not isinstance(rec, dict):
            invalid_count += 1
            continue
        name = rec.get("MS名")
        if not isinstance(name, str) or not name.strip():
            invalid_count += 1
            continue
        name_counts[name] += 1
        indexed[name] = rec
    return indexed, name_counts, invalid_count


def global_keys(records: Iterable[Dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for rec in records:
        keys.update(rec.keys())
    return keys


def diff_summary(
    old: Dict[str, Dict[str, Any]], new: Dict[str, Dict[str, Any]]
) -> Tuple[int, int, int, int, int]:
    """差分サマリを計算。直接辞書比較で json.dumps オーバーヘッドを回避。"""
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys
    changed = {k for k in common if old[k] != new[k]}
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
    return [f"- {_escape_md(k)}: {v} 件" for k, v in items[:limit]]


def format_list(items: Iterable[str], limit: int) -> Tuple[List[str], bool]:
    data = list(items)
    truncated = len(data) > limit
    head = data[:limit]
    return ([f"  - {_escape_md(x)}" for x in head], truncated)


class _Sentinel:
    """キー削除を表すセンチネル。None と区別するために使用。"""

    pass


_DELETED = _Sentinel()


def get_changed_records_detail(
    old: Dict[str, Dict[str, Any]], new: Dict[str, Dict[str, Any]]
) -> List[Tuple[str, List[Tuple[str, str, Any, Any]]]]:
    """変更レコードの詳細を取得。

    戻り値: [(機体名, [(操作種別, 項目名, 旧値, 新値), ...]), ...]
    操作種別: "added" | "removed" | "changed"
    """
    result: List[Tuple[str, List[Tuple[str, str, Any, Any]]]] = []
    common = set(old.keys()) & set(new.keys())

    for name in common:
        o = old[name]
        n = new[name]
        changes: List[Tuple[str, str, Any, Any]] = []

        o_keys = set(o.keys())
        n_keys = set(n.keys())

        # 追加された項目
        for k in sorted(n_keys - o_keys):
            changes.append(("added", k, _DELETED, n[k]))

        # 削除された項目
        for k in sorted(o_keys - n_keys):
            changes.append(("removed", k, o[k], _DELETED))

        # 変更された項目
        for k in sorted(o_keys & n_keys):
            if o.get(k) != n.get(k):
                changes.append(("changed", k, o[k], n[k]))

        if changes:
            result.append((name, changes))

    return result


def format_value(value: Any, max_len: int = 120) -> str:
    """値を表示用にフォーマット。

    特殊文字（改行、引用符、バックスラッシュ等）と Markdown 特殊文字をエスケープ。
    長すぎる値は切り詰める。
    """
    if isinstance(value, _Sentinel):
        return "削除"
    if value is None:
        return "null"
    if isinstance(value, str):
        s = json.dumps(value, ensure_ascii=False)[1:-1]
    elif isinstance(value, (list, dict)):
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = str(value)
    s = _escape_md(s)
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def format_value_plain(value: Any, max_len: int = 120) -> str:
    if isinstance(value, _Sentinel):
        return ""
    if value is None:
        return "null"
    if isinstance(value, str):
        s = json.dumps(value, ensure_ascii=False)[1:-1]
    elif isinstance(value, (list, dict)):
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = str(value)
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def format_field_value(field: str, value: Any, max_len: int = 120) -> str:
    """変更表向けに値を短く整形する。"""
    if field == "fullst" and isinstance(value, list):
        parts = []
        for item in value[:6]:
            if not isinstance(item, dict):
                parts.append(format_value(item, max_len=40))
                continue
            name = item.get("name", "")
            level = item.get("level", "")
            if "points" not in item:
                points_text = "未設定"
            else:
                points = item.get("points", None)
                points_text = "null" if points is None else str(points)
            parts.append(f"{name} Lv{level}:{points_text}")
        if len(value) > 6:
            parts.append(f"他{len(value) - 6}件")
        return _escape_md(f"{len(value)}件: " + " / ".join(parts))
    return format_value(value, max_len=max_len)


def format_fullst_summary(value: Any) -> str:
    if isinstance(value, _Sentinel):
        return "なし"
    if isinstance(value, list):
        return f"{len(value)}件"
    return format_value(value)


def fullst_point_text(item: Any) -> str:
    if isinstance(item, dict):
        if "points" not in item:
            return "未設定"
        if item.get("points") is None:
            return "null"
        return format_value_plain(item.get("points"))
    return ""


def indexed_fullst_items(
    items: List[Any],
) -> Dict[tuple[str, Any, int], tuple[int, Any]]:
    counts: Counter[tuple[str, Any]] = Counter()
    indexed: Dict[tuple[str, Any, int], tuple[int, Any]] = {}
    for pos, item in enumerate(items, start=1):
        if isinstance(item, dict):
            name = str(item.get("name", ""))
            level = item.get("level", "")
        else:
            name = str(item)
            level = ""
        counts[(name, level)] += 1
        indexed[(name, level, counts[(name, level)])] = (pos, item)
    return indexed


def fullst_detail_rows(old_val: Any, new_val: Any) -> List[List[str]]:
    old_items = old_val if isinstance(old_val, list) else []
    new_items = new_val if isinstance(new_val, list) else []
    old_index = indexed_fullst_items(old_items)
    new_index = indexed_fullst_items(new_items)
    keys = list(old_index.keys()) + [key for key in new_index if key not in old_index]
    rows: List[List[str]] = []
    for name, level, occurrence in keys:
        old_pos, old_item = old_index.get((name, level, occurrence), ("", None))
        new_pos, new_item = new_index.get((name, level, occurrence), ("", None))
        rows.append(
            [
                str(old_pos),
                str(new_pos),
                name,
                format_value_plain(level),
                fullst_point_text(old_item),
                fullst_point_text(new_item),
            ]
        )
    return rows


def format_change_inline(
    name: str, changes: List[Tuple[str, str, Any, Any]], max_items: int = 5
) -> str:
    """変更内容をインライン形式でフォーマット。

    形式: '機体名: 項目 (旧 → 新), ...'
    max_items: 表示する項目数の上限（超過分は省略表示）
    """
    parts: List[str] = []
    for op, field, old_val, new_val in changes[:max_items]:
        escaped_field = _escape_md(field)
        old_str = format_value(old_val)
        new_str = format_value(new_val)
        if op == "removed":
            parts.append(f"{escaped_field} ({old_str} → 削除)")
        elif op == "added":
            parts.append(f"{escaped_field} (追加: {new_str})")
        else:
            parts.append(f"{escaped_field} ({old_str} → {new_str})")
    if len(changes) > max_items:
        parts.append(f"他{len(changes) - max_items}件")
    escaped_name = _escape_md(name)
    return f"{escaped_name}: {', '.join(parts)}"


def level_sort_key(name: str) -> tuple[int, str]:
    match = re.search(r"_LV(\d+)$", name)
    if match:
        return int(match.group(1)), name
    return 999, name


def level_label(name: str) -> str:
    match = re.search(r"_LV(\d+)$", name)
    return f"LV{match.group(1)}" if match else "LV不明"


def base_ms_name(name: str) -> str:
    return re.sub(r"_LV\d+$", "", name)


def ms_level_sort_key(name: str) -> tuple[str, int, str]:
    lv, full_name = level_sort_key(name)
    return base_ms_name(name), lv, full_name


def append_table(lines: List[str], headers: List[str], rows: List[List[str]]) -> None:
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    if rows:
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append(
            "| "
            + " | ".join("なし" if i == 0 else "" for i in range(len(headers)))
            + " |"
        )


def append_counter_table(
    lines: List[str], counter: Counter[str], limit: int = 20
) -> None:
    rows = [
        [_escape_md(key), str(count)]
        for key, count in sorted(counter.items(), key=lambda x: (-x[1], x[0]))[:limit]
    ]
    append_table(lines, ["項目", "件数"], rows)


def record_table_row(name: str, rec: Dict[str, Any]) -> List[str]:
    slots = [rec.get(key, "") for key in ("近スロット", "中スロット", "遠スロット")]
    slots_text = "" if all(v == "" for v in slots) else "/".join(str(v) for v in slots)
    return [
        _escape_md(name),
        format_value(rec.get("属性", "")),
        format_value(rec.get("コスト", "")),
        format_value(rec.get("HP", "")),
        format_value(rec.get("スピード", "")),
        format_value(rec.get("高速移動", "")),
        format_value(rec.get("スラスター", "")),
        format_value(rec.get("射撃補正", "")),
        format_value(rec.get("格闘補正", "")),
        _escape_md(slots_text),
        str(len(rec.get("fullst") or [])),
    ]


def record_ms_table_row(name: str, rec: Dict[str, Any]) -> List[str]:
    return [level_label(name), *record_table_row(name, rec)[1:]]


def append_records_by_ms_table(
    lines: List[str],
    title: str,
    names: List[str],
    records: Dict[str, Dict[str, Any]],
    list_limit: int,
) -> None:
    lines.append(f"## {title}")
    lines.append("")
    lines.append(f"- 件数: {len(names)}")
    lines.append("")
    if not names:
        lines.append("該当なし")
        lines.append("")
        return

    shown = sorted(names, key=ms_level_sort_key)[:list_limit]
    for base in sorted({base_ms_name(name) for name in shown}):
        group = [name for name in shown if base_ms_name(name) == base]
        group.sort(key=level_sort_key)
        lines.append(f"### {_escape_md(base)}")
        append_table(
            lines,
            [
                "LV",
                "属性",
                "コスト",
                "HP",
                "スピード",
                "高速移動",
                "スラスター",
                "射撃",
                "格闘",
                "スロット(近/中/遠)",
                "fullst",
            ],
            [record_ms_table_row(name, records[name]) for name in group],
        )
        lines.append("")
    if len(names) > list_limit:
        lines.append(f"...（残り {len(names) - list_limit} 件）")
        lines.append("")


def append_changed_records_table(
    lines: List[str],
    changed_records_detail: List[Tuple[str, List[Tuple[str, str, Any, Any]]]],
    list_limit: int,
) -> None:
    lines.append("## 変更レコード一覧")
    lines.append("")
    lines.append(f"- 件数: {len(changed_records_detail)}")
    lines.append("")
    if not changed_records_detail:
        lines.append("該当なし")
        lines.append("")
        return

    sorted_changed = sorted(
        changed_records_detail, key=lambda x: ms_level_sort_key(x[0])
    )
    shown = sorted_changed[:list_limit]
    for base in sorted({base_ms_name(name) for name, _ in shown}):
        group = [
            (name, changes) for name, changes in shown if base_ms_name(name) == base
        ]
        group.sort(key=lambda x: level_sort_key(x[0]))
        rows: List[List[str]] = []
        fullst_details: List[Tuple[str, Any, Any]] = []
        for name, changes in group:
            lv = level_label(name)
            for op, field, old_val, new_val in changes:
                if field == "fullst":
                    old_text = "" if op == "added" else format_fullst_summary(old_val)
                    new_text = "" if op == "removed" else format_fullst_summary(new_val)
                    fullst_details.append((lv, old_val, new_val))
                elif op == "added":
                    old_text = ""
                    new_text = format_field_value(field, new_val)
                elif op == "removed":
                    old_text = format_field_value(field, old_val)
                    new_text = ""
                else:
                    old_text = format_field_value(field, old_val)
                    new_text = format_field_value(field, new_val)
                rows.append([_escape_md(lv), _escape_md(field), old_text, new_text])
        lines.append(f"### {_escape_md(base)}")
        append_table(lines, ["LV", "項目", "変更前", "変更後"], rows)
        lines.append("")
        for lv, old_val, new_val in fullst_details:
            lines.append(f"{_escape_md(lv)} fullst 明細:")
            append_table(
                lines,
                [
                    "変更前 No",
                    "変更後 No",
                    "名称",
                    "Lv",
                    "変更前 points",
                    "変更後 points",
                ],
                [
                    [_escape_md(cell) for cell in row]
                    for row in fullst_detail_rows(old_val, new_val)
                ],
            )
            lines.append("")
    if len(sorted_changed) > list_limit:
        lines.append(f"...（残り {len(sorted_changed) - list_limit} 件）")
        lines.append("")


def build_report_lines(
    old_list: List[Any],
    new_list: List[Any],
    *,
    list_limit: int = 200,
    generated_at: datetime | None = None,
    old_label: str = "old",
    new_label: str = "new",
    notes: List[str] | None = None,
) -> tuple[list[str], str]:
    if not isinstance(old_list, list) or not isinstance(new_list, list):
        raise ValueError("old/new は配列(JSON)である必要があります。")

    old_index, old_name_counts, old_invalid = index_by_name(old_list)
    new_index, new_name_counts, new_invalid = index_by_name(new_list)

    def _warn_dupes(label: str, name_counts: Counter[str]) -> None:
        dupe_names = {k: v for k, v in name_counts.items() if v > 1}
        if dupe_names:
            extra = sum(v - 1 for v in dupe_names.values())
            top = sorted(dupe_names)[:5]
            suffix = f" 他{len(dupe_names)-5}種" if len(dupe_names) > 5 else ""
            top_str = ", ".join(top)
            print(
                f"警告: {label} に重複 MS名 {len(dupe_names)}種 / 余剰{extra}件: {top_str}{suffix}",
                file=sys.stderr,
            )

    _warn_dupes("old", old_name_counts)
    _warn_dupes("new", new_name_counts)
    if old_invalid:
        print(
            f"警告: old に不正レコード（非dict/MS名欠落/空）が {old_invalid} 件あります",
            file=sys.stderr,
        )
    if new_invalid:
        print(
            f"警告: new に不正レコード（非dict/MS名欠落/空）が {new_invalid} 件あります",
            file=sys.stderr,
        )

    old_count, new_count, added_count, removed_count, changed_count = diff_summary(
        old_index, new_index
    )

    old_keys = global_keys(old_index.values())
    new_keys = global_keys(new_index.values())
    added_keys = sorted(new_keys - old_keys)
    removed_keys = sorted(old_keys - new_keys)

    changed_fields, added_fields, removed_fields = diff_field_counts(
        old_index, new_index
    )
    added_records = sorted(set(new_index.keys()) - set(old_index.keys()))
    removed_records = sorted(set(old_index.keys()) - set(new_index.keys()))
    changed_records_detail = get_changed_records_detail(old_index, new_index)

    now = generated_at or datetime.now()
    out_date = now.strftime("%Y%m%d")
    out_dt = now.strftime("%Y-%m-%d %H:%M:%S")
    summary = f"records: {old_count} -> {new_count} | +{added_count} -{removed_count} ~{changed_count}"

    lines: List[str] = []
    lines.append(f"# msData 差分レポート ({out_date})")
    lines.append("")
    lines.append(f"- 生成日時: {out_dt}")
    lines.append(f"- 比較対象: `{old_label}` → `{new_label}`")
    for note in notes or []:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## サマリ")
    lines.append(
        f"- レコード数: {old_count} → {new_count} | +{added_count} -{removed_count} ~{changed_count}"
    )
    lines.append(
        f"- グローバル項目数: {len(old_keys)} → {len(new_keys)} | +{len(added_keys)} -{len(removed_keys)}"
    )
    lines.append(
        "- 追加された項目: "
        + (", ".join(_escape_md(k) for k in added_keys) if added_keys else "なし")
    )
    lines.append(
        "- 削除された項目: "
        + (", ".join(_escape_md(k) for k in removed_keys) if removed_keys else "なし")
    )
    lines.append("")
    lines.append("## 変更項目の頻度（上位）")
    append_counter_table(lines, changed_fields)
    lines.append("")
    lines.append("## レコード単位で新規追加された項目（頻度）")
    append_counter_table(lines, added_fields)
    lines.append("")
    lines.append("## レコード単位で削除された項目（頻度）")
    append_counter_table(lines, removed_fields)
    lines.append("")
    append_records_by_ms_table(
        lines, "追加レコード一覧", added_records, new_index, list_limit
    )
    append_records_by_ms_table(
        lines, "削除レコード一覧", removed_records, old_index, list_limit
    )
    append_changed_records_table(lines, changed_records_detail, list_limit)
    return lines, summary


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--list-limit", type=int, default=200)
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--print-summary", action="store_true")
    args = ap.parse_args(argv)

    old_list = load_json(args.old)
    new_list = load_json(args.new)
    lines, summary = build_report_lines(
        old_list,
        new_list,
        list_limit=args.list_limit,
        old_label=str(args.old),
        new_label=str(args.new),
        notes=args.note,
    )

    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines), encoding="utf-8")
    except OSError as e:
        print(f"エラー: {args.out} への書き込みに失敗: {e}", file=sys.stderr)
        return 1

    if args.print_summary:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
