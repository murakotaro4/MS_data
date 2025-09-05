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
    "格闘判定力": "格闘判定力",
    "カウンター": "カウンター",
    "再出撃時間": "再出撃時間",
}


def extract_title(soup: BeautifulSoup) -> str:
    title = soup.title.get_text(" ") if soup.title else ""
    # 例: "F90［MZ仕様］ - 機動戦士..."
    return title.split(" - ")[0].strip()


def levels_from_table(table: Tag) -> List[int]:
    thead = table.find("thead")
    if not thead:
        return []
    ths = [clean_text(th.get_text(" ")) for th in thead.find_all("th")]
    # 先頭列は属性名（強襲/汎用/支援）や空白列
    lv = []
    for t in ths[1:]:
        m = re.search(r"LV(\d+)", t)
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
        if row_name not in FIELD_MAP:
            continue
        key = FIELD_MAP[row_name]
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

    # 強化リスト情報（fullst）を抽出
    def parse_fullst(s: BeautifulSoup) -> List[Dict[str, Any]]:
        # 見出し「強化リスト情報」を探す
        header = None
        for hx in s.find_all(["h2", "h3"]):
            if "強化リスト情報" in clean_text(hx.get_text(" ")):
                header = hx
                break
        if not header:
            return []
        table = header.find_next("table")
        if not table:
            return []
        items: List[Tuple[str, int]] = []
        current_name: Optional[str] = None
        for tr in table.find_all("tr"):
            ths = tr.find_all("th")
            if not ths:
                continue
            # リスト名候補（背景色付きthや先頭thが多い）
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

            # レベル指定（Lv1, Lv2, Lv3, Lv4, ...）
            lvl: Optional[int] = None
            for th in ths:
                txt = clean_text(th.get_text(" "))
                m = re.fullmatch(r"Lv(\d+)", txt, re.IGNORECASE)
                if m:
                    lvl = int(m.group(1))
                    break
            if current_name and isinstance(lvl, int):
                items.append((current_name, lvl))

        # 各リスト名について 最小Lv と 最大Lv のみを採用（例: Lv1 と Lv4）
        levels_by_name: Dict[str, List[int]] = {}
        for nm, lv in items:
            levels_by_name.setdefault(nm, []).append(lv)
        out: List[Dict[str, Any]] = []
        for nm, lvs in levels_by_name.items():
            uniq = sorted(set(lvs))
            if not uniq:
                continue
            # 最低Lv（通常の強化）
            out.append({"name": nm, "level": uniq[0]})
            # 最高Lv（上限開放があればそれ）
            if len(uniq) > 1 and uniq[-1] != uniq[0]:
                out.append({"name": nm, "level": uniq[-1]})
        # ポリシー: Lv1 と Lv4+ のみに限定（Lv2/Lv3は省略）
        out = [e for e in out if e["level"] == 1 or e["level"] >= 4]
        return out

    fullst = parse_fullst(soup)
    if fullst:
        for lv in levels:
            per_level[lv]["fullst"] = fullst

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


if __name__ == "__main__":
    raise SystemExit(main())
