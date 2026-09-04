"""PR payload（REST / GraphQL 由来）の共通アクセサと自動更新 PR のマーカー定義。

REST（`head.ref` / `head.sha` / `base.ref` / `head.repo.full_name`）と
`gh pr list --json` などの GraphQL 由来キー（`headRefName` / `headRefOid` /
`baseRefName`）の両方を受け付け、無ければ空文字を返す。
"""

from __future__ import annotations

import re
from typing import Any

# 自動更新 PR 本文の run id マーカー（data_update.yml の `<!-- source_run_id:N -->`）
SOURCE_RUN_ID_RE = re.compile(r"source_run_id:(\d+)")
# 自動更新 PR の head ブランチ（日付部を捕捉）
HEAD_REF_DATE_RE = re.compile(r"^data/auto-update-(\d{8})$")


def _nested_str(item: dict[str, Any], *keys: str) -> str:
    value: Any = item
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) else ""


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def head_ref(pull: dict[str, Any]) -> str:
    return _first_str(_nested_str(pull, "head", "ref"), pull.get("headRefName"))


def head_sha(pull: dict[str, Any]) -> str:
    return _first_str(_nested_str(pull, "head", "sha"), pull.get("headRefOid"))


def base_ref(pull: dict[str, Any]) -> str:
    return _first_str(_nested_str(pull, "base", "ref"), pull.get("baseRefName"))


def head_repo_full_name(pull: dict[str, Any]) -> str:
    return _nested_str(pull, "head", "repo", "full_name")


def source_run_id_from_body(body: str | None) -> str:
    """PR body の ``source_run_id:N`` マーカーから run id を取り出す（無ければ空）。"""
    match = SOURCE_RUN_ID_RE.search(body or "")
    return match.group(1) if match else ""
