#!/usr/bin/env python3
"""
バトオペ2 atwiki からモビルスーツ一覧と各機体ステータスをスクレイピングし、
正規化済みのレコードを生成するユーティリティ（uv 前提）。

サブコマンド
- index   : 一覧ページから (name, url, cost, 属性) を収集
- details : index出力を入力にし、各詳細ページからLVごとのステータスを抽出
- all     : index → details まで一気通貫で実行

使い方例
- 一覧のみ:
  uv run python scripts/scrape_msdata.py index \
      --url https://w.atwiki.jp/battle-operation2/pages/377.html \
      --out cache/index.json
- 詳細スクレイプ:
  uv run python scripts/scrape_msdata.py details \
      --in cache/index.json \
      --out cache/details.jsonl \
      --rate 1.0
- 一気通貫（出力JSONL）:
  uv run python scripts/scrape_msdata.py all \
      --out cache/details.jsonl

注意
- レート制限を守ってください（既定: 1 req/sec）。
- 取得HTMLの構造は変わる可能性があります。CSSセレクタは `SELECTORS` を参照。
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag

from scripts.cache_http import CacheConfig, CacheHTTP
from scripts.label_utils import (
    FIELD_MAP,
    clean_text,
    normalize_row_label,
)

ATWIKI_BASE = "https://w.atwiki.jp"
INDEX_URL = "https://w.atwiki.jp/battle-operation2/pages/377.html"
MS_NAME_WITH_LEVEL = re.compile(r"^(?P<base>.+)_LV(?P<level>\d+)$")
PAGE_ID_RE = re.compile(r"/pages/(?P<page_id>\d+)\.html$")
UPDATED_AGE_RE = re.compile(r"\((?P<value>\d+)(?P<unit>[mhd])\)\s*$")


def absolute_url(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return ATWIKI_BASE + href
    if href.startswith("http"):
        return href
    return ATWIKI_BASE + "/" + href.lstrip("/")


def extract_page_id(url: str) -> Optional[int]:
    match = PAGE_ID_RE.search(url)
    if not match:
        return None
    return int(match.group("page_id"))


def extract_updated_age(title: str) -> tuple[Optional[str], Optional[int]]:
    title = clean_text(title)
    match = UPDATED_AGE_RE.search(title)
    if not match:
        return None, None
    value = int(match.group("value"))
    unit = match.group("unit")
    factor = {"m": 60, "h": 3600, "d": 86400}[unit]
    return f"{value}{unit}", value * factor


def extract_ms_base_name(name: str) -> Optional[str]:
    match = MS_NAME_WITH_LEVEL.match(name)
    if not match:
        return None
    return match.group("base")


def parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def find_latest_provenance(
    reports_dir: Path,
) -> tuple[Optional[Path], Optional[Dict[str, Any]]]:
    latest_path: Optional[Path] = None
    latest_data: Optional[Dict[str, Any]] = None
    latest_generated_at: Optional[datetime] = None
    for path in sorted(reports_dir.glob("provenance_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            generated_at = parse_iso_datetime(str(data["generated_at"]))
        except Exception:
            continue
        if latest_generated_at is None or generated_at > latest_generated_at:
            latest_generated_at = generated_at
            latest_path = path
            latest_data = data
    return latest_path, latest_data


def load_msdata_base_index(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for record in data:
        if not isinstance(record, dict):
            continue
        ms_name = record.get("MS名")
        if not isinstance(ms_name, str):
            continue
        base_name = extract_ms_base_name(ms_name)
        if not base_name or base_name in result:
            continue
        result[base_name] = {
            "cost": record.get("コスト"),
            "attr": record.get("属性"),
            "wiki_url": record.get("wiki_url"),
        }
    return result


def load_detail_fetch_state(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    items = data.get("items")
    if isinstance(items, dict):
        return {
            str(url): entry for url, entry in items.items() if isinstance(entry, dict)
        }

    # Backward-compatible shape for ad-hoc state files: {url: {fetched_at: ...}}.
    return {
        str(url): entry
        for url, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("fetched_at"), str)
    }


def write_detail_fetch_state(
    path: Path, items: Dict[str, Dict[str, Any]], generated_at: datetime
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "items": dict(sorted(items.items())),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def remember_detail_fetch(
    detail_state: Dict[str, Dict[str, Any]],
    url: str,
    item: Dict[str, Any],
    meta: Dict[str, Any],
) -> None:
    fetched_at = meta.get("fetched_at")
    if not isinstance(fetched_at, str):
        fetched_at = datetime.now(timezone.utc).isoformat()
    detail_state[url] = {
        "name": item.get("name"),
        "page_id": item.get("page_id") or extract_page_id(url),
        "fetched_at": fetched_at,
        "http_status": meta.get("http_status"),
        "semantic_sha256": meta.get("semantic_sha256"),
    }


def _detail_state_fetched_at(
    detail_fetch_state: Dict[str, Dict[str, Any]], url: str
) -> Optional[datetime]:
    entry = detail_fetch_state.get(url)
    if not isinstance(entry, dict):
        return None
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, str):
        return None
    try:
        return parse_iso_datetime(fetched_at)
    except (TypeError, ValueError):
        return None


def select_changed_index_items(
    items: List[Dict[str, Any]],
    *,
    previous_generated_at: Optional[datetime],
    previous_msdata_index: Dict[str, Dict[str, Any]],
    now: Optional[datetime] = None,
    freshness_window_seconds: int = 3600,
    force_full: bool = False,
    min_age_coverage: float = 0.95,
    detail_fetch_state: Optional[Dict[str, Dict[str, Any]]] = None,
    stale_detail_seconds: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    total_count = len(items)
    age_count = sum(
        1 for item in items if isinstance(item.get("updated_age_seconds"), int)
    )
    age_coverage = (age_count / total_count) if total_count else 1.0
    stale_detail_enabled = (
        detail_fetch_state is not None
        and isinstance(stale_detail_seconds, int)
        and stale_detail_seconds > 0
    )

    meta: Dict[str, Any] = {
        "fast_path": True,
        "fallback_reason": "",
        "candidate_count": 0,
        "total_count": total_count,
        "age_coverage": age_coverage,
        "freshness_window_seconds": freshness_window_seconds,
        "previous_generated_at": (
            previous_generated_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if previous_generated_at
            else None
        ),
        "elapsed_seconds": None,
        "threshold_seconds": None,
        "stale_detail_seconds": stale_detail_seconds if stale_detail_enabled else None,
        "detail_fetch_state_count": len(detail_fetch_state or {}),
        "reason_counts": {},
    }

    if force_full:
        meta["fast_path"] = False
        meta["fallback_reason"] = "force_full"
        meta["candidate_count"] = total_count
        return items, meta

    if previous_generated_at is None:
        meta["fast_path"] = False
        meta["fallback_reason"] = "missing_previous_provenance"
        meta["candidate_count"] = total_count
        return items, meta

    if age_coverage < min_age_coverage:
        meta["fast_path"] = False
        meta["fallback_reason"] = "low_age_coverage"
        meta["candidate_count"] = total_count
        return items, meta

    elapsed_seconds = max(
        0,
        int((now_utc - previous_generated_at.astimezone(timezone.utc)).total_seconds()),
    )
    threshold_seconds = elapsed_seconds + freshness_window_seconds
    meta["elapsed_seconds"] = elapsed_seconds
    meta["threshold_seconds"] = threshold_seconds

    selected: List[Dict[str, Any]] = []
    reason_counts: Dict[str, int] = {}
    for item in items:
        reasons: List[str] = []
        name = item.get("name")
        existing = previous_msdata_index.get(name) if isinstance(name, str) else None
        if existing is None:
            reasons.append("new_name")
        else:
            item_cost = item.get("cost")
            if isinstance(item_cost, int) and existing.get("cost") != item_cost:
                reasons.append("cost_changed")
            item_attr = item.get("属性")
            if (
                isinstance(item_attr, str)
                and item_attr
                and existing.get("attr") != item_attr
            ):
                reasons.append("attr_changed")
            current_url = item.get("url")
            if (
                isinstance(current_url, str)
                and isinstance(existing.get("wiki_url"), str)
                and existing.get("wiki_url") != current_url
            ):
                reasons.append("wiki_url_changed")

        age_seconds = item.get("updated_age_seconds")
        if age_seconds is None:
            reasons.append("missing_age")
        elif age_seconds <= threshold_seconds:
            reasons.append("recent_update")

        url = item.get("url")
        if stale_detail_enabled and isinstance(url, str):
            fetched_at = _detail_state_fetched_at(detail_fetch_state or {}, url)
            if fetched_at is None:
                reasons.append("stale_detail_cache")
            else:
                detail_age_seconds = int(
                    max(
                        0,
                        (now_utc - fetched_at.astimezone(timezone.utc)).total_seconds(),
                    )
                )
                if detail_age_seconds >= int(stale_detail_seconds or 0):
                    reasons.append("stale_detail_cache")

        if reasons:
            selected_item = dict(item)
            selected_item["change_reasons"] = reasons
            selected.append(selected_item)
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    meta["candidate_count"] = len(selected)
    meta["reason_counts"] = reason_counts
    return selected, meta


def get_client(timeout: float = 30.0) -> httpx.Client:
    headers = {"User-Agent": "msdata-scraper/0.1 (+https://github.com/; contact=local)"}
    # Cloudflare対策: cloudscraper が利用可能な場合は優先して使う。
    if os.getenv("MSDATA_HTTP_CLIENT", "cloudscraper").lower() == "cloudscraper":
        try:
            import cloudscraper

            scraper = cloudscraper.create_scraper()
            scraper.headers.update(headers)
            scraper.request = functools.partial(scraper.request, timeout=timeout)
            return scraper
        except Exception as exc:  # cloudscraperが使えない場合は httpx へフォールバック
            print(
                f"[warn] cloudscraper unavailable, fallback to httpx: {exc}",
                file=sys.stderr,
            )
    return httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)


def parse_ttl(s: str) -> int:
    """ "7d", "72h", "3600s" などを秒に変換。単位なしは秒と解釈。"""
    s = str(s).strip().lower()
    if not s:
        return 7 * 24 * 3600
    m = re.fullmatch(r"(\d+)([smhd]?)", s)
    if not m:
        return int(float(s))
    val = int(m.group(1))
    unit = m.group(2) or "s"
    if unit == "s":
        return val
    if unit == "m":
        return val * 60
    if unit == "h":
        return val * 3600
    if unit == "d":
        return val * 86400
    return val


def to_int(text: str) -> Optional[int]:
    if text is None:
        return None
    # 全角→半角、カンマや単位除去
    t = (
        text.replace(",", "")
        .replace("％", "%")
        .replace("秒", "")
        .replace("度/秒", "")
        .replace("[度/秒]", "")
        .replace("\xa0", " ")
    )
    m = re.search(r"-?\d+", t)
    return int(m.group(0)) if m else None


def symbol_to_bool(s: str) -> Optional[bool]:
    t = clean_text(s)
    # 記号/語を可否にマップ
    true_syms = {"◎", "◯", "○", "〇", "△", "可", "可能", "yes", "可○"}
    false_syms = {"×", "不可", "不可能", "no"}
    if t in true_syms:
        return True
    if t in false_syms:
        return False
    # テキスト内に含まれる場合
    if any(x in t for x in ["不可", "×"]):
        return False
    if any(x in t for x in ["可", "可能", "◯", "○", "〇", "◎", "△"]):
        return True
    return None


def parse_deployment(soup: BeautifulSoup) -> Dict[str, Optional[bool]]:
    """出撃可否（地上/宇宙）を推定して返す。

    - 優先: 「〜出撃のみ」系の明示文
    - 次点: 記号/語（◯/×/可/不可/△）の行や表
    - 何も見つからなければ None
    """

    def section_text(h: Tag) -> str:
        parts: List[str] = []
        # 近傍の数要素を収集
        cur = h
        for _ in range(6):
            cur = cur.find_next_sibling()
            if not cur or getattr(cur, "name", "").startswith("h"):
                break
            parts.append(cur.get_text(" ") if hasattr(cur, "get_text") else str(cur))
        return clean_text(" \n ".join(parts))

    def scan_tables(h: Tag) -> Tuple[Optional[bool], Optional[bool]]:
        gz = None
        uz = None
        # 近傍の最初のtableを数個まで探索
        seen = 0
        cur = h
        while seen < 3 and cur:
            cur = cur.find_next_sibling()
            if not cur:
                break
            if cur.name == "table":
                seen += 1
                for tr in cur.find_all("tr"):
                    cells = [
                        clean_text(x.get_text(" "))
                        for x in tr.find_all(["th", "td"])
                        if clean_text(x.get_text(" "))
                    ]
                    if not cells:
                        continue
                    # 形式1: 地上 | ◯    宇宙 | ×
                    for i, c in enumerate(cells):
                        if "地上" in c and i + 1 < len(cells):
                            v = symbol_to_bool(cells[i + 1])
                            if v is not None:
                                gz = v if gz is None else gz
                        if "宇宙" in c and i + 1 < len(cells):
                            v = symbol_to_bool(cells[i + 1])
                            if v is not None:
                                uz = v if uz is None else uz
        return gz, uz

    result: Dict[str, Optional[bool]] = {"出撃_地上可": None, "出撃_宇宙可": None}
    # 0) atwiki 固有のIDにエンコードされているケース: label_sortie_{G|n}_{S|n}
    lab = soup.find(id=re.compile(r"^label_sortie_([GSn])_([GSn])$"))
    if lab and hasattr(lab, 'get'):
        m = re.match(r"label_sortie_([GSn])_([GSn])", lab.get('id', ''))
        if m:
            g, s = m.group(1), m.group(2)
            result["出撃_地上可"] = True if g == 'G' else (False if g == 'n' else None)
            result["出撃_宇宙可"] = True if s == 'S' else (False if s == 'n' else None)
            return result
    # 対象となる見出しを探す
    headers: List[Tag] = []
    for hx in soup.find_all(["h2", "h3", "h4"]):
        txt = clean_text(hx.get_text(" "))
        if any(k in txt for k in ("出撃", "環境適正", "機体属性・出撃制限・環境適正")):
            headers.append(hx)
    # 1) 明示文（のみ）
    for h in headers:
        txt = section_text(h)
        t = txt.replace("：", ":")
        # 地上のみ/宇宙のみ
        if "地上" in t and "のみ" in t:
            result["出撃_地上可"], result["出撃_宇宙可"] = True, False
            return result
        if "宇宙" in t and "のみ" in t:
            result["出撃_地上可"], result["出撃_宇宙可"] = False, True
            return result
    # 2) 記号表記
    for h in headers:
        txt = section_text(h)
        # パターン: 地上:◯ 宇宙:×
        m1 = re.search(r"地上\s*[:：]\s*([◎◯○〇△×不可可])", txt)
        m2 = re.search(r"宇宙\s*[:：]\s*([◎◯○〇△×不可可])", txt)
        gz = symbol_to_bool(m1.group(1)) if m1 else None
        uz = symbol_to_bool(m2.group(1)) if m2 else None
        if gz is not None or uz is not None:
            result["出撃_地上可"], result["出撃_宇宙可"] = gz, uz
            return result
        # テーブル走査
        tgz, tuz = scan_tables(h)
        if tgz is not None or tuz is not None:
            result["出撃_地上可"], result["出撃_宇宙可"] = tgz, tuz
            return result
    return result


def parse_env_suitability(soup: BeautifulSoup) -> Dict[str, bool]:
    """環境適正（地上/宇宙/水中）を抽出。見つからないものは False。

    優先: atwiki 固有ID label_env_{G|n}_{S|n}(_{W|n})
    フォールバック: 文言/表からの記号解釈（簡易）
    """
    result = {"環境適正_地上": False, "環境適正_宇宙": False, "環境適正_水中": False}
    # 1) 固有ID
    lab = soup.find(id=re.compile(r"^label_env_([Gn])_([Sn])(?:_([Wn]))?$"))
    if lab and hasattr(lab, "get"):
        m = re.match(r"label_env_([Gn])_([Sn])(?:_([Wn]))?", lab.get("id", ""))
        if m:
            g, s, w = m.group(1), m.group(2), m.group(3)
            result["環境適正_地上"] = g == "G"
            result["環境適正_宇宙"] = s == "S"
            result["環境適正_水中"] = (w == "W") if w is not None else False
            return result

    # 2) テキスト/表（簡易フォールバック）
    def section_text(h: Tag) -> str:
        parts: List[str] = []
        cur = h
        for _ in range(6):
            cur = cur.find_next_sibling()
            if not cur or getattr(cur, "name", "").startswith("h"):
                break
            parts.append(cur.get_text(" ") if hasattr(cur, "get_text") else str(cur))
        return clean_text(" \n ".join(parts))

    headers: List[Tag] = []
    for hx in soup.find_all(["h2", "h3", "h4"]):
        txt = clean_text(hx.get_text(" "))
        if "環境適正" in txt or "機体属性・出撃制限・環境適正" in txt:
            headers.append(hx)
    for h in headers:
        txt = section_text(h)

        def find_bool(label: str) -> Optional[bool]:
            m = re.search(label + r"\s*[:：]\s*([^\s]+)", txt)
            if m:
                return symbol_to_bool(m.group(1))
            return None

        gz = find_bool("地上")
        uz = find_bool("宇宙")
        wz = find_bool("水中")
        if gz is not None:
            result["環境適正_地上"] = bool(gz)
        if uz is not None:
            result["環境適正_宇宙"] = bool(uz)
        if wz is not None:
            result["環境適正_水中"] = bool(wz)
        if gz is not None or uz is not None or wz is not None:
            break
    return result


# ===============
# Index parsing
# ===============

SECTION_IDS = [
    ("menu_hanyou", "汎用"),
    ("menu_kyoushu", "強襲"),
    ("menu_sien", "支援"),
]


def append_index_items(
    results: List[Dict[str, Any]],
    ul: Tag,
    *,
    cost: Optional[int],
    attr: Optional[str],
    seen_names: set[str],
) -> None:
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


def parse_index(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict[str, Any]] = []
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


# ===============
# Detail parsing
# ===============


def extract_title(soup: BeautifulSoup) -> str:
    title = soup.title.get_text(" ") if soup.title else ""
    # 例: "F90［MZ仕様］ - 機動戦士..."
    return title.split(" - ")[0].strip()


def levels_from_table(table: Tag) -> List[int]:
    # 1) thead優先
    thead = table.find("thead")
    headers = []
    if thead:
        headers = [clean_text(th.get_text(" ")) for th in thead.find_all("th")]
    # 2) thead が無い/空なら、最初に LV を含む行の th 群を使う
    if not headers:
        for tr in table.find_all("tr"):
            ths = tr.find_all("th")
            if not ths:
                continue
            texts = [clean_text(th.get_text(" ")) for th in ths]
            if any(re.search(r"LV\d+", t) for t in texts):
                headers = texts
                break
    lv: List[int] = []
    for t in headers[1:]:  # 先頭列は項目名 or 属性名
        m = re.search(r"LV(\d+)", t, re.IGNORECASE)
        if m:
            lv.append(int(m.group(1)))
    return lv


def expand_cells(cells: List[Tag], n_levels: int) -> List[Optional[str]]:
    vals: List[Optional[str]] = []
    for td in cells:
        colspan = int(td.get("colspan", 1))
        txt = clean_text(td.get_text(" "))
        vals.extend([txt] * colspan)
    # 長すぎる場合は切る、短ければNoneで埋める
    if len(vals) > n_levels:
        vals = vals[:n_levels]
    while len(vals) < n_levels:
        vals.append(None)
    return vals


def find_detail_table(soup: BeautifulSoup) -> tuple[Optional[Tag], Optional[Tag]]:
    tbl_div = soup.find(id=re.compile(r"^table_(kyoushu|hanyou|sien)$"))
    table = tbl_div.find("table") if tbl_div else None
    if not table:
        for candidate in soup.find_all("table"):
            if candidate.find(string=re.compile(r"LV\d+")):
                table = candidate
                break
    return tbl_div, table


def build_base_records(
    table: Tag, name: str, levels: List[int]
) -> Dict[int, Dict[str, Any]]:
    per_level: Dict[int, Dict[str, Any]] = {
        lv: {"MS名": f"{name}_LV{lv}"} for lv in levels
    }

    for tr in table.find_all("tr"):
        th = tr.find("th")
        if not th:
            continue
        row_name = clean_text(th.get_text(" "))
        key_name = FIELD_MAP.get(row_name)
        if key_name is None:
            key_name = FIELD_MAP.get(normalize_row_label(row_name))
        if key_name is None:
            continue

        values = expand_cells(tr.find_all("td"), len(levels))
        for lv, val in zip(levels, values):
            if val is None:
                continue
            if key_name in ("格闘判定力", "カウンター", "レアリティ", "必要階級"):
                per_level[lv][key_name] = clean_text(val)
                continue

            iv = to_int(val)
            if iv is not None:
                per_level[lv][key_name] = iv
    return per_level


def apply_parts_slots(
    soup: BeautifulSoup, per_level: Dict[int, Dict[str, Any]], levels: List[int]
) -> None:
    parts_table: Optional[Tag] = None
    for h3 in soup.find_all("h3"):
        if "パーツスロット" in h3.get_text():
            parts_table = h3.find_next_sibling("table")
            break

    if not parts_table:
        return

    row_name_map = {
        "近距離": "近スロット",
        "中距離": "中スロット",
        "遠距離": "遠スロット",
    }
    for tr in parts_table.find_all("tr"):
        th = tr.find("th")
        if not th:
            continue
        dst_key = row_name_map.get(clean_text(th.get_text(" ")))
        if not dst_key:
            continue
        values = expand_cells(tr.find_all("td"), len(levels))
        for lv, val in zip(levels, values):
            iv = to_int(val or "")
            if iv is not None:
                per_level[lv][dst_key] = iv


def infer_attr_from_table_div(tbl_div: Optional[Tag]) -> Optional[str]:
    if not tbl_div or not isinstance(tbl_div, Tag):
        return None
    match = re.search(r"table_(kyoushu|hanyou|sien)", tbl_div.get("id", ""))
    if not match:
        return None
    attr_map = {"kyoushu": "強襲", "hanyou": "汎用", "sien": "支援"}
    return attr_map.get(match.group(1))


def apply_attr(
    per_level: Dict[int, Dict[str, Any]], levels: List[int], attr: Optional[str]
) -> None:
    if not attr:
        return
    for lv in levels:
        per_level[lv]["属性"] = attr


def apply_deployment_and_env(
    soup: BeautifulSoup, per_level: Dict[int, Dict[str, Any]], levels: List[int]
) -> None:
    dep = parse_deployment(soup)
    env = parse_env_suitability(soup)
    for lv in levels:
        for key, value in dep.items():
            if value is not None:
                per_level[lv][key] = value
        per_level[lv].update(env)


def apply_deployment_fallbacks(
    per_level: Dict[int, Dict[str, Any]], levels: List[int]
) -> None:
    for lv in levels:
        rec = per_level[lv]
        if "出撃_地上可" not in rec and "出撃_宇宙可" not in rec:
            has_g = "旋回_地上_通常時" in rec
            has_s = "旋回_宇宙_通常時" in rec
            if has_g and has_s:
                rec["出撃_地上可"] = True
                rec["出撃_宇宙可"] = True
            elif has_g and not has_s:
                rec["出撃_地上可"] = True
                rec["出撃_宇宙可"] = False
            elif has_s and not has_g:
                rec["出撃_地上可"] = False
                rec["出撃_宇宙可"] = True


def normalize_turn_values(
    per_level: Dict[int, Dict[str, Any]], levels: List[int]
) -> None:
    for lv in levels:
        rec = per_level[lv]
        ground = rec.get("出撃_地上可")
        space = rec.get("出撃_宇宙可")
        if ground is False and space is True:
            if "旋回_宇宙_通常時" not in rec and "旋回_地上_通常時" in rec:
                rec["旋回_宇宙_通常時"] = rec.pop("旋回_地上_通常時")
            if "旋回_宇宙_変形時" not in rec and "旋回_地上_変形時" in rec:
                rec["旋回_宇宙_変形時"] = rec.pop("旋回_地上_変形時")
        if ground is True and space is False:
            if "旋回_地上_通常時" not in rec and "旋回_宇宙_通常時" in rec:
                rec["旋回_地上_通常時"] = rec.pop("旋回_宇宙_通常時")
            if "旋回_地上_変形時" not in rec and "旋回_宇宙_変形時" in rec:
                rec["旋回_地上_変形時"] = rec.pop("旋回_宇宙_変形時")


def parse_fullst_by_ms_level(
    soup: BeautifulSoup, ms_levels: List[int]
) -> Dict[int, List[Dict[str, Any]]]:
    header = None
    for hx in soup.find_all(["h2", "h3"]):
        if "強化リスト情報" in clean_text(hx.get_text(" ")):
            header = hx
            break
    if not header:
        return {}

    table = header.find_next("table")
    if not table:
        return {}

    rows: List[Tuple[str, int, str, Dict[int, int], set[int], set[int]]] = []
    current_name: Optional[str] = None
    section = "normal"
    for tr in table.find_all("tr"):
        row_text = clean_text(tr.get_text(" "))
        if row_text == "上限開放":
            section = "upper"
            current_name = None
            continue

        ths = tr.find_all("th")
        if not ths:
            continue

        cand_names: List[str] = []
        for th in ths:
            txt = clean_text(th.get_text(" "))
            if not txt:
                continue
            if any(
                x in txt
                for x in (
                    "強化リスト",
                    "上限開放",
                    "リスト名",
                    "MSレベル毎必要強化値",
                    "効果",
                )
            ):
                continue
            if re.fullmatch(r"LV\d+|Lv\d+|Lv", txt, re.IGNORECASE):
                continue
            cand_names.append(txt)
        if cand_names:
            current_name = cand_names[0]

        fullst_lv: Optional[int] = None
        for th in ths:
            txt = clean_text(th.get_text(" "))
            match = re.fullmatch(r"Lv(\d+)", txt, re.IGNORECASE)
            if match:
                fullst_lv = int(match.group(1))
                break

        tds = tr.find_all("td")
        if not tds or current_name is None or fullst_lv is None:
            continue

        numeric_cells = tds[:-1] if len(tds) >= 1 else tds
        points_by_ms: Dict[int, int] = {}
        present_ms_levels: set[int] = set()
        blocked_ms_levels: set[int] = set()
        for ms_lv in ms_levels:
            idx = ms_lv - 1
            if 0 <= idx < len(numeric_cells):
                present_ms_levels.add(ms_lv)
                raw_value = clean_text(numeric_cells[idx].get_text(" "))
                val = to_int(raw_value)
                if val is not None:
                    points_by_ms[ms_lv] = val
                elif raw_value in {"-", "－"} and "強行出撃" not in current_name:
                    blocked_ms_levels.add(ms_lv)

        if (
            not points_by_ms
            and "強行出撃" not in current_name
            and not blocked_ms_levels
        ):
            continue
        rows.append(
            (
                current_name,
                fullst_lv,
                section,
                points_by_ms,
                present_ms_levels,
                blocked_ms_levels,
            )
        )

    by_ms_level: Dict[int, List[Dict[str, Any]]] = {lv: [] for lv in ms_levels}
    for ms_lv in ms_levels:
        by_name: Dict[tuple[str, str], List[Tuple[int, Optional[int], bool]]] = {}
        for nm, flv, section, pmap, present_lvs, blocked_lvs in rows:
            pts = pmap.get(ms_lv)
            skip_fallback = False
            if pts is None and "強行出撃" not in nm and ms_lv in blocked_lvs:
                skip_fallback = True
            elif pts is None and ("強行出撃" not in nm or ms_lv not in present_lvs):
                continue
            by_name.setdefault((section, nm), []).append((flv, pts, skip_fallback))

        items: List[Dict[str, Any]] = []
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


def fullst_sort_key(item: Dict[str, Any]) -> tuple[int, bool, int]:
    name = str(item.get("name", ""))
    points = item.get("points")
    point_value = points if isinstance(points, int) else 0
    return (0 if name == "強行出撃" else 1, points is not None, point_value)


def fullst_entry_key(item: Dict[str, Any]) -> tuple[Any, Any, Any]:
    return item.get("_section"), item.get("name"), item.get("level")


def fullst_section_name_key(item: Dict[str, Any]) -> tuple[Any, Any]:
    return item.get("_section"), item.get("name")


def copy_fullst_with_null_points(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    copied = []
    for e in items:
        if not isinstance(e, dict) or e.get("_skip_fallback"):
            continue
        item = {"name": e.get("name"), "level": e.get("level"), "points": None}
        if "_section" in e:
            item["_section"] = e.get("_section")
        copied.append(item)
    return copied


def strip_skip_fallback_entries(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def public_fullst_entries(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"name": e.get("name"), "level": e.get("level"), "points": e.get("points")}
        for e in items
        if isinstance(e, dict) and not e.get("_skip_fallback")
    ]


def merge_fullst_with_previous(
    current: List[Dict[str, Any]], previous: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
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
    per_level: Dict[int, Dict[str, Any]],
    levels: List[int],
    fullst_by_lv: Dict[int, List[Dict[str, Any]]],
) -> None:
    last_effective: List[Dict[str, Any]] = []
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


BASE_REQUIRED = {
    "HP",
    "スピード",
    "スラスター",
    "高速移動",
    "射撃補正",
    "格闘補正",
    "耐ビーム補正",
    "耐実弾補正",
    "耐格闘補正",
    "近スロット",
    "中スロット",
    "遠スロット",
}
FALLBACKABLE_REQUIRED_KEYS = {"スラスター"}


def has_turn_value(rec: Dict[str, Any]) -> bool:
    return ("旋回_地上_通常時" in rec) or ("旋回_宇宙_通常時" in rec)


def apply_required_value_fallbacks(
    per_level: Dict[int, Dict[str, Any]], levels: List[int]
) -> None:
    last_values: Dict[str, Any] = {}
    for lv in sorted(levels):
        rec = per_level.get(lv)
        if not isinstance(rec, dict):
            continue

        for key in FALLBACKABLE_REQUIRED_KEYS:
            if key in rec:
                last_values[key] = rec[key]
                continue
            if key not in last_values:
                continue

            required_without_key = BASE_REQUIRED - {key}
            if required_without_key.issubset(rec.keys()) and has_turn_value(rec):
                rec[key] = last_values[key]


def filter_complete_records(
    per_level: Dict[int, Dict[str, Any]]
) -> Dict[int, Dict[str, Any]]:
    return {
        lv: rec
        for lv, rec in per_level.items()
        if BASE_REQUIRED.issubset(rec.keys()) and has_turn_value(rec)
    }


def parse_details(html: str) -> Dict[int, Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    name = extract_title(soup)

    tbl_div, table = find_detail_table(soup)
    if not table:
        raise ValueError("機体テーブルが見つかりませんでした")

    levels = levels_from_table(table)
    if not levels:
        raise ValueError("LV 見出しが検出できませんでした")

    per_level = build_base_records(table, name, levels)
    apply_parts_slots(soup, per_level, levels)
    apply_attr(per_level, levels, infer_attr_from_table_div(tbl_div))
    apply_deployment_and_env(soup, per_level, levels)
    apply_deployment_fallbacks(per_level, levels)
    normalize_turn_values(per_level, levels)
    apply_required_value_fallbacks(per_level, levels)
    apply_fullst_fallback(per_level, levels, parse_fullst_by_ms_level(soup, levels))
    return filter_complete_records(per_level)


# ===============
# CLI
# ===============


def cmd_index(args: argparse.Namespace) -> int:
    url = args.url or INDEX_URL
    client = get_client()
    cfg = CacheConfig(
        ttl_seconds=parse_ttl(args.ttl), no_network=args.no_network, force=args.force
    )
    cache = CacheHTTP(client, cfg)
    text, _meta = cache.get(url)
    items = parse_index(text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"index: {len(items)} items -> {out}")
    return 0


def cmd_details(args: argparse.Namespace) -> int:
    src = Path(args.input)
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("ERROR: input must be a JSON array", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    client = get_client()
    cfg = CacheConfig(
        ttl_seconds=parse_ttl(args.ttl), no_network=args.no_network, force=args.force
    )
    cache = CacheHTTP(client, cfg)
    detail_state_path = Path(
        getattr(args, "detail_fetch_state_out", "") or "cache/detail_fetch_state.json"
    )
    detail_state = load_detail_fetch_state(detail_state_path)
    t_last = 0.0
    written = 0
    with out.open("w", encoding="utf-8") as f:
        for i, item in enumerate(data, 1):
            url = item.get("url")
            if not url:
                continue
            # rate limit
            now = time.time()
            wait = max(0.0, (t_last + 1.0 / max(args.rate, 0.1)) - now)
            if wait:
                time.sleep(wait)
            t_last = time.time()
            try:
                text, _meta = cache.get(url)
                # 変更がなければスキップ（オプション）
                if getattr(args, "changed_only", False):
                    if not _meta.get("semantic_changed", False):
                        remember_detail_fetch(detail_state, url, item, _meta)
                        continue
                per_level = parse_details(text)
                # 補足情報（index由来）を併合
                for lv, rec in per_level.items():
                    # MS名は index の name を基底とし、LVを維持（SSOT=index）
                    msn = rec.get("MS名") or ""
                    m = re.match(r"^(.*)_LV(\d+)$", msn)
                    lvno = m.group(2) if m else None
                    idx_name = item.get("name") or (m.group(1) if m else msn)
                    ms_name_index = (
                        f"{idx_name}_LV{lvno}" if lvno else (msn or idx_name)
                    )

                    base = {
                        "MS名": ms_name_index,
                        "コスト": rec.get("コスト") or item.get("cost"),
                        "属性": rec.get("属性") or item.get("属性"),
                    }
                    wiki_url = item.get("url")
                    if isinstance(wiki_url, str) and wiki_url:
                        base["wiki_url"] = wiki_url
                    merged = {**rec, **base}
                    f.write(json.dumps(merged, ensure_ascii=False))
                    f.write("\n")
                    written += 1
                remember_detail_fetch(detail_state, url, item, _meta)
            except Exception as e:
                print(f"WARN: failed {url}: {e}", file=sys.stderr)
            if args.limit and written >= args.limit:
                break
    write_detail_fetch_state(
        detail_state_path, detail_state, datetime.now(timezone.utc)
    )
    print(f"details: wrote {written} records -> {out}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    tmp_index = Path("cache/index.json")
    tmp_index.parent.mkdir(parents=True, exist_ok=True)
    # index
    client = get_client()
    cfg = CacheConfig(
        ttl_seconds=parse_ttl(getattr(args, "ttl", "7d")),
        no_network=getattr(args, "no_network", False),
        force=getattr(args, "force", False),
    )
    cache = CacheHTTP(client, cfg)
    text, _meta = cache.get(INDEX_URL)
    items = parse_index(text)
    tmp_index.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # details
    dargs = argparse.Namespace(
        input=str(tmp_index),
        out=args.out,
        rate=args.rate,
        limit=args.limit,
        ttl=getattr(args, "ttl", "7d"),
        no_network=getattr(args, "no_network", False),
        force=getattr(args, "force", False),
        changed_only=getattr(args, "changed_only", False),
        detail_fetch_state_out=getattr(
            args, "detail_fetch_state_out", "cache/detail_fetch_state.json"
        ),
    )
    return cmd_details(dargs)


def cmd_detect_changed(args: argparse.Namespace) -> int:
    index_path = Path(args.input)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("ERROR: input must be a JSON array", file=sys.stderr)
        return 2

    previous_path: Optional[Path] = None
    previous_data: Optional[Dict[str, Any]] = None
    if getattr(args, "previous_provenance", None):
        previous_path = Path(args.previous_provenance)
        if previous_path.exists():
            try:
                previous_data = json.loads(previous_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(
                    f"WARN: failed to read previous provenance {previous_path}: {exc}",
                    file=sys.stderr,
                )
    else:
        previous_path, previous_data = find_latest_provenance(Path(args.reports_dir))

    previous_generated_at: Optional[datetime] = None
    if isinstance(previous_data, dict) and isinstance(
        previous_data.get("generated_at"), str
    ):
        try:
            previous_generated_at = parse_iso_datetime(previous_data["generated_at"])
        except (TypeError, ValueError) as exc:
            print(
                "WARN: failed to parse previous provenance generated_at "
                f"{previous_data.get('generated_at')!r}: {exc}",
                file=sys.stderr,
            )

    now = (
        parse_iso_datetime(args.now)
        if getattr(args, "now", None)
        else datetime.now(timezone.utc)
    )
    stale_detail_days = getattr(args, "stale_detail_days", None)
    detail_fetch_state: Optional[Dict[str, Dict[str, Any]]] = None
    stale_detail_seconds: Optional[int] = None
    if stale_detail_days is not None:
        stale_detail_seconds = int(float(stale_detail_days) * 86400)
        detail_fetch_state = load_detail_fetch_state(
            Path(
                getattr(args, "detail_fetch_state", "")
                or "cache/detail_fetch_state.json"
            )
        )
    selected, meta = select_changed_index_items(
        [item for item in data if isinstance(item, dict)],
        previous_generated_at=previous_generated_at,
        previous_msdata_index=load_msdata_base_index(Path(args.msdata)),
        now=now,
        freshness_window_seconds=parse_ttl(args.freshness_window),
        force_full=args.force_full,
        min_age_coverage=float(args.min_age_coverage),
        detail_fetch_state=detail_fetch_state,
        stale_detail_seconds=stale_detail_seconds,
    )
    meta["generated_at"] = (
        now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    meta["selected_index_path"] = str(Path(args.out))
    meta["source_index_path"] = str(index_path)
    meta["previous_provenance_path"] = str(previous_path) if previous_path else None

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    meta_path = Path(args.meta_out)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        "detect-changed: "
        f"{meta['candidate_count']}/{meta['total_count']} candidates "
        f"(fast_path={meta['fast_path']}, fallback_reason={meta['fallback_reason'] or 'none'})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_idx = sub.add_parser(
        "index", help="一覧ページから機体URLを抽出（キャッシュ対応）"
    )
    p_idx.add_argument("--url", default=INDEX_URL)
    p_idx.add_argument("--out", default="cache/index.json")
    p_idx.add_argument(
        "--ttl", default="7d", help="キャッシュTTL（例: 7d, 72h, 3600s）"
    )
    p_idx.add_argument("--no-network", action="store_true")
    p_idx.add_argument("--force", action="store_true")
    p_idx.set_defaults(func=cmd_index)

    p_det = sub.add_parser(
        "details", help="詳細ページからステータスを抽出しJSONL出力（キャッシュ対応）"
    )
    p_det.add_argument("--in", dest="input", required=True)
    p_det.add_argument("--out", default="cache/details.jsonl")
    p_det.add_argument("--rate", type=float, default=1.0, help="req/sec")
    p_det.add_argument(
        "--limit", type=int, default=0, help="最大レコード数（0=制限なし）"
    )
    p_det.add_argument("--ttl", default="7d", help="キャッシュTTL")
    p_det.add_argument("--no-network", action="store_true")
    p_det.add_argument("--force", action="store_true")
    p_det.add_argument(
        "--detail-fetch-state-out", default="cache/detail_fetch_state.json"
    )
    p_det.add_argument(
        "--changed-only",
        action="store_true",
        help="セマンティック変化がないページをスキップ（コメント等の更新は無視）",
    )
    p_det.set_defaults(func=cmd_details)

    p_all = sub.add_parser("all", help="index→details を連続実行")
    p_all.add_argument("--out", default="cache/details.jsonl")
    p_all.add_argument("--rate", type=float, default=1.0)
    p_all.add_argument("--limit", type=int, default=0)
    p_all.add_argument("--ttl", default="7d")
    p_all.add_argument("--no-network", action="store_true")
    p_all.add_argument("--force", action="store_true")
    p_all.add_argument(
        "--detail-fetch-state-out", default="cache/detail_fetch_state.json"
    )
    p_all.add_argument(
        "--changed-only",
        action="store_true",
        help="セマンティック変化がないページをスキップ（details と同じ挙動）",
    )
    p_all.set_defaults(func=cmd_all)

    p_detect = sub.add_parser(
        "detect-changed",
        help="MS一覧の更新経過から再取得対象ページだけを抽出",
    )
    p_detect.add_argument("--in", dest="input", required=True)
    p_detect.add_argument("--out", default="cache/index_changed.json")
    p_detect.add_argument("--meta-out", default="cache/index_changed_meta.json")
    p_detect.add_argument("--reports-dir", default="reports")
    p_detect.add_argument("--previous-provenance", default="")
    p_detect.add_argument("--msdata", default="msData.json")
    p_detect.add_argument("--freshness-window", default="1h")
    p_detect.add_argument(
        "--detail-fetch-state", default="cache/detail_fetch_state.json"
    )
    p_detect.add_argument("--stale-detail-days", default="14")
    p_detect.add_argument("--min-age-coverage", type=float, default=0.95)
    p_detect.add_argument("--force-full", action="store_true")
    p_detect.add_argument("--now", default="")
    p_detect.set_defaults(func=cmd_detect_changed)

    # ラベル監査用: 行見出し（raw / normalized）のみ抽出
    def cmd_labels(args: argparse.Namespace) -> int:
        src = Path(args.input)
        data = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            print("ERROR: input must be a JSON array", file=sys.stderr)
            return 2
        client = get_client()
        cfg = CacheConfig(
            ttl_seconds=parse_ttl(args.ttl),
            no_network=args.no_network,
            force=args.force,
        )
        cache = CacheHTTP(client, cfg)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        t_last = 0.0
        written = 0
        with out.open("w", encoding="utf-8") as f:
            for i, item in enumerate(data, 1):
                url = item.get("url")
                if not url:
                    continue
                now = time.time()
                wait = max(0.0, (t_last + 1.0 / max(args.rate, 0.1)) - now)
                if wait:
                    time.sleep(wait)
                t_last = time.time()
                try:
                    text, meta = cache.get(url)
                    soup = BeautifulSoup(text, "lxml")
                    # ステータス表の検出ロジックは parse_details と同じ方針
                    _tbl_div, table = find_detail_table(soup)
                    raw_labels: List[str] = []
                    normalized_labels: List[str] = []
                    if table:
                        seen_raw = set()
                        seen_norm = set()
                        for tr in table.find_all("tr"):
                            th = tr.find("th")
                            if not th:
                                continue
                            rname = clean_text(th.get_text(" "))
                            nname = normalize_row_label(rname)
                            if rname and rname not in seen_raw:
                                raw_labels.append(rname)
                                seen_raw.add(rname)
                            if nname and nname not in seen_norm:
                                normalized_labels.append(nname)
                                seen_norm.add(nname)
                    row = {
                        "url": url,
                        "title": soup.title.get_text(" ") if soup.title else "",
                        "attr": item.get("属性"),
                        "raw_labels": raw_labels,
                        "normalized_labels": normalized_labels,
                        "content_sha256": meta.get("content_sha256"),
                    }
                    f.write(json.dumps(row, ensure_ascii=False))
                    f.write("\n")
                    written += 1
                except Exception as e:
                    print(f"WARN: labels failed {url}: {e}", file=sys.stderr)
                if args.limit and written >= args.limit:
                    break
        print(f"labels: wrote {written} pages -> {out}")
        return 0

    p_lbl = sub.add_parser(
        "labels", help="行見出しの揺らぎ監査用データを抽出（キャッシュ対応）"
    )
    p_lbl.add_argument("--in", dest="input", required=True)
    p_lbl.add_argument("--out", default="cache/labels_raw.jsonl")
    p_lbl.add_argument("--rate", type=float, default=1.0, help="req/sec")
    p_lbl.add_argument("--limit", type=int, default=0)
    p_lbl.add_argument("--ttl", default="7d")
    p_lbl.add_argument("--no-network", action="store_true")
    p_lbl.add_argument("--force", action="store_true")
    p_lbl.set_defaults(func=cmd_labels)

    return ap


def main(argv: List[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
