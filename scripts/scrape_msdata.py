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
    headers = {
        "User-Agent": "msdata-scraper/0.1 (+https://github.com/; contact=local)"
    }
    return httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


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
                results.append({
                    "name": name,
                    "url": href,
                    "cost": cost,
                    "属性": attr,
                })
    return results


# ===============
# Detail parsing
# ===============

FIELD_MAP = {
    "Cost": "コスト",
    "機体HP": "HP",
    "耐実弾補正": "耐実弾補正",
    "耐ビーム補正": "耐ビーム補正",
    "耐格闘補正": "耐格闘補正",
    "射撃補正": "射撃補正",
    "格闘補正": "格闘補正",
    "スピード": "スピード",
    "高速移動": "高速移動",
    "スラスター": "スラスター",
    "旋回（地上）[度/秒]": "旋回_地上_通常時",
    "旋回（宇宙）[度/秒]": "旋回_宇宙_通常時",
    "旋回[度/秒]": "旋回_地上_通常時",  # 旧ページ互換
    "格闘判定力": "格闘判定力",
    "カウンター": "カウンター",
    "再出撃時間": "再出撃時間",
}


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

    per_level: Dict[int, Dict[str, Any]] = {lv: {"MS名": f"{name}_LV{lv}"} for lv in levels}

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
            if key in ("格闘判定力", "カウンター"):
                per_level[lv][key] = clean_text(val)
            elif key == "再出撃時間":
                per_level[lv][key] = to_int(val)
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
        row_name_map = {"近距離": "近スロット", "中距離": "中スロット", "遠距離": "遠スロット"}
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

    # 強化リスト情報（fullst）を抽出：各MSレベルごとに必要強化値で昇順ソートし、points を付与
    def parse_fullst_by_ms_level(s: BeautifulSoup, ms_levels: List[int]) -> Dict[int, List[Dict[str, Any]]]:
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
                if any(x in txt for x in ("強化リスト", "上限開放", "リスト名", "MSレベル毎必要強化値", "効果")):
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
                    copied = [{"name": e.get("name"), "level": e.get("level"), "points": None} for e in base_list if isinstance(e, dict)]
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
    filtered = {lv: rec for lv, rec in per_level.items() if REQUIRED.issubset(rec.keys())}
    return filtered


# ===============
# CLI
# ===============


def cmd_index(args: argparse.Namespace) -> int:
    url = args.url or INDEX_URL
    client = get_client()
    r = client.get(url)
    r.raise_for_status()
    items = parse_index(r.text)
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
                r = client.get(url)
                r.raise_for_status()
                per_level = parse_details(r.text)
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
    tmp_index.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # details
    dargs = argparse.Namespace(input=str(tmp_index), out=args.out, rate=args.rate, limit=args.limit)
    return cmd_details(dargs)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_idx = sub.add_parser("index", help="一覧ページから機体URLを抽出")
    p_idx.add_argument("--url", default=INDEX_URL)
    p_idx.add_argument("--out", default="cache/index.json")
    p_idx.set_defaults(func=cmd_index)

    p_det = sub.add_parser("details", help="詳細ページからステータスを抽出しJSONL出力")
    p_det.add_argument("--in", dest="input", required=True)
    p_det.add_argument("--out", default="cache/details.jsonl")
    p_det.add_argument("--rate", type=float, default=1.0, help="req/sec")
    p_det.add_argument("--limit", type=int, default=0, help="最大レコード数（0=制限なし）")
    p_det.set_defaults(func=cmd_details)

    p_all = sub.add_parser("all", help="index→details を連続実行")
    p_all.add_argument("--out", default="cache/details.jsonl")
    p_all.add_argument("--rate", type=float, default=1.0)
    p_all.add_argument("--limit", type=int, default=0)
    p_all.set_defaults(func=cmd_all)

    return ap


def main(argv: List[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)
def normalize_row_label(s: str) -> str:
    # 注記用の半角カッコ内（例: ( +25 )）のみ除去。全角カッコ（例: （地上）/（宇宙））は保持。
    s = re.sub(r"\(.*?\)", "", s)
    return clean_text(s)


if __name__ == "__main__":
    raise SystemExit(main())
