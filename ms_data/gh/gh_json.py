"""gh api / gh pr の JSON 出力を解析する共通ヘルパー。

`gh api --paginate` は JSON 値を連結して出力することがあるため、
通常の json.loads ではなく逐次デコードで読み取る。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


GhRunner = Callable[[list[str]], str]


def run_gh(
    args: list[str], *, env_overrides: dict[str, str] | None = None
) -> str:
    kwargs: dict[str, Any] = {
        "check": True,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if env_overrides is not None:
        env = os.environ.copy()
        env.update(env_overrides)
        kwargs["env"] = env
    try:
        result = subprocess.run(args, **kwargs)
    except subprocess.CalledProcessError as error:
        if isinstance(error.stderr, str) and error.stderr:
            print(
                error.stderr,
                file=sys.stderr,
                end="" if error.stderr.endswith("\n") else "\n",
            )
        raise
    return result.stdout


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


def gh_api_json(
    endpoint: str,
    *,
    method: str = "GET",
    fields: dict[str, str] | None = None,
    headers: list[str] | None = None,
    paginate: bool = False,
    runner: GhRunner = run_gh,
) -> Any:
    cmd = ["gh", "api", endpoint]
    if method != "GET":
        cmd.extend(["-X", method])
    if paginate:
        cmd.append("--paginate")
    for header in headers or []:
        cmd.extend(["-H", header])
    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    return parse_json_stream(runner(cmd))


def load_json_stream(path: Path) -> Any:
    return parse_json_stream(path.read_text(encoding="utf-8"))


def login_of(item: dict[str, Any]) -> str:
    user = item.get("user")
    if not isinstance(user, dict):
        return ""
    login = user.get("login")
    return login if isinstance(login, str) else ""
