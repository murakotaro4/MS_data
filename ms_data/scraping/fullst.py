"""強化リスト（fullst）テーブルの解析と LV 間フォールバック。

詳細ページの「強化リスト情報」テーブルは、強化リスト名 × 強化 LV の行に
MS レベルごとの必要強化値が並ぶ構造。本モジュールは
1) テーブルを行単位で収集し（_collect_fullst_rows）、
2) MS レベルごとの fullst 項目リストへ集計し（parse_fullst_by_ms_level）、
3) 表に記載のない MS レベルへは前の LV の内容を points=None で引き継ぐ
   （apply_fullst_fallback）。

内部表現のメモ:
- `_section`: "normal"（通常枠）/ "upper"（上限開放枠）。出力前に除去される
  内部キーで、同名リストの枠違いを区別するために持ち回る。
- `_skip_fallback`: セルが "-"（明示的に対象外）だった項目の印。
  フォールバック複製の対象から除外する。
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from bs4 import BeautifulSoup, Tag

from ms_data.core.labels import clean_text
from ms_data.scraping.text_values import to_int


class FullstRow(NamedTuple):
    """強化リストテーブルの1行分（強化リスト名 × 強化LV）。"""

    name: str
    fullst_lv: int
    section: str  # "normal" | "upper"（上限開放）
    points_by_ms: dict[int, int]  # MSレベル → 必要強化値
    present_ms_levels: set[int]  # セルが存在した MS レベル
    blocked_ms_levels: set[int]  # セルが "-"（対象外）だった MS レベル


# 強化リスト名の候補から除外する定型見出し（部分一致）
_FULLST_HEADER_WORDS = (
    "強化リスト",
    "上限開放",
    "リスト名",
    "MSレベル毎必要強化値",
    "効果",
)
_LV_LABEL_RE = re.compile(r"LV\d+|Lv\d+|Lv", re.IGNORECASE)
_FULLST_LV_RE = re.compile(r"Lv(\d+)", re.IGNORECASE)
_BLOCKED_CELL_VALUES = frozenset({"-", "－"})
FORCED_SORTIE = "強行出撃"


def find_fullst_table(soup: BeautifulSoup) -> Tag | None:
    """「強化リスト情報」見出し（h2/h3）直後の table を返す。無ければ None。"""
    for hx in soup.find_all(["h2", "h3"]):
        if "強化リスト情報" in clean_text(hx.get_text(" ")):
            table = hx.find_next("table")
            return table if isinstance(table, Tag) else None
    return None


def _row_list_name(th_texts: list[str]) -> str | None:
    """行見出しのうち LV 表記でも定型見出しでもない最初のテキスト（強化リスト名）。"""
    for txt in th_texts:
        if not txt:
            continue
        if any(word in txt for word in _FULLST_HEADER_WORDS):
            continue
        if _LV_LABEL_RE.fullmatch(txt):
            continue
        return txt
    return None


def _row_fullst_lv(th_texts: list[str]) -> int | None:
    """行見出しから強化 LV（`Lv3` 等）を読む。無ければ None。"""
    for txt in th_texts:
        match = _FULLST_LV_RE.fullmatch(txt)
        if match:
            return int(match.group(1))
    return None


def _parse_points_cells(
    tds: list[Tag], ms_levels: list[int], *, list_name: str
) -> tuple[dict[int, int], set[int], set[int]]:
    """数値セル列を (points_by_ms, present_ms_levels, blocked_ms_levels) に読む。

    末尾セルは「効果」列のため数値対象から外す。数値セルは MS レベル順に
    並ぶ前提（LV1 が先頭セル）。"-" は対象外（blocked）だが「強行出撃」は
    例外として blocked 扱いしない。
    """
    numeric_cells = tds[:-1]
    points_by_ms: dict[int, int] = {}
    present_ms_levels: set[int] = set()
    blocked_ms_levels: set[int] = set()
    for ms_lv in ms_levels:
        idx = ms_lv - 1
        if not 0 <= idx < len(numeric_cells):
            continue
        present_ms_levels.add(ms_lv)
        raw_value = clean_text(numeric_cells[idx].get_text(" "))
        val = to_int(raw_value)
        if val is not None:
            points_by_ms[ms_lv] = val
        elif raw_value in _BLOCKED_CELL_VALUES and FORCED_SORTIE not in list_name:
            blocked_ms_levels.add(ms_lv)
    return points_by_ms, present_ms_levels, blocked_ms_levels


def _collect_fullst_rows(soup: BeautifulSoup, ms_levels: list[int]) -> list[FullstRow]:
    """「強化リスト情報」テーブルを走査し、有効な行を FullstRow として収集する。

    強化リスト名は行見出しから読み、以降の行にも引き継ぐ（rowspan 相当の
    構造のため）。「上限開放」の区切り行を境に section を "upper" へ切り替える。
    必要強化値も "-" セルも無い行は採用しない（「強行出撃」は例外）。
    """
    table = find_fullst_table(soup)
    if table is None:
        return []

    rows: list[FullstRow] = []
    current_name: str | None = None
    section = "normal"
    for tr in table.find_all("tr"):
        if clean_text(tr.get_text(" ")) == "上限開放":
            section = "upper"
            current_name = None
            continue

        ths = tr.find_all("th")
        if not ths:
            continue
        th_texts = [clean_text(th.get_text(" ")) for th in ths]
        list_name = _row_list_name(th_texts)
        if list_name is not None:
            current_name = list_name
        fullst_lv = _row_fullst_lv(th_texts)

        tds = tr.find_all("td")
        if not tds or current_name is None or fullst_lv is None:
            continue

        points_by_ms, present_ms_levels, blocked_ms_levels = _parse_points_cells(
            tds, ms_levels, list_name=current_name
        )
        if (
            not points_by_ms
            and FORCED_SORTIE not in current_name
            and not blocked_ms_levels
        ):
            continue
        rows.append(
            FullstRow(
                name=current_name,
                fullst_lv=fullst_lv,
                section=section,
                points_by_ms=points_by_ms,
                present_ms_levels=present_ms_levels,
                blocked_ms_levels=blocked_ms_levels,
            )
        )
    return rows


def parse_fullst_by_ms_level(
    soup: BeautifulSoup, ms_levels: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """強化リストテーブルを MS レベルごとの fullst 項目リストに集計する。

    同名リストは強化 LV の最小と最大のみ残す（中間 LV は msData に持たない方針）。
    「強行出撃」は必要強化値が無くてもセルが存在すれば points=None で採用する。
    """
    rows = _collect_fullst_rows(soup, ms_levels)
    if not rows:
        return {}

    by_ms_level: dict[int, list[dict[str, Any]]] = {lv: [] for lv in ms_levels}
    for ms_lv in ms_levels:
        by_name: dict[tuple[str, str], list[tuple[int, int | None, bool]]] = {}
        for row in rows:
            pts = row.points_by_ms.get(ms_lv)
            skip_fallback = False
            if (
                pts is None
                and FORCED_SORTIE not in row.name
                and ms_lv in row.blocked_ms_levels
            ):
                skip_fallback = True
            elif pts is None and (
                FORCED_SORTIE not in row.name or ms_lv not in row.present_ms_levels
            ):
                continue
            by_name.setdefault((row.section, row.name), []).append(
                (row.fullst_lv, pts, skip_fallback)
            )

        items: list[dict[str, Any]] = []
        for (section, nm), lst in by_name.items():
            lst_sorted = sorted(lst, key=lambda x: x[0])
            keep = []
            if lst_sorted:
                keep.append(lst_sorted[0])
            if len(lst_sorted) > 1 and lst_sorted[-1] != lst_sorted[0]:
                keep.append(lst_sorted[-1])
            for flv, pts, skip_fallback in keep:
                item = {"name": nm, "level": flv, "points": pts, "_section": section}
                if skip_fallback:
                    item["_skip_fallback"] = True
                items.append(item)
        items.sort(key=fullst_sort_key)
        if items:
            by_ms_level[ms_lv] = items
    return {k: v for k, v in by_ms_level.items() if v}


def fullst_sort_key(item: dict[str, Any]) -> tuple[int, bool, int]:
    """fullst 項目の表示順キー（強行出撃 → points なし → points 昇順）。"""
    name = str(item.get("name", ""))
    points = item.get("points")
    point_value = points if isinstance(points, int) else 0
    return (0 if name == FORCED_SORTIE else 1, points is not None, point_value)


def fullst_entry_key(item: dict[str, Any]) -> tuple[Any, Any, Any]:
    """同一項目の判定キー（枠・名前・強化LV）。"""
    return item.get("_section"), item.get("name"), item.get("level")


def fullst_section_name_key(item: dict[str, Any]) -> tuple[Any, Any]:
    """同一リストの判定キー（枠・名前。強化LV違いを同一視）。"""
    return item.get("_section"), item.get("name")


def copy_fullst_with_null_points(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """前 LV からの引き継ぎ用に points を None に落としたコピーを作る。"""
    copied = []
    for e in items:
        if not isinstance(e, dict) or e.get("_skip_fallback"):
            continue
        item = {"name": e.get("name"), "level": e.get("level"), "points": None}
        if "_section" in e:
            item["_section"] = e.get("_section")
        copied.append(item)
    return copied


def strip_skip_fallback_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """_skip_fallback の付いた項目を除去する（_section は内部用に保持）。"""
    stripped = []
    for e in items:
        if not isinstance(e, dict) or e.get("_skip_fallback"):
            continue
        item = {
            "name": e.get("name"),
            "level": e.get("level"),
            "points": e.get("points"),
        }
        if "_section" in e:
            item["_section"] = e.get("_section")
        stripped.append(item)
    return stripped


def public_fullst_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """内部キー（_section/_skip_fallback）を落とした公開形に変換する。"""
    return [
        {"name": e.get("name"), "level": e.get("level"), "points": e.get("points")}
        for e in items
        if isinstance(e, dict) and not e.get("_skip_fallback")
    ]


def merge_fullst_with_previous(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """現 LV の項目に、前 LV にだけ存在したリストを points=None で補完する。"""
    if not previous:
        return current

    current_keys = {fullst_entry_key(e) for e in current if isinstance(e, dict)}
    current_section_names = {
        fullst_section_name_key(e)
        for e in current
        if isinstance(e, dict) and not e.get("_skip_fallback")
    }
    copied_missing = [
        e
        for e in copy_fullst_with_null_points(previous)
        if fullst_entry_key(e) not in current_keys
        and fullst_section_name_key(e) not in current_section_names
    ]
    merged = copied_missing + current
    merged.sort(key=fullst_sort_key)
    return merged


def apply_fullst_fallback(
    per_level: dict[int, dict[str, Any]],
    levels: list[int],
    fullst_by_lv: dict[int, list[dict[str, Any]]],
) -> None:
    """MS レベル昇順に fullst を確定し、表に無い LV へ前 LV の内容を引き継ぐ。"""
    last_effective: list[dict[str, Any]] = []
    for lv in sorted(levels):
        current = fullst_by_lv.get(lv) or []
        use_current = bool(current)

        if use_current:
            merged = merge_fullst_with_previous(current, last_effective)
            effective = strip_skip_fallback_entries(merged)
            if effective:
                per_level[lv]["fullst"] = public_fullst_entries(effective)
                last_effective = effective
            continue

        if last_effective:
            copied = copy_fullst_with_null_points(last_effective)
            if copied:
                per_level[lv]["fullst"] = public_fullst_entries(copied)
                last_effective = copied
