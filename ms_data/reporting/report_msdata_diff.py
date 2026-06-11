#!/usr/bin/env python3
"""
msData.json の差分レポートを Markdown で出力する。

差分の計算は ms_data.reporting.msdata_diff_model、本モジュールは
Markdown への整形（エスケープ・表組み・セクション構成）と CLI を担う。

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
from typing import Any

from ms_data.core import json_io

# 後方互換 re-export（差分計算は msdata_diff_model 側に実装がある）
from ms_data.reporting.msdata_diff_model import (
    _DELETED,
    _Sentinel,
    base_ms_name,
    diff_field_counts,
    diff_summary,
    format_value_plain,
    fullst_detail_rows,
    fullst_point_text,
    get_changed_records_detail,
    global_keys,
    index_by_name,
    indexed_fullst_items,
    level_sort_key,
    ms_level_sort_key,
)

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
    """fullst の概要表示（件数のみ）を作る。"""
    if isinstance(value, _Sentinel):
        return "なし"
    if isinstance(value, list):
        return f"{len(value)}件"
    return format_value(value)


def level_label(name: str) -> str:
    """ "ガンダム_LV3" → "LV3"（LV サフィックスが無ければ "LV不明"）。"""
    match = re.search(r"_LV(\d+)$", name)
    return f"LV{match.group(1)}" if match else "LV不明"


def append_table(lines: list[str], headers: list[str], rows: list[list[str]]) -> None:
    """Markdown 表を lines に追記する（行なしの場合は「なし」行）。"""
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
    lines: list[str], counter: Counter[str], limit: int = 20
) -> None:
    """件数カウンタを「項目 | 件数」の表として追記する（件数降順・上位 limit 件）。"""
    rows = [
        [_escape_md(key), str(count)]
        for key, count in sorted(counter.items(), key=lambda x: (-x[1], x[0]))[:limit]
    ]
    append_table(lines, ["項目", "件数"], rows)


def record_table_row(name: str, rec: dict[str, Any]) -> list[str]:
    """レコード1件分の主要ステータス行を作る。"""
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


def record_ms_table_row(name: str, rec: dict[str, Any]) -> list[str]:
    """機体別グループ表の1行（先頭列を LV ラベルに置き換え）。"""
    return [level_label(name), *record_table_row(name, rec)[1:]]


def append_records_by_ms_table(
    lines: list[str],
    title: str,
    names: list[str],
    records: dict[str, dict[str, Any]],
    list_limit: int,
) -> None:
    """追加/削除レコードを機体ごとにグループ化した表で追記する。"""
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
    lines: list[str],
    changed_records_detail: list[tuple[str, list[tuple[str, str, Any, Any]]]],
    list_limit: int,
) -> None:
    """変更レコードを機体ごとの「変更前/変更後」表と fullst 明細で追記する。"""
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
        rows: list[list[str]] = []
        fullst_details: list[tuple[str, Any, Any]] = []
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
    old_list: list[Any],
    new_list: list[Any],
    *,
    list_limit: int = 200,
    generated_at: datetime | None = None,
    old_label: str = "old",
    new_label: str = "new",
    notes: list[str] | None = None,
) -> tuple[list[str], str]:
    """差分レポートの本文行と1行サマリを組み立てる。"""
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

    lines: list[str] = []
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


def main(argv: list[str] | None = None) -> int:
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
