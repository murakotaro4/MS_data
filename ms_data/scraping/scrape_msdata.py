#!/usr/bin/env python3
"""
バトオペ2 atwiki からモビルスーツ一覧と各機体ステータスをスクレイピングする CLI。

サブコマンド
- index          : 一覧ページから (name, url, cost, 属性) を収集
- details        : index出力を入力にし、各詳細ページからLVごとのステータスを抽出
- all            : index → details まで一気通貫で実行
- detect-changed : 一覧の更新経過から再取得対象ページだけを抽出
- labels         : 行見出しの揺らぎ監査用データを抽出

実装は責務ごとに分かれている:
- text_values      : 文字列・数値変換の小物（parse_ttl, to_int など）
- index_page       : 一覧ページの HTML 解析
- detail_page      : 詳細ページの HTML 解析（parse_details）
- fullst           : 強化リストの解析と LV 間フォールバック
- change_detection : 再取得対象の選定（select_changed_index_items）
- fetch_state      : 取得状態・取得統計の永続化

本モジュールは CLI（cmd_*）と後方互換の re-export のみを持つ。

使い方例
- 一覧のみ:
  uv run python -m ms_data.scraping.scrape_msdata index \
      --url https://w.atwiki.jp/battle-operation2/pages/377.html \
      --out cache/index.json
- 詳細スクレイプ:
  uv run python -m ms_data.scraping.scrape_msdata details \
      --in cache/index.json \
      --out cache/details.jsonl \
      --rate 1.0
- 一気通貫（出力JSONL）:
  uv run python -m ms_data.scraping.scrape_msdata all \
      --out cache/details.jsonl

注意
- レート制限を守ってください（既定: 1 req/sec）。
- 取得HTMLの構造は変わる可能性があります。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ms_data.core.labels import clean_text, normalize_row_label
from ms_data.net.cache_http import CacheConfig, CacheHTTP
from ms_data.net.client import get_scraper_client
from ms_data.scraping.change_detection import (
    find_latest_provenance,
    load_msdata_base_index,
    select_changed_index_items,
)
from ms_data.scraping.detail_page import (
    build_base_records,
    find_detail_table,
    parse_deployment,
    parse_details,
    parse_env_suitability,
)
from ms_data.scraping.fetch_state import (
    load_detail_fetch_state,
    remember_detail_fetch,
    remember_detail_fetch_failure,
    write_detail_fetch_state,
    write_fetch_stats,
)
from ms_data.scraping.index_page import parse_index

# この facade がサポートする公開面（テスト・CLI が参照する名前）
# 動的参照やリポジトリ外の互換は保証しない。
from ms_data.scraping.text_values import (
    is_counter_placeholder,
    looks_like_ticket_count,
    parse_iso_datetime,
    parse_ttl,
    symbol_to_bool,
    to_int,
)

INDEX_URL = "https://w.atwiki.jp/battle-operation2/pages/377.html"


def get_client(timeout: float = 30.0) -> httpx.Client:
    # テストが本モジュール属性として monkeypatch するため、ラッパーとして残す
    return get_scraper_client(timeout)


def _build_cache(args: argparse.Namespace, *, rate: float | None = None) -> CacheHTTP:
    """CLI 引数からキャッシュ付き HTTP クライアントを組み立てる。

    get_client / CacheHTTP はテストが本モジュール属性として monkeypatch する
    ため、必ずモジュール global 経由で参照すること。
    """
    cfg = CacheConfig(
        ttl_seconds=parse_ttl(getattr(args, "ttl", "7d")),
        no_network=getattr(args, "no_network", False),
        force=getattr(args, "force", False),
        # レート制限は実際のネットワーク取得時のみ適用（キャッシュヒットは待機しない）
        min_interval_seconds=(1.0 / max(rate, 0.1)) if rate is not None else 0.0,
    )
    return CacheHTTP(get_client(), cfg)


# ===============
# CLI
# ===============


def cmd_index(args: argparse.Namespace) -> int:
    """一覧ページを取得し index レコードの JSON 配列を出力する。"""
    url = args.url or INDEX_URL
    cache = _build_cache(args)
    started_at = datetime.now(timezone.utc)
    t_start = time.monotonic()
    text, _meta = cache.get(url)
    items = parse_index(text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")
    stats_out = getattr(args, "fetch_stats_out", "")
    if stats_out:
        # index は実行の先頭フェーズなので前回実行分をリセットする
        write_fetch_stats(
            Path(stats_out),
            "index",
            cache.stats,
            started_at=started_at,
            duration_seconds=time.monotonic() - t_start,
            reset=True,
        )
    print(f"index: {len(items)} items -> {out}")
    return 0


def _merge_index_fields(rec: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """詳細ページのレコードに index 由来の情報を併合する。

    MS名は index の name を基底とし、LV 番号を維持する（SSOT=index）。
    コスト・属性は詳細ページ優先、無ければ index の値で補完する。
    """
    ms_name_raw = rec.get("MS名") or ""
    m = re.match(r"^(.*)_LV(\d+)$", ms_name_raw)
    level_no = m.group(2) if m else None
    index_name = item.get("name") or (m.group(1) if m else ms_name_raw)
    ms_name_index = (
        f"{index_name}_LV{level_no}" if level_no else (ms_name_raw or index_name)
    )

    base = {
        "MS名": ms_name_index,
        "コスト": rec.get("コスト") or item.get("cost"),
        "属性": rec.get("属性") or item.get("属性"),
    }
    wiki_url = item.get("url")
    if isinstance(wiki_url, str) and wiki_url:
        base["wiki_url"] = wiki_url
    return {**rec, **base}


def cmd_details(args: argparse.Namespace) -> int:
    """index 出力の各 URL から詳細を取得し、LV ごとのレコードを JSONL 出力する。"""
    src = Path(args.input)
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("ERROR: input must be a JSON array", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = _build_cache(args, rate=args.rate)
    detail_state_path = Path(
        getattr(args, "detail_fetch_state_out", "") or "cache/detail_fetch_state.json"
    )
    detail_state = load_detail_fetch_state(detail_state_path)
    run_started_at = datetime.now(timezone.utc)
    t_start = time.monotonic()
    written = 0
    with out.open("w", encoding="utf-8") as f:
        for item in data:
            url = item.get("url")
            if not url:
                continue
            try:
                text, _meta = cache.get(url)
                # 変更がなければスキップ（オプション）
                if getattr(args, "changed_only", False) and not _meta.get(
                    "semantic_changed", False
                ):
                    remember_detail_fetch(
                        detail_state, url, item, _meta, run_started_at
                    )
                    continue
                per_level = parse_details(text)
                for rec in per_level.values():
                    merged = _merge_index_fields(rec, item)
                    f.write(json.dumps(merged, ensure_ascii=False))
                    f.write("\n")
                    written += 1
                remember_detail_fetch(detail_state, url, item, _meta, run_started_at)
            except Exception as e:
                remember_detail_fetch_failure(
                    detail_state, url, item, e, run_started_at
                )
                print(f"WARN: failed {url}: {e}", file=sys.stderr)
            if args.limit and written >= args.limit:
                break
    write_detail_fetch_state(
        detail_state_path, detail_state, datetime.now(timezone.utc), run_started_at
    )
    stats_out = getattr(args, "fetch_stats_out", "")
    if stats_out:
        write_fetch_stats(
            Path(stats_out),
            "details",
            cache.stats,
            started_at=run_started_at,
            duration_seconds=time.monotonic() - t_start,
        )
    print(f"details: wrote {written} records -> {out}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    """index → details を連続実行する。"""
    tmp_index = Path("cache/index.json")
    tmp_index.parent.mkdir(parents=True, exist_ok=True)
    # index
    cache = _build_cache(args)
    started_at = datetime.now(timezone.utc)
    t_start = time.monotonic()
    text, _meta = cache.get(INDEX_URL)
    items = parse_index(text)
    tmp_index.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fetch_stats_out = getattr(args, "fetch_stats_out", "")
    if fetch_stats_out:
        # index は実行の先頭フェーズなので前回実行分をリセットする
        write_fetch_stats(
            Path(fetch_stats_out),
            "index",
            cache.stats,
            started_at=started_at,
            duration_seconds=time.monotonic() - t_start,
            reset=True,
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
        fetch_stats_out=fetch_stats_out,
    )
    return cmd_details(dargs)


def cmd_detect_changed(args: argparse.Namespace) -> int:
    """一覧の更新経過と前回実行の記録から、再取得対象ページだけを抽出する。"""
    index_path = Path(args.input)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("ERROR: input must be a JSON array", file=sys.stderr)
        return 2

    previous_path: Path | None = None
    previous_data: dict[str, Any] | None = None
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

    previous_generated_at: datetime | None = None
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
    revalidate = bool(getattr(args, "revalidate", False))
    detail_fetch_state: dict[str, dict[str, Any]] | None = None
    stale_detail_seconds: int | None = None
    if stale_detail_days is not None:
        stale_detail_seconds = int(float(stale_detail_days) * 86400)
    if stale_detail_days is not None or revalidate:
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
        revalidate=revalidate,
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


def cmd_labels(args: argparse.Namespace) -> int:
    """ラベル監査用に各詳細ページの行見出し（raw / normalized）を抽出する。"""
    src = Path(args.input)
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("ERROR: input must be a JSON array", file=sys.stderr)
        return 2
    cache = _build_cache(args, rate=args.rate)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as f:
        for item in data:
            url = item.get("url")
            if not url:
                continue
            try:
                text, meta = cache.get(url)
                soup = BeautifulSoup(text, "lxml")
                # ステータス表の検出ロジックは parse_details と同じ方針
                _tbl_div, table = find_detail_table(soup)
                raw_labels: list[str] = []
                normalized_labels: list[str] = []
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
    p_idx.add_argument(
        "--fetch-stats-out",
        default="cache/fetch_stats.json",
        help="ネットワーク取得統計の出力先（空文字で無効化）",
    )
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
    p_det.add_argument(
        "--fetch-stats-out",
        default="cache/fetch_stats.json",
        help="ネットワーク取得統計の出力先（空文字で無効化）",
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
    p_all.add_argument(
        "--fetch-stats-out",
        default="cache/fetch_stats.json",
        help="ネットワーク取得統計の出力先（空文字で無効化）",
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
    p_detect.add_argument(
        "--revalidate",
        action="store_true",
        help="一覧の更新経過と前回取得時刻を直接比較して再取得対象を選ぶ（週次再検証）",
    )
    p_detect.add_argument("--now", default="")
    p_detect.set_defaults(func=cmd_detect_changed)

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


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
