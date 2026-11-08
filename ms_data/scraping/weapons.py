"""機体詳細ページの HTML から兵装名（主兵装・副兵装）を抽出する。

atwiki の機体ページは次の構造を持つ（2026-11 の全量取得 602 ページで確認）:

- 主兵装: 「射撃」「格闘」の見出しの下に武器ページの include（div.plugin_include）があり、
  その中の表の見出し行が「武器名 | LV | 威力 | …」。本体行は先頭セルが武器名の th
  （rowspan で LV 行をまとめる）、続くセルが「LV1」「LV2」…。
- 副兵装: 兵装名そのものが見出し（h3/h4）で、直下に「LV | 威力 | …」の表、
  またはシールドの「（空） | LV1 | LV2 | …」の表が続く。

見出しの階層はページによって揺れる（「主兵装」「副兵装」の h2 が欠けて副兵装が
主兵装の h2 の下に並ぶページ、主兵装の h2 が無いページがある）。そのため見出しの
文言ではなく、表の形で主兵装・副兵装を判別する。

レア度はページに記載が無いため扱わない。
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from ms_data.core.labels import clean_text

KIND_MAIN = "主兵装"
KIND_SUB = "副兵装"

# 兵装の一覧を探す範囲の終わりを示す h2 見出し（数値情報 → 主兵装 → 副兵装 の後に続く）
_REGION_END_H2 = ("スキル情報", "強化リスト情報", "備考")

# 兵装名として扱わない見出し（数値情報の小見出しと主兵装の区分見出し）
_NON_WEAPON_HEADINGS = {
    "機体",
    "パーツスロット",
    "連撃補正",
    "格闘方向補正",
    "射撃",
    "格闘",
    "機体属性・出撃制限・環境適正",
}
_NON_WEAPON_PREFIXES = ("移動方向補正",)

# 主兵装の区分見出し
_MAIN_CATEGORIES = ("射撃", "格闘")

_LV_RE = re.compile(r"^LV\s*(\d+)$")


def _text(node: Any) -> str:
    if not hasattr(node, "get_text"):
        return ""
    return clean_text(node.get_text(" "))


def _level(text: str) -> int | None:
    m = _LV_RE.match(text)
    return int(m.group(1)) if m else None


def _region_headings(soup: BeautifulSoup) -> list[Tag]:
    """ページ本文（#pagetitle 以降）から、兵装一覧の範囲にある h2〜h4 を返す。

    サイドメニューにも見出しが多数あるため、必ず #pagetitle より後ろだけを見る。
    """
    title = soup.find(id="pagetitle")
    if title is None:
        return []
    headings: list[Tag] = []
    for h in title.find_all_next(["h2", "h3", "h4"]):
        if h.name == "h2" and _text(h) in _REGION_END_H2:
            break
        headings.append(h)
    return headings


def _section_nodes(h: Tag) -> list[Tag]:
    """見出し h の直後から、次の見出し（h1〜h6）までの兄弟要素を返す。"""
    nodes: list[Tag] = []
    cur = h.find_next_sibling()
    while cur is not None and not re.fullmatch(r"h[1-6]", cur.name or ""):
        nodes.append(cur)
        cur = cur.find_next_sibling()
    return nodes


def _tables(nodes: list[Tag]) -> list[Tag]:
    out: list[Tag] = []
    for node in nodes:
        if node.name == "table":
            out.append(node)
        out.extend(node.find_all("table"))
    return out


def _first_cells(tr: Tag) -> list[Tag]:
    return tr.find_all(["th", "td"], recursive=False)


def _is_main_table(table: Tag) -> bool:
    """見出し行の先頭が「武器名」の表（主兵装の一覧表）か。"""
    for tr in table.find_all("tr"):
        cells = _first_cells(tr)
        if cells:
            return _text(cells[0]) == "武器名"
    return False


def _main_weapons_from_table(table: Tag) -> list[tuple[str, list[int]]]:
    """主兵装の表から (武器名, [LV...]) を表の順に返す。"""
    weapons: list[tuple[str, list[int]]] = []
    current: list[int] | None = None
    for tr in table.find_all("tr"):
        if tr.find_parent("thead") is not None:
            continue
        cells = _first_cells(tr)
        if not cells:
            continue
        first = cells[0]
        if first.name == "th" and len(cells) >= 2:
            name = _text(first)
            lv = _level(_text(cells[1]))
            if name and lv is not None:
                current = [lv]
                weapons.append((name, current))
                continue
        # rowspan でまとめられた続きの LV 行（先頭セルが LVn）
        lv = _level(_text(first))
        if lv is not None and current is not None and lv not in current:
            current.append(lv)
    return weapons


def _sub_weapon_levels(tables: list[Tag]) -> list[int] | None:
    """副兵装の表から LV を読む。兵装の表でなければ None。

    - 通常: 見出し行が「LV | 威力 | …」で、各行の先頭セルが「LV1」「LV2」…
    - シールド: 見出し行が「（空） | LV1 | LV2 | …」
    """
    for table in tables:
        rows = [r for r in table.find_all("tr") if _first_cells(r)]
        if not rows:
            continue
        header = [_text(c) for c in _first_cells(rows[0])]
        if header and header[0] == "LV":
            levels: list[int] = []
            for tr in rows[1:]:
                lv = _level(_text(_first_cells(tr)[0]))
                if lv is not None and lv not in levels:
                    levels.append(lv)
            return levels
        header_levels = [lv for lv in (_level(c) for c in header[1:]) if lv is not None]
        if header_levels:
            return header_levels
    return None


def _is_non_weapon_heading(text: str) -> bool:
    return text in _NON_WEAPON_HEADINGS or text.startswith(_NON_WEAPON_PREFIXES)


def extract_weapons(html: str) -> list[dict[str, Any]]:
    """機体ページ HTML から兵装の一覧を返す。

    返り値は ``{"name", "kind", "category"?, "levels"}`` の辞書のリスト（ページ上の順）。
    ``category`` は主兵装の区分（射撃/格闘）で、判別できたときだけ入れる。
    同じ種類・同じ名前の兵装が複数回出た場合は 1 件にまとめ、LV を合算する。
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}

    def add(name: str, kind: str, levels: list[int], category: str | None) -> None:
        key = (kind, name)
        rec = index.get(key)
        if rec is None:
            rec = {"name": name, "kind": kind}
            if category:
                rec["category"] = category
            rec["levels"] = []
            index[key] = rec
            results.append(rec)
        for lv in levels:
            if lv not in rec["levels"]:
                rec["levels"].append(lv)
        rec["levels"].sort()

    for h in _region_headings(soup):
        heading = _text(h)
        tables = _tables(_section_nodes(h))
        main_tables = [t for t in tables if _is_main_table(t)]
        if main_tables:
            category = heading if heading in _MAIN_CATEGORIES else None
            for table in main_tables:
                for name, levels in _main_weapons_from_table(table):
                    add(name, KIND_MAIN, levels, category)
            continue
        if h.name == "h2" or not heading or _is_non_weapon_heading(heading):
            continue
        levels = _sub_weapon_levels(tables)
        if levels is not None:
            add(heading, KIND_SUB, levels, None)
    return results
