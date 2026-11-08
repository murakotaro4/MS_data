"""data/weapons.json（兵装名の一覧）をスキーマと意味の両面で検証する。

- スキーマ: schema/weapons.schema.json
- 意味: 同じ機体・種類・兵装名の重複がないこと、機体名順に並んでいること、
  同じ機体の行の wiki_url が揃っていること、LV が昇順であること
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ms_data.core import paths
from ms_data.core.json_io import load_json


def validate_schema(data: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors
    ]


def validate_semantics(data: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    url_by_ms: dict[str, str] = {}
    prev_ms: str | None = None
    for i, rec in enumerate(data):
        ms_name = rec["ms_name"]
        key = (ms_name, rec["kind"], rec["name"])
        if key in seen:
            messages.append(f"{i}: duplicate weapon {key}")
        seen.add(key)
        url = url_by_ms.setdefault(ms_name, rec["wiki_url"])
        if url != rec["wiki_url"]:
            messages.append(
                f"{i}: wiki_url differs within {ms_name}: {rec['wiki_url']}"
            )
        if prev_ms is not None and ms_name < prev_ms:
            messages.append(f"{i}: not sorted by ms_name ({prev_ms} -> {ms_name})")
        prev_ms = ms_name
        if rec["levels"] != sorted(rec["levels"]):
            messages.append(f"{i}: levels not sorted: {rec['levels']}")
    return messages


def validate(weapons_path: Path, schema_path: Path) -> list[str]:
    data = load_json(weapons_path)
    messages = validate_schema(data, load_json(schema_path))
    if messages:
        return messages
    return validate_semantics(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("weapons", nargs="?", default=paths.WEAPONS_JSON.as_posix())
    ap.add_argument("--schema", default=paths.WEAPONS_SCHEMA.as_posix())
    args = ap.parse_args(argv)
    weapons_path = Path(args.weapons)
    if not weapons_path.exists():
        print(f"weapons file not found: {weapons_path}", file=sys.stderr)
        return 1
    messages = validate(weapons_path, Path(args.schema))
    for msg in messages[:50]:
        print(f"{weapons_path}: {msg}", file=sys.stderr)
    if messages:
        print(f"NG: {len(messages)} error(s)", file=sys.stderr)
        return 1
    print(f"OK: {weapons_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
