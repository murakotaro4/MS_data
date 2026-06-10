"""gh api / gh pr の JSON 出力を解析する共通ヘルパー。

`gh api --paginate` は JSON 値を連結して出力することがあるため、
通常の json.loads ではなく逐次デコードで読み取る。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def flatten_pages(value: Any) -> Any:
    if isinstance(value, list) and all(isinstance(page, list) for page in value):
        return [item for page in value for item in page]
    return value


def parse_json_stream(text: str) -> Any:
    text = text.strip()
    if not text:
        return []

    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    while index < len(text):
        value, index = decoder.raw_decode(text, index)
        values.append(value)
        while index < len(text) and text[index].isspace():
            index += 1
    return flatten_pages(values[0] if len(values) == 1 else values)


def load_json_stream(path: Path) -> Any:
    return parse_json_stream(path.read_text(encoding="utf-8"))


def login_of(item: dict[str, Any]) -> str:
    user = item.get("user")
    if not isinstance(user, dict):
        return ""
    login = user.get("login")
    return login if isinstance(login, str) else ""
