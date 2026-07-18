"""スキル抽出 CLI の引数定義と I/O 実装。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ms_data.net.cache_http import CacheConfig
from ms_data.scraping.skill_owners import SKILL_URL
from ms_data.scraping.text_values import parse_ttl


@dataclass(frozen=True)
class CliDeps:
    """facade の monkeypatch seam を実行時に注入する依存一式。"""

    get_client: Callable[[], Any]
    cache_http: type[Any]
    extract_skills_from_html: Callable[[str], dict[str, Any]]
    extract_skill_rows_table: Callable[[str], dict[str, Any]]
    extract_skill_owners_rows_table: Callable[[str], dict[str, Any]]
    subprocess_module: Any = subprocess


def _build_cache(args: argparse.Namespace, deps: CliDeps) -> Any:
    return deps.cache_http(
        deps.get_client(),
        CacheConfig(
            ttl_seconds=parse_ttl(args.ttl),
            no_network=args.no_network,
            force=args.force,
        ),
    )


def _write_json(data: dict[str, Any], output: str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out


def cmd_fetch(args: argparse.Namespace, deps: CliDeps) -> int:
    """スキル一覧ページを取得してキャッシュする。"""
    _html, meta = _build_cache(args, deps).get(args.url)
    print(json.dumps({"saved": True, "meta": meta}, ensure_ascii=False))
    return 0


def cmd_parse(args: argparse.Namespace, deps: CliDeps) -> int:
    """キャッシュ済み HTML を解析して skills JSON を出力する。"""
    html_path = Path(args.input)
    if not html_path.exists():
        raise SystemExit(f"HTML not found: {html_path}")
    data = deps.extract_skills_from_html(html_path.read_text(encoding="utf-8"))
    out = _write_json(data, args.out)
    print(f"skills: wrote -> {out}")
    return 0


def cmd_all(args: argparse.Namespace, deps: CliDeps) -> int:
    """取得と解析を一気通貫で実行する。"""
    html, meta = _build_cache(args, deps).get(args.url)
    data = deps.extract_skills_from_html(html)
    data["fetched_at"] = meta.get("fetched_at")
    out = _write_json(data, args.out)
    print(f"skills: wrote -> {out}")
    return 0


def cmd_table(args: argparse.Namespace, deps: CliDeps) -> int:
    """スキル一覧テーブルを行形式で厳格抽出する。"""
    html, meta = _build_cache(args, deps).get(args.url)
    data = deps.extract_skill_rows_table(html)
    data["fetched_at"] = meta.get("fetched_at")
    out = _write_json(data, args.out)
    print(f"skills-table: wrote -> {out}")
    return 0


def cmd_owners_table(args: argparse.Namespace, deps: CliDeps) -> int:
    """所持機体逆引きテーブルを行形式で抽出する。"""
    html, meta = _build_cache(args, deps).get(args.url)
    data = deps.extract_skill_owners_rows_table(html)
    # フォールバック: 抽出できない場合は curl で直取得（環境に curl がある前提）
    if not data.get("rows"):
        try:
            raw = deps.subprocess_module.check_output(
                ["curl", "-sL", args.url], text=True, encoding="utf-8"
            )
            data = deps.extract_skill_owners_rows_table(raw)
            data["fetched_by"] = "curl"
        except (
            FileNotFoundError,
            deps.subprocess_module.CalledProcessError,
            OSError,
            UnicodeDecodeError,
        ) as exc:
            print(f"warning: curl fallback failed: {exc}", file=sys.stderr)
    data["fetched_at"] = meta.get("fetched_at")
    out = _write_json(data, args.out)
    print(f"owners-table: wrote -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Extract core system skills from atwiki skills list (prototype)"
    )
    sub = ap.add_subparsers(dest="cmd")

    p_fetch = sub.add_parser("fetch", help="Fetch HTML (cache-aware)")
    p_fetch.add_argument("--url", default=SKILL_URL)
    p_fetch.add_argument("--ttl", default="7d")
    p_fetch.add_argument("--no-network", action="store_true")
    p_fetch.add_argument("--force", action="store_true")

    p_parse = sub.add_parser("parse", help="Parse HTML file into skills JSON")
    p_parse.add_argument(
        "--in", dest="input", required=True, help="Path to cached HTML"
    )
    p_parse.add_argument("--out", dest="out", default="cache/skills.json")

    p_all = sub.add_parser("all", help="Fetch+Parse in one go")
    p_all.add_argument("--url", default=SKILL_URL)
    p_all.add_argument("--ttl", default="7d")
    p_all.add_argument("--no-network", action="store_true")
    p_all.add_argument("--force", action="store_true")
    p_all.add_argument("--out", dest="out", default="cache/skills.json")

    p_tbl = sub.add_parser(
        "table", help="Extract strict table rows (skill, level, desc, details)"
    )
    p_tbl.add_argument("--url", default=SKILL_URL)
    p_tbl.add_argument("--ttl", default="7d")
    p_tbl.add_argument("--no-network", action="store_true")
    p_tbl.add_argument("--force", action="store_true")
    p_tbl.add_argument("--out", dest="out", default="cache/skills_table.json")

    p_otbl = sub.add_parser(
        "owners-table", help="Extract 'owners reverse index' table rows"
    )
    p_otbl.add_argument("--url", default=SKILL_URL)
    p_otbl.add_argument("--ttl", default="7d")
    p_otbl.add_argument("--no-network", action="store_true")
    p_otbl.add_argument("--force", action="store_true")
    p_otbl.add_argument("--out", dest="out", default="cache/owners_table.json")
    return ap


_COMMANDS = {
    "fetch": cmd_fetch,
    "parse": cmd_parse,
    "all": cmd_all,
    "table": cmd_table,
    "owners-table": cmd_owners_table,
}


def main(argv: list[str] | None, deps: CliDeps) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2
    return int(_COMMANDS[args.cmd](args, deps))
