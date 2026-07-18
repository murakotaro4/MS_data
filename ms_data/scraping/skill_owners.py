"""atwiki の厳格テーブル方式によるスキルオーナー抽出。"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from ms_data.scraping.text_values import normalize_symbol_text

_norm = normalize_symbol_text


# PC表示を強制して取得の安定性を上げる
SKILL_URL = "https://w.atwiki.jp/battle-operation2/pages/179.html?pc_mode=1"

_RE_ANCHOR = re.compile(r"^(能力UP「[^」]+」)\s*LV(\d+)$")


def _role_from_text(text: str) -> str | None:
    """見出しセルの文言から属性（強襲/汎用/支援）を推定する。"""
    if "強" in text:
        return "強襲"
    if "汎" in text:
        return "汎用"
    if "支" in text:
        return "支援"
    return None


def _owner_links_from_cells(cells: list[Tag]) -> list[dict[str, str]]:
    """td 群からリンク（機体名と href）を収集する。"""
    owners: list[dict[str, str]] = []
    for td in cells:
        for anchor in td.find_all("a"):
            text = _norm(anchor.get_text(" "))
            href = anchor.get("href") or ""
            if text:
                owners.append({"name": text, "href": href})
    return owners


def _candidate_owner_tables(soup: BeautifulSoup) -> list[Tag]:
    """所持機体逆引きらしいテーブル（スキルアンカー + 属性行を持つ）を探す。"""
    candidates: list[Tag] = []
    for tbl in soup.find_all("table"):
        ok = False
        for anchor in tbl.find_all("a"):
            aid = (anchor.get("id") or "").strip()
            if not aid or not _RE_ANCHOR.match(aid):
                continue
            th = anchor.find_parent("th")
            tr = th.find_parent("tr") if th else None
            nxt = tr.find_next_sibling("tr") if tr else None
            th_role = nxt.find("th") if nxt else None
            role_txt = _norm(th_role.get_text(" ")) if th_role else ""
            if any(key in role_txt for key in ("強", "汎", "支")):
                ok = True
                break
        if ok:
            candidates.append(tbl)
    return candidates


def _find_owner_section_tables(soup: BeautifulSoup) -> list[Tag]:
    """「所持機体 逆引き」見出し直後のテーブル群を返す（見出しが無ければ推定）。"""
    header = None
    for tag in soup.find_all(["h2", "h3", "h4"]):
        text = _norm(tag.get_text(" "))
        if "所持機体" in text and "逆引き" in text:
            header = tag
            break

    if not header:
        return _candidate_owner_tables(soup)

    target_tables: list[Tag] = []
    cur = header
    while True:
        cur = cur.find_next_sibling()
        if not cur:
            break
        name = getattr(cur, "name", "")
        if name in ("h2", "h3", "h4"):
            break
        if name == "table":
            target_tables.append(cur)
    return target_tables or _candidate_owner_tables(soup)


def _extract_owner_anchors(target_tables: list[Tag]) -> list[tuple[str, int, Tag]]:
    """逆引きテーブルからスキルアンカー（スキル名, LV, 見出し行）を列挙する。"""
    anchors: list[tuple[str, int, Tag]] = []
    for tbl in target_tables:
        for anchor in tbl.find_all("a"):
            aid = (anchor.get("id") or "").strip()
            if not aid:
                continue
            match = _RE_ANCHOR.match(aid)
            if not match:
                continue
            name = match.group(1).replace("AREUS", "ZEUS")
            level = int(match.group(2))
            th = anchor.find_parent("th")
            tr = th.find_parent("tr") if th else None
            if tr:
                anchors.append((name, level, tr))
    return anchors


def _collect_anchor_row_owners(tr: Tag) -> tuple[str | None, list[dict[str, str]]]:
    """アンカー行自身から属性とその行の所持機体リンクを取り出す。"""
    anchor_th = tr.find("th")
    role_th = anchor_th.find_next_sibling("th") if anchor_th else None
    role = _role_from_text(_norm(role_th.get_text(" "))) if role_th else None
    if not role or not role_th:
        return role, []

    td_list: list[Tag] = []
    td = role_th.find_next_sibling("td")
    if td:
        td_list.append(td)
        td2 = td.find_next_sibling("td")
        if td2:
            td_list.append(td2)
    return role, _owner_links_from_cells(td_list)


def _collect_owner_block(
    start_tr: Tag, stop_tr: Tag | None
) -> dict[str, list[dict[str, str]]]:
    """アンカー行から次のアンカー直前までの所持機体を属性別に集める。"""
    owners_by_role: dict[str, list[dict[str, str]]] = {
        "強襲": [],
        "汎用": [],
        "支援": [],
    }
    current_role, line_owners = _collect_anchor_row_owners(start_tr)
    if current_role and line_owners:
        owners_by_role[current_role].extend(line_owners)

    cur_tr = start_tr
    while True:
        cur_tr = cur_tr.find_next_sibling("tr")
        if not cur_tr or (stop_tr and cur_tr is stop_tr):
            break
        th_role = cur_tr.find("th")
        if th_role and th_role.find("a", id=True):
            break
        role_txt = _norm(th_role.get_text(" ")) if th_role else ""
        next_role = _role_from_text(role_txt)
        if next_role:
            current_role = next_role
        line_owners = _owner_links_from_cells(cur_tr.find_all("td"))
        if current_role and line_owners:
            owners_by_role[current_role].extend(line_owners)
    return owners_by_role


def extract_skill_owners_rows_table(html: str) -> dict[str, Any]:
    """ページ下部の『所持機体 逆引き一覧』セクションに限定して、行として厳格抽出する。

    出力: { source, rows: [ {skill, level, role, owners: [{name, href}], block_index} ] }
    - block_index: セクション内での並び順インデックス（デバッグ/監査用）
    - role: "強襲"/"汎用"/"支援" のいずれか
    """
    soup = BeautifulSoup(html, "lxml")
    target_tables = _find_owner_section_tables(soup)
    if not target_tables:
        return {"source": SKILL_URL, "rows": []}

    rows_out: list[dict[str, Any]] = []
    anchors = _extract_owner_anchors(target_tables)

    for idx, (name, level, tr) in enumerate(anchors):
        stop_tr = anchors[idx + 1][2] if (idx + 1 < len(anchors)) else None
        owners_by_role = _collect_owner_block(tr, stop_tr)
        for role, owners in owners_by_role.items():
            rows_out.append(
                {
                    "skill": name,
                    "level": level,
                    "role": role,
                    "owners": owners,
                    "block_index": idx,
                }
            )

    return {"source": SKILL_URL, "rows": rows_out}
