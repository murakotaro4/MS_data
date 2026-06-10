"""レポート（Markdown）生成の共通部品。"""

from __future__ import annotations

import json
from typing import Any


def value_text(value: Any) -> str:
    """テーブルセル向けの値の文字列化。dict/list は JSON、None は空文字。"""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
