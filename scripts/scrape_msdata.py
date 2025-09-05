#!/usr/bin/env python3
"""
バトオペ2 atwiki からモビルスーツ一覧と各機体ステータスをスクレイピングし、
正規化済みのレコードを生成するユーティリティ（uv 前提）。

サブコマンド
- index   : 一覧ページから (name, url, cost, 属性) を収集
- details : index出力を入力にし、各詳細ページからLVごとのステータスを抽出
- all     : index → details まで一気通貫で実行

使い方例
- 一覧のみ:                   uv run python scripts/scrape_msdata.py index --url https://w.atwiki.jp/battle-operation2/pages/377.html --out cache/index.json
- 詳細スクレイプ:             uv run python scripts/scrape_msdata.py details --in cache/index.json --out cache/details.jsonl --rate 1.0
- 一気通貫（出力JSONL）:     uv run python scripts/scrape_msdata.py all --out cache/details.jsonl

注意
- レート制限を守ってください（既定: 1 req/sec）。
- 取得HTMLの構造は変わる可能性があります。CSSセレクタは `SELECTORS` を参照。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag
from scripts.label_utils import (
    clean_text,
    normalize_row_label,
    FIELD_MAP,
)
from scripts.cache_http import CacheHTTP, CacheConfig


ATWIKI_BASE = "https://w.atwiki.jp"
INDEX_URL = "https://w.atwiki.jp/battle-operation2/pages/377.html"


def absolute_url(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return ATWIKI_BASE + href
    if href.startswith("http"):
        return href
    return ATWIKI_BASE + "/" + href.lstrip("/")


def get_client(timeout: float = 30.0) -> httpx.Client:
    headers = {"User-Agent": "msdata-scraper/0.1 (+https://github.com/; contact=local)"}
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


def parse_index(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict[str, Any]] = []
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
            for a in ul.select("li > a[href]"):
                name = clean_text(a.get_text(" "))
                href = absolute_url(a["href"])
                results.append(
                    {
                        "name": name,
                        "url": href,
                        "cost": cost,
                        "属性": attr,
                    }
                )
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


def parse_details(html: str) -> Dict[int, Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    name = extract_title(soup)

    # 機体テーブル（数値情報→機体）
    # id="table_kyoushu|hanyou|sien" 直下のtableを優先
    tbl_div = soup.find(id=re.compile(r"^table_(kyoushu|hanyou|sien)$"))
    table = tbl_div.find("table") if tbl_div else None
    if not table:
        # フォールバック：ページ内の最初の「LV1」を含むテーブル
        for t in soup.find_all("table"):
            if t.find(string=re.compile(r"LV\d+")):
                table = t
                break
    if not table:
        raise ValueError("機体テーブルが見つかりませんでした")

    levels = levels_from_table(table)
    if not levels:
        raise ValueError("LV 見出しが検出できませんでした")

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
            row_name2 = normalize_row_label(row_name)
            key_name = FIELD_MAP.get(row_name2)
        if key_name is None:
            continue
        key = key_name
        tds = tr.find_all("td")
        values = expand_cells(tds, len(levels))
        for lv, val in zip(levels, values):
            if val is None:
                continue
            if key in ("格闘判定力", "カウンター", "レアリティ", "必要階級"):
                per_level[lv][key] = clean_text(val)
            elif key in ("再出撃時間", "必要DP", "必要リサイクルチケット"):
                iv = to_int(val)
                if iv is not None:
                    per_level[lv][key] = iv
            else:
                iv = to_int(val)
                if iv is not None:
                    per_level[lv][key] = iv

    # パーツスロット表
    parts_table: Optional[Tag] = None
    for h3 in soup.find_all("h3"):
        if "パーツスロット" in h3.get_text():
            nxt = h3.find_next_sibling("table")
            if nxt:
                parts_table = nxt
            break
    if parts_table:
        # 行: 近距離/中距離/遠距離
        row_name_map = {
            "近距離": "近スロット",
            "中距離": "中スロット",
            "遠距離": "遠スロット",
        }
        for tr in parts_table.find_all("tr"):
            th = tr.find("th")
            if not th:
                continue
            rname = clean_text(th.get_text(" "))
            dst_key = row_name_map.get(rname)
            if not dst_key:
                continue
            tds = tr.find_all("td")
            values = expand_cells(tds, len(levels))
            for lv, val in zip(levels, values):
                iv = to_int(val or "")
                if iv is not None:
                    per_level[lv][dst_key] = iv

    # 属性（推定）: table_* のサフィックスから
    attr = None
    if tbl_div and isinstance(tbl_div, Tag):
        m = re.search(r"table_(kyoushu|hanyou|sien)", tbl_div.get("id", ""))
        if m:
            attr_map = {"kyoushu": "強襲", "hanyou": "汎用", "sien": "支援"}
            attr = attr_map.get(m.group(1))
    if attr:
        for lv in levels:
            per_level[lv]["属性"] = attr

    # 出撃可否（地上/宇宙）
    dep = parse_deployment(soup)
    if dep:
        for lv in levels:
            for k, v in dep.items():
                if v is not None:
                    per_level[lv][k] = v

    # 環境適正（地上/宇宙/水中）
    env = parse_env_suitability(soup)
    for lv in levels:
        per_level[lv].update(env)

    # 強化リスト情報（fullst）を抽出：各MSレベルごとに必要強化値で昇順ソートし、points を付与
    def parse_fullst_by_ms_level(
        s: BeautifulSoup, ms_levels: List[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        # 見出し「強化リスト情報」を探す
        header = None
        for hx in s.find_all(["h2", "h3"]):
            if "強化リスト情報" in clean_text(hx.get_text(" ")):
                header = hx
                break
        if not header:
            return {}
        table = header.find_next("table")
        if not table:
            return {}

        # 列構造は行の td 数に依存させる（末尾は効果列が入るため原則1つ除外）

        # 収集: (name, list_level, {ms_lv -> points})
        rows: List[Tuple[str, int, Dict[int, int]]] = []
        current_name: Optional[str] = None
        for tr in table.find_all("tr"):
            ths = tr.find_all("th")
            if not ths:
                continue
            # リスト名候補
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

            # フルリストのLv（例: Lv1, Lv2, Lv4 など）
            fullst_lv: Optional[int] = None
            for th in ths:
                txt = clean_text(th.get_text(" "))
                m = re.fullmatch(r"Lv(\d+)", txt, re.IGNORECASE)
                if m:
                    fullst_lv = int(m.group(1))
                    break

            # 数値セルを収集（行末の効果セルを除外）
            tds = tr.find_all("td")
            if not tds or current_name is None or fullst_lv is None:
                continue
            # 末尾（効果列）を除外する。安全側で1つだけ除去。
            numeric_cells = tds[:-1] if len(tds) >= 1 else tds

            # MSレベルに対応する列位置は 1始まりで左から順に対応させる
            points_by_ms: Dict[int, int] = {}
            for ms_lv in ms_levels:
                idx = ms_lv - 1
                if 0 <= idx < len(numeric_cells):
                    val = to_int(clean_text(numeric_cells[idx].get_text(" ")))
                    if val is not None:
                        points_by_ms[ms_lv] = val

            # 少なくともどこかのMSレベルで数値があるときのみ採用
            if points_by_ms:
                rows.append((current_name, fullst_lv, points_by_ms))

        # 各MSレベルごとに、同一リスト名については「数値が存在するLvの中で最小と最大のみ」を採用し、points昇順で並べる
        by_ms_level: Dict[int, List[Dict[str, Any]]] = {lv: [] for lv in ms_levels}
        for ms_lv in ms_levels:
            # name -> list of (list_level, points)
            by_name: Dict[str, List[Tuple[int, int]]] = {}
            for nm, flv, pmap in rows:
                if ms_lv in pmap:
                    by_name.setdefault(nm, []).append((flv, pmap[ms_lv]))
            items: List[Dict[str, Any]] = []
            for nm, lst in by_name.items():
                # 数値がある level を採用（Lvの最小/最大）
                lst_sorted = sorted(lst, key=lambda x: x[0])
                keep = []
                if lst_sorted:
                    keep.append(lst_sorted[0])
                if len(lst_sorted) > 1 and lst_sorted[-1] != lst_sorted[0]:
                    keep.append(lst_sorted[-1])
                for flv, pts in keep:
                    items.append({"name": nm, "level": flv, "points": pts})
            # points 昇順で整列
            items.sort(key=lambda d: d.get("points", 0))
            if items:
                by_ms_level[ms_lv] = items
        # 空のMSレベルは削除
        return {k: v for k, v in by_ms_level.items() if v}

    fullst_by_lv = parse_fullst_by_ms_level(soup, levels)
    # フォールバック: 強化リストが未掲載のMSレベルには直前のレベルのfullstを採用（pointsは未知なのでNone）
    seen_lower: List[int] = []
    for lv in sorted(levels):
        if lv in fullst_by_lv and fullst_by_lv[lv]:
            per_level[lv]["fullst"] = fullst_by_lv[lv]
            seen_lower.append(lv)
        else:
            if seen_lower:
                base_lv = seen_lower[-1]
                base_list = fullst_by_lv.get(base_lv) or []
                if base_list:
                    copied = [
                        {"name": e.get("name"), "level": e.get("level"), "points": None}
                        for e in base_list
                        if isinstance(e, dict)
                    ]
                    per_level[lv]["fullst"] = copied

    # 必須キーが揃っていないLVは除外（スキーマに準拠するため）
    REQUIRED = {
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
        "旋回_地上_通常時",
    }
    filtered = {
        lv: rec for lv, rec in per_level.items() if REQUIRED.issubset(rec.keys())
    }
    return filtered


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
                per_level = parse_details(text)
                # 補足情報（index由来）を併合
                for lv, rec in per_level.items():
                    base = {
                        "MS名": rec.get("MS名"),
                        "コスト": rec.get("コスト") or item.get("cost"),
                        "属性": rec.get("属性") or item.get("属性"),
                    }
                    merged = {**rec, **base}
                    f.write(json.dumps(merged, ensure_ascii=False))
                    f.write("\n")
                    written += 1
            except Exception as e:
                print(f"WARN: failed {url}: {e}", file=sys.stderr)
            if args.limit and written >= args.limit:
                break
    print(f"details: wrote {written} records -> {out}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    tmp_index = Path("cache/index.json")
    tmp_index.parent.mkdir(parents=True, exist_ok=True)
    # index
    client = get_client()
    r = client.get(INDEX_URL)
    r.raise_for_status()
    items = parse_index(r.text)
    tmp_index.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # details
    dargs = argparse.Namespace(
        input=str(tmp_index), out=args.out, rate=args.rate, limit=args.limit
    )
    return cmd_details(dargs)


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
    p_det.set_defaults(func=cmd_details)

    p_all = sub.add_parser("all", help="index→details を連続実行")
    p_all.add_argument("--out", default="cache/details.jsonl")
    p_all.add_argument("--rate", type=float, default=1.0)
    p_all.add_argument("--limit", type=int, default=0)
    p_all.set_defaults(func=cmd_all)

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
                    tbl_div = soup.find(id=re.compile(r"^table_(kyoushu|hanyou|sien)$"))
                    table = tbl_div.find("table") if tbl_div else None
                    if not table:
                        for t in soup.find_all("table"):
                            if t.find(string=re.compile(r"LV\d+")):
                                table = t
                                break
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
