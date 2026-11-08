"""カスタムパーツ一覧ページ（atwiki pages/263）の解析と `data/custom_parts.json` の生成。

1ページに全系統（攻撃系・防御系・移動系・補助系・特殊系）の表が載っているため、
取得は1リクエストのみ。各表の直前の h3 見出しを系統として扱う。

出力は msData.json とは別ファイル（配布中の msData.json に未使用データを混ぜないため）。
1件 = パーツ1種類の1LV で、名称・LV・レア度（☆の数）・系統・出典URLを持つ。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from ms_data.core import paths
from ms_data.core.json_io import load_json
from ms_data.core.labels import clean_text

CUSTOM_PARTS_URL = "https://w.atwiki.jp/battle-operation2/pages/263.html"
DEFAULT_OUT = paths.CUSTOM_PARTS.as_posix()
CATEGORIES = ("攻撃系", "防御系", "移動系", "補助系", "特殊系")
NAME_HEADER = "名称"
# 前回件数に対してこの比率を下回る結果は取得異常とみなし上書きしない
MIN_KEEP_RATIO = 0.8
LV_RE = re.compile(r"^LV\s*(\d+)$", re.IGNORECASE)
RARITY_RE = re.compile(r"^[☆★]+$")


class CustomPartsParseError(ValueError):
    """ページ構造が想定と異なり、一覧を確定できないときに送出する。"""


def _expand_rows(table: Tag) -> list[list[str]]:
    """rowspan / colspan を展開した表のセル文字列グリッドを返す。"""
    grid: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}  # 列 -> (値, 残り行数)
    for tr in table.find_all("tr"):
        row: list[str] = []
        cells = tr.find_all(["th", "td"], recursive=False)
        col = 0
        it = iter(cells)
        cell = next(it, None)
        while cell is not None or col in pending:
            if col in pending:
                value, remaining = pending[col]
                row.append(value)
                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col] = (value, remaining - 1)
                col += 1
                continue
            text = clean_text(cell.get_text(" "))
            rowspan = _span(cell, "rowspan")
            colspan = _span(cell, "colspan")
            for _ in range(colspan):
                row.append(text)
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1
            cell = next(it, None)
        grid.append(row)
    return grid


def _span(cell: Tag, attr: str) -> int:
    try:
        return max(1, int(str(cell.get(attr, "1")).strip()))
    except ValueError:
        return 1


def _category_of(table: Tag) -> str | None:
    h3 = table.find_previous("h3")
    if h3 is None:
        return None
    text = clean_text(h3.get_text(" "))
    return text if text in CATEGORIES else None


def parse_custom_parts(
    html: str, *, source_url: str = CUSTOM_PARTS_URL
) -> list[dict[str, Any]]:
    """カスタムパーツ一覧ページ HTML から全パーツ・全LVのレコードを抽出する。

    想定外の構造（系統の欠落、LV/レア度の書式違い、同一パーツ・LVの重複）は
    黙って捨てずに CustomPartsParseError を送出する（誤った一覧で上書きしないため）。
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("#wikibody") or soup
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    found_categories: set[str] = set()
    for table in body.find_all("table"):
        grid = _expand_rows(table)
        if not grid or not grid[0] or grid[0][0] != NAME_HEADER:
            continue
        category = _category_of(table)
        if category is None:
            raise CustomPartsParseError("系統見出し（h3）が見つからない表があります")
        header = grid[0]
        try:
            lv_idx = header.index("LV")
            rarity_idx = header.index("レア度")
        except ValueError as exc:
            raise CustomPartsParseError(
                f"{category}: 見出しに LV/レア度 がありません"
            ) from exc
        found_categories.add(category)
        for row in grid[1:]:
            if not any(row):
                continue  # セルのない空行
            if row[0] == NAME_HEADER:
                continue  # rowspan 展開後の2段目の見出し行（近/中/遠）
            if len(row) <= max(lv_idx, rarity_idx):
                # 必須セル（LV/レア度）の欠けたデータ行は黙って捨てない
                raise CustomPartsParseError(
                    f"{category}/{row[0]}: LV/レア度のセルが欠けた行があります"
                )
            name, lv_text, rarity_text = row[0], row[lv_idx], row[rarity_idx]
            if not name:
                raise CustomPartsParseError(f"{category}: 名称が空の行があります")
            lv_match = LV_RE.match(lv_text)
            if not lv_match:
                raise CustomPartsParseError(
                    f"{category}/{name}: LV を解釈できません: {lv_text!r}"
                )
            if not RARITY_RE.match(rarity_text):
                raise CustomPartsParseError(
                    f"{category}/{name}: レア度を解釈できません: {rarity_text!r}"
                )
            level = int(lv_match.group(1))
            key = (name, level)
            if key in seen:
                raise CustomPartsParseError(f"{name} LV{level} が重複しています")
            seen.add(key)
            records.append(
                {
                    "名称": name,
                    "LV": level,
                    "レア度": len(rarity_text),
                    "系統": category,
                    "出典URL": source_url,
                }
            )
    missing = [c for c in CATEGORIES if c not in found_categories]
    if missing:
        raise CustomPartsParseError(f"系統の表が見つかりません: {', '.join(missing)}")
    return records


def summarize_changes(
    old: list[dict[str, Any]], new: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """前回出力との差分（追加・削除・変更された「名称 LVn」）を返す。"""

    def index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            f"{r.get('名称')} LV{r.get('LV')}": r for r in items if isinstance(r, dict)
        }

    before, after = index(old), index(new)
    return {
        "added": sorted(k for k in after if k not in before),
        "removed": sorted(k for k in before if k not in after),
        "changed": sorted(k for k in after if k in before and after[k] != before[k]),
    }


def fetch_html(url: str, *, ttl: str, no_network: bool, force: bool) -> str:
    """キャッシュ（cache/html）経由で一覧ページを取得する。取得は1リクエストのみ。"""
    from ms_data.net.cache_http import CacheConfig, CacheHTTP
    from ms_data.net.client import get_scraper_client
    from ms_data.scraping.text_values import parse_ttl

    cfg = CacheConfig(ttl_seconds=parse_ttl(ttl), no_network=no_network, force=force)
    text, _meta = CacheHTTP(get_scraper_client(), cfg).get(url)
    return text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="atwiki のカスタムパーツ一覧から custom_parts.json を生成"
    )
    p.add_argument("--html", help="pages/263 の保存済み HTML（指定時は取得しない）")
    p.add_argument("--url", default=CUSTOM_PARTS_URL)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--ttl", default="7d")
    p.add_argument("--no-network", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument(
        "--min-keep-ratio",
        type=float,
        default=MIN_KEEP_RATIO,
        help="前回件数に対する最低件数比。下回ると取得異常とみなし上書きしない",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.html:
            html = Path(args.html).read_text(encoding="utf-8")
        else:
            html = fetch_html(
                args.url, ttl=args.ttl, no_network=args.no_network, force=args.force
            )
        records = parse_custom_parts(html, source_url=args.url)
    except Exception as exc:  # 取得・解析の失敗時は既存ファイルを保持する
        print(f"[error] custom parts update failed: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    old = load_json(out) if out.exists() else []
    old = old if isinstance(old, list) else []
    if old and len(records) < len(old) * args.min_keep_ratio:
        print(
            f"[error] custom parts: 件数が前回 {len(old)} 件から {len(records)} 件へ"
            "急減したため上書きしません（ページ構造の変化や取得異常の可能性）",
            file=sys.stderr,
        )
        return 1
    diff = summarize_changes(old, records)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    kinds = len({r["名称"] for r in records})
    print(
        f"[ok] custom parts: {kinds} 種類 / {len(records)} 件 -> {out} "
        f"(追加 {len(diff['added'])} / 削除 {len(diff['removed'])} / "
        f"変更 {len(diff['changed'])})"
    )
    for label, key in (("追加", "added"), ("削除", "removed"), ("変更", "changed")):
        for item in diff[key]:
            print(f"  {label}: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
