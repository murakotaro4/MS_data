"""取得済みの機体ページ HTML から data/weapons.json（兵装名の一覧）を更新する。

atwiki への追加取得はしない。`cache/html` にある機体ページだけを読み直し、
その機体の行を置き換える。HTML が無い機体（その回に取得していない機体）は
既存の行をそのまま残す。毎日の差分取得では変化したページの HTML しか無いため、
この差し替え方式で全機体分を保つ（月 1 回の全量取得で全機体が読み直される）。

- 機体名は index（`cache/index.json`）の `name` を正とする（msData の `MS名` の LV 抜き）。
- index に無くなった機体の行は削除する。
- HTML から兵装を 1 件も読めなかった機体は、取得失敗や一時的なページ崩れの
  可能性があるため既存の行を残す（件数を出力に記録する）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ms_data.core import paths
from ms_data.core.json_io import load_json, load_json_or_default
from ms_data.net.cache_http import url_to_slug
from ms_data.scraping.weapons import extract_weapons

# index から消えた機体の行を削除する上限（既存機体数に対する割合と最低件数）。
# index の解析が一部欠けた回に大量削除しないための安全弁。超えたら削除せず残す。
REMOVAL_MAX_RATIO = 0.05
REMOVAL_MIN_ALLOWED = 5

# 出力レコードのキー順（JSON の見た目を安定させる）
RECORD_KEYS = ("ms_name", "kind", "category", "name", "levels", "wiki_url")


def _html_for(html_dir: Path, url: str) -> str | None:
    """index の URL に対応する取得済み HTML を返す。正常取得（200）でなければ None。"""
    slug = url_to_slug(url)
    html_path = html_dir / f"{slug}.html"
    if not html_path.exists():
        return None
    meta_path = html_dir / f"{slug}.meta.json"
    if meta_path.exists():
        try:
            meta = load_json(meta_path)
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(meta, dict) and meta.get("http_status") not in (None, 200):
            return None
    return html_path.read_text(encoding="utf-8")


def _record(ms_name: str, wiki_url: str, weapon: dict[str, Any]) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "ms_name": ms_name,
        "kind": weapon["kind"],
        "category": weapon.get("category"),
        "name": weapon["name"],
        "levels": list(weapon.get("levels") or []),
        "wiki_url": wiki_url,
    }
    return {k: rec[k] for k in RECORD_KEYS if rec.get(k) is not None}


def update_weapons(
    *,
    index: list[dict[str, Any]],
    html_dir: Path,
    existing: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """兵装一覧を更新し、(新しい一覧, 集計) を返す。"""
    by_ms: dict[str, list[dict[str, Any]]] = {}
    for rec in existing:
        name = rec.get("ms_name")
        if isinstance(name, str):
            by_ms.setdefault(name, []).append(rec)

    stats: dict[str, Any] = {
        "index_count": 0,
        "html_count": 0,
        "refreshed_count": 0,
        "kept_count": 0,
        "empty_kept": [],
        "removed_ms": [],
        "removal_skipped": [],
    }
    out: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for item in index:
        name = item.get("name")
        url = item.get("url")
        if not isinstance(name, str) or not isinstance(url, str) or name in seen:
            continue
        seen.add(name)
        stats["index_count"] += 1
        html = _html_for(html_dir, url)
        weapons = extract_weapons(html) if html is not None else []
        if html is not None:
            stats["html_count"] += 1
        if weapons:
            out[name] = [_record(name, url, w) for w in weapons]
            stats["refreshed_count"] += 1
            continue
        if html is not None:
            stats["empty_kept"].append(name)
        if name in by_ms:
            out[name] = by_ms[name]
            stats["kept_count"] += 1

    missing = sorted(set(by_ms) - seen)
    allowed = max(REMOVAL_MIN_ALLOWED, int(len(by_ms) * REMOVAL_MAX_RATIO))
    if len(missing) <= allowed:
        stats["removed_ms"] = missing
    else:
        stats["removal_skipped"] = missing
        for name in missing:
            out[name] = by_ms[name]
    records = [rec for ms_name in sorted(out) for rec in out[ms_name]]
    stats["record_count"] = len(records)
    stats["ms_count"] = len(out)
    return records, stats


def dump_weapons(records: list[dict[str, Any]]) -> str:
    """1 行 1 兵装の JSON 配列にする（差分が兵装単位の行で読めるように）。"""
    if not records:
        return "[]\n"
    lines = [json.dumps(rec, ensure_ascii=False) for rec in records]
    return "[\n  " + ",\n  ".join(lines) + "\n]\n"


def _write_github_output(path: str, stats: dict[str, Any], changed: bool) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"weapons_changed={'true' if changed else 'false'}\n")
        f.write(f"weapons_refreshed_count={stats['refreshed_count']}\n")
        f.write(f"weapons_record_count={stats['record_count']}\n")


def _write_step_summary(path: str, stats: dict[str, Any], changed: bool) -> None:
    lines = [
        "### 兵装名一覧（data/weapons.json）",
        f"- 変更: {'あり' if changed else 'なし'}",
        f"- 読み直した機体: {stats['refreshed_count']} / HTML {stats['html_count']}",
        f"- 機体数: {stats['ms_count']} / 兵装行数: {stats['record_count']}",
    ]
    if stats["empty_kept"]:
        names = "、".join(stats["empty_kept"][:20])
        lines.append(
            f"- 兵装を読めず既存の行を残した機体: {len(stats['empty_kept'])} 件（{names}）"
        )
    if stats["removed_ms"]:
        names = "、".join(stats["removed_ms"][:20])
        lines.append(
            f"- index から消えて削除した機体: {len(stats['removed_ms'])} 件（{names}）"
        )
    if stats["removal_skipped"]:
        lines.append(
            "- index から消えた機体が多すぎるため削除を見送り: "
            f"{len(stats['removal_skipped'])} 件"
        )
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", default=paths.INDEX_JSON.as_posix())
    ap.add_argument("--html-dir", default=paths.HTML_CACHE_DIR.as_posix())
    ap.add_argument("--weapons", default=paths.WEAPONS_JSON.as_posix())
    ap.add_argument("--out", default=None, help="出力先（既定は --weapons を上書き）")
    ap.add_argument("--github-output", default=None)
    ap.add_argument("--step-summary", default=None)
    args = ap.parse_args(argv)

    index_path = Path(args.index)
    if not index_path.exists():
        print(f"index not found: {index_path}", file=sys.stderr)
        return 2
    index = load_json(index_path)
    if not isinstance(index, list) or not index:
        print(f"index is empty or invalid: {index_path}", file=sys.stderr)
        return 2

    weapons_path = Path(args.weapons)
    existing = load_json_or_default(weapons_path, [])
    if not isinstance(existing, list):
        print(f"weapons file is not a list: {weapons_path}", file=sys.stderr)
        return 2

    records, stats = update_weapons(
        index=index, html_dir=Path(args.html_dir), existing=existing
    )
    text = dump_weapons(records)
    out_path = Path(args.out) if args.out else weapons_path
    before = out_path.read_text(encoding="utf-8") if out_path.exists() else None
    changed = before != text
    if changed:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")

    print(
        "weapons: "
        f"ms={stats['ms_count']} records={stats['record_count']} "
        f"refreshed={stats['refreshed_count']} kept={stats['kept_count']} "
        f"empty_kept={len(stats['empty_kept'])} removed={len(stats['removed_ms'])} "
        f"changed={changed}"
    )
    if args.github_output:
        _write_github_output(args.github_output, stats, changed)
    if args.step_summary:
        _write_step_summary(args.step_summary, stats, changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
