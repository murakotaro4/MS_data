"""data/custom_parts.json の構造（JSON Schema）と一意性（name+level）を検証する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ms_data.core import paths
from ms_data.core.json_io import load_json


def validate_custom_parts(data: Any, schema: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")
    if not isinstance(data, list):
        return messages
    seen: set[tuple[Any, Any]] = set()
    for index, rec in enumerate(data):
        if not isinstance(rec, dict):
            continue
        key = (rec.get("name"), rec.get("level"))
        if key in seen:
            messages.append(f"{index}: name+level が重複しています: {key[0]} LV{key[1]}")
        seen.add(key)
    return messages


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default=paths.CUSTOM_PARTS.as_posix())
    p.add_argument("--schema", default=paths.CUSTOM_PARTS_SCHEMA.as_posix())
    args = p.parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        print(f"[error] not found: {path}", file=sys.stderr)
        return 1
    messages = validate_custom_parts(load_json(path), load_json(args.schema))
    for message in messages:
        print(f"[error] {path}: {message}", file=sys.stderr)
    if messages:
        return 1
    print(f"[ok] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
