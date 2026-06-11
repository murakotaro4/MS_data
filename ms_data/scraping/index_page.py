"""MS 一覧ページ（index）の HTML 解析。

属性別メニュー（汎用/強襲/支援）と Steam 版限定セクションから
機体名・詳細 URL・コスト・属性・更新経過時間を収集する。
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag

from ms_data.core.labels import clean_text
from ms_data.scraping.text_values import (
    absolute_url,
    extract_page_id,
    extract_updated_age,
    to_int,
)

# 一覧ページの属性別メニュー div の id と属性名の対応
SECTION_IDS = [
    ("menu_hanyou", "汎用"),
    ("menu_kyoushu", "強襲"),
    ("menu_sien", "支援"),
]


def append_index_items(
    results: list[dict[str, Any]],
    ul: Tag,
    *,
    cost: int | None,
    attr: str | None,
    seen_names: set[str],
) -> None:
    """ul 配下のリンクを index レコードとして results に追記する（名前重複は除外）。"""
    for a in ul.select("li > a[href]"):
        name = clean_text(a.get_text(" "))
        if not name or name in seen_names:
            continue
        href = absolute_url(a["href"])
        updated_age_text, updated_age_seconds = extract_updated_age(a.get("title", ""))
        results.append(
            {
                "name": name,
                "url": href,
                "page_id": extract_page_id(href),
                "cost": cost,
                "属性": attr,
                "updated_age_text": updated_age_text,
                "updated_age_seconds": updated_age_seconds,
            }
        )
        seen_names.add(name)


def parse_index(html: str) -> list[dict[str, Any]]:
    """一覧ページ HTML から全機体の index レコードを抽出する。

    属性別メニューは「h4(コスト見出し) → ul → li > a」の並びを前提とする。
    Steam 版限定機体はコスト・属性が一覧から取れないため None で収集する。
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for sec_id, attr in SECTION_IDS:
        sec = soup.find("div", id=sec_id)
        if not sec:
            continue
        # h4(コスト) → ul → li > a の並び
        for h4 in sec.find_all("h4"):
            cost = to_int(clean_text(h4.get_text(" ")))
            ul = h4.find_next_sibling("ul")
            if not ul:
                continue
            append_index_items(results, ul, cost=cost, attr=attr, seen_names=seen_names)

    etc = soup.find("div", id="menu_etc")
    if etc:
        for h3 in etc.find_all("h3"):
            if "Steam版限定" not in clean_text(h3.get_text(" ")):
                continue
            ul = h3.find_next_sibling("ul")
            if ul:
                append_index_items(
                    results, ul, cost=None, attr=None, seen_names=seen_names
                )
            break
    return results
