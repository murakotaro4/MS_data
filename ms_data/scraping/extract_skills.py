#!/usr/bin/env python3
"""atwiki スキル抽出の後方互換 facade と CLI エントリーポイント。"""

from __future__ import annotations

import argparse
import subprocess

import httpx

from ms_data.net.cache_http import CacheHTTP
from ms_data.net.client import get_browser_client
from ms_data.scraping import skills_cli
from ms_data.scraping.skill_owners import (
    SKILL_URL,
    extract_skill_owners_rows_table,
)
from ms_data.scraping.skills_html import (
    extract_skill_owners_from_html,
    extract_skill_rows_table,
    extract_skills_from_html,
)

__all__ = [
    "CacheHTTP",
    "SKILL_URL",
    "cmd_all",
    "cmd_fetch",
    "cmd_owners_table",
    "cmd_parse",
    "cmd_table",
    "extract_skill_owners_from_html",
    "extract_skill_owners_rows_table",
    "extract_skill_rows_table",
    "extract_skills_from_html",
    "get_client",
    "main",
    "subprocess",
]


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


def main(argv: list[str] | None = None) -> int:
    return skills_cli.main(argv, _deps())


if __name__ == "__main__":
    raise SystemExit(main())
