"""msData 差分レポートの「差分計算」部分（Markdown 描画を含まない）。

old/new の msData レコード配列から、レコード単位・項目単位の差分と
fullst（強化リスト）の明細比較行を組み立てる。Markdown への整形は
ms_data.reporting.report_msdata_diff 側が担う。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any
from collections.abc import Iterable


def index_by_name(
    records: Iterable[Any],
) -> tuple[dict[str, dict[str, Any]], Counter[str], int]:
    """レコードを MS名 でインデックス化。重複カウンタと不正レコード数を返す。"""
    indexed: dict[str, dict[str, Any]] = {}
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


def global_keys(records: Iterable[dict[str, Any]]) -> set[str]:
    """全レコードに現れるキーの和集合。"""
    keys: set[str] = set()
    for rec in records:
        keys.update(rec.keys())
    return keys


def diff_summary(
    old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]
) -> tuple[int, int, int, int, int]:
    """差分サマリ (旧件数, 新件数, 追加, 削除, 変更) を計算する。"""
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys
    changed = {k for k in common if old[k] != new[k]}
    return (len(old_keys), len(new_keys), len(added), len(removed), len(changed))


def diff_field_counts(
    old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]
) -> tuple[Counter[str], Counter[str], Counter[str]]:
    """共通レコード間で項目ごとの (変更, 追加, 削除) 件数を数える。"""
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


class _Sentinel:
    """キー削除を表すセンチネル。None と区別するために使用。"""

    pass


_DELETED = _Sentinel()


def get_changed_records_detail(
    old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]
) -> list[tuple[str, list[tuple[str, str, Any, Any]]]]:
    """変更レコードの詳細を取得。

    戻り値: [(機体名, [(操作種別, 項目名, 旧値, 新値), ...]), ...]
    操作種別: "added" | "removed" | "changed"
    """
    result: list[tuple[str, list[tuple[str, str, Any, Any]]]] = []
    common = set(old.keys()) & set(new.keys())

    for name in common:
        o = old[name]
        n = new[name]
        changes: list[tuple[str, str, Any, Any]] = []

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


def format_value_plain(value: Any, max_len: int = 120) -> str:
    """値をエスケープなしの表示用文字列にする（長い値は切り詰め）。"""
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


def fullst_point_text(item: Any) -> str:
    """fullst 項目の points を表示用文字列にする（未設定/null を区別）。"""
    if isinstance(item, dict):
        if "points" not in item:
            return "未設定"
        if item.get("points") is None:
            return "null"
        return format_value_plain(item.get("points"))
    return ""


def indexed_fullst_items(
    items: list[Any],
) -> dict[tuple[str, Any, int], tuple[int, Any]]:
    """fullst 配列を (名称, Lv, 出現回数) → (位置, 項目) で引ける索引にする。

    同名・同 Lv の重複に備えて出現回数をキーに含める。
    """
    counts: Counter[tuple[str, Any]] = Counter()
    indexed: dict[tuple[str, Any, int], tuple[int, Any]] = {}
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


def fullst_detail_rows(old_val: Any, new_val: Any) -> list[list[str]]:
    """fullst の old/new を突き合わせ、明細表の行（文字列リスト）を作る。"""
    old_items = old_val if isinstance(old_val, list) else []
    new_items = new_val if isinstance(new_val, list) else []
    old_index = indexed_fullst_items(old_items)
    new_index = indexed_fullst_items(new_items)
    keys = list(old_index.keys()) + [key for key in new_index if key not in old_index]
    keys.sort(
        key=lambda key: (
            0 if key in new_index else 1,
            new_index.get(key, old_index.get(key, (999, None)))[0],
            old_index.get(key, (999, None))[0],
        )
    )
    rows: list[list[str]] = []
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


def level_sort_key(name: str) -> tuple[int, str]:
    """LV 番号 → 名前順のソートキー（LV なしは末尾）。"""
    match = re.search(r"_LV(\d+)$", name)
    if match:
        return int(match.group(1)), name
    return 999, name


def base_ms_name(name: str) -> str:
    """ "ガンダム_LV3" → "ガンダム"（LV サフィックスの除去のみ）。"""
    return re.sub(r"_LV\d+$", "", name)


def ms_level_sort_key(name: str) -> tuple[str, int, str]:
    """基底名 → LV 番号 → 名前順のソートキー。"""
    lv, full_name = level_sort_key(name)
    return base_ms_name(name), lv, full_name
