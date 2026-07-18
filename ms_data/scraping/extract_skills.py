#!/usr/bin/env python3
"""atwiki スキル抽出の後方互換 facade と CLI エントリーポイント。"""

from __future__ import annotations

import argparse
import subprocess

import httpx

from ms_data.net.cache_http import CacheConfig, CacheHTTP
from ms_data.net.client import get_browser_client
from ms_data.scraping import skills_cli
from ms_data.scraping.skill_owners import (
    SKILL_URL,
    _RE_ANCHOR,
    _candidate_owner_tables,
    _collect_anchor_row_owners,
    _collect_owner_block,
    _extract_owner_anchors,
    _find_owner_section_tables,
    _owner_links_from_cells,
    _role_from_text,
    extract_skill_owners_rows_table,
)
from ms_data.scraping.skills_cli import build_parser
from ms_data.scraping.skills_html import (
    CORE_SKILLS,
    _effects_from_lines,
    _extract_activation,
    _extract_duration,
    _norm,
    _parse_grants,
    _percent_to_factor,
    _select_main_skill_table,
    _split_lines,
    _to_int_first,
    extract_skill_owners_from_html,
    extract_skill_rows_table,
    extract_skills_from_html,
)
from ms_data.scraping.text_values import normalize_symbol_text, parse_ttl


def get_client(timeout: float = 30.0) -> httpx.Client:
    """テスト互換のため facade 上に残す HTTP クライアント生成 seam。"""
    return get_browser_client(timeout)


def _deps() -> skills_cli.CliDeps:
    """facade の global を毎回参照し monkeypatch を CLI 実装へ反映する。"""
    return skills_cli.CliDeps(
        get_client=get_client,
        cache_http=CacheHTTP,
        extract_skills_from_html=extract_skills_from_html,
        extract_skill_rows_table=extract_skill_rows_table,
        extract_skill_owners_rows_table=extract_skill_owners_rows_table,
        subprocess_module=subprocess,
    )


def cmd_fetch(args: argparse.Namespace) -> int:
    return skills_cli.cmd_fetch(args, _deps())


def cmd_parse(args: argparse.Namespace) -> int:
    return skills_cli.cmd_parse(args, _deps())


def cmd_all(args: argparse.Namespace) -> int:
    return skills_cli.cmd_all(args, _deps())


def cmd_table(args: argparse.Namespace) -> int:
    return skills_cli.cmd_table(args, _deps())


def cmd_owners_table(args: argparse.Namespace) -> int:
    return skills_cli.cmd_owners_table(args, _deps())


def _cmd_otbl(args: argparse.Namespace) -> int:
    """旧ネスト名に対応する owners-table コマンドの互換 alias。"""
    return cmd_owners_table(args)


def main(argv: list[str] | None = None) -> int:
    return skills_cli.main(argv, _deps())


if __name__ == "__main__":
    raise SystemExit(main())
