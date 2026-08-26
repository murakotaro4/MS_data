"""レポート（Markdown）生成の共通部品。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def append_table(
    lines: list[str], headers: list[str], rows: Iterable[list[str]]
) -> None:
    """Markdown 表を lines に追記する（行なしの場合は「なし」行）。"""
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    has_rows = False
    for row in rows:
        has_rows = True
        lines.append("| " + " | ".join(row) + " |")
    if not has_rows:
        lines.append(
            "| "
            + " | ".join("なし" if i == 0 else "" for i in range(len(headers)))
            + " |"
        )


def value_text(value: Any) -> str:
    """テーブルセル向けの値の文字列化。dict/list は JSON、None は空文字。"""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
