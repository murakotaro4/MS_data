#!/usr/bin/env python3
"""
msData.json 検証ユーティリティ（uv 前提）

検証内容
- JSON Schema による構造/型チェック（schema/msData.schema.json）
- キーの表記揺れ（別名キー）の検出
- `MS名` の重複チェック

使用例
- 基本検証:          uv run python scripts/validate_msdata.py msData.json
- 追加で別名をエラー扱い: uv run python scripts/validate_msdata.py msData.json --fail-on-typo
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schema/msData.schema.json")

KEY_ALIASES = {
    "射撃補則": "射撃補正",
    "射撃補生": "射撃補正",
    "格闘補定": "格闘補正",
    "旋回_通常時_地上": "旋回_地上_通常時",
    "旋回_通常時_宇宙": "旋回_宇宙_通常時",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_schema(data: Any, schema_path: Path) -> List[str]:
    schema = load_json(schema_path)
    v = Draft7Validator(schema)
    errors = [e.message for e in v.iter_errors(data)]
    return errors


def find_typos(records: List[Dict[str, Any]]) -> Dict[str, int]:
    c = Counter()
    for r in records:
        for alias in KEY_ALIASES:
            if alias in r:
                c[alias] += 1
    return dict(c)


def find_duplicate_names(records: List[Dict[str, Any]]) -> Dict[str, int]:
    c = Counter(r.get("MS名") for r in records if isinstance(r.get("MS名"), str))
    return {k: v for k, v in c.items() if v > 1}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, nargs="?", default=Path("msData.json"))
    ap.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    ap.add_argument("--fail-on-typo", action="store_true")
    args = ap.parse_args(argv)

    data = load_json(args.path)
    if not isinstance(data, list):
        print("ERROR: top-level must be an array", file=sys.stderr)
        return 2

    schema_errors = validate_schema(data, args.schema)
    typo_counts = find_typos([r for r in data if isinstance(r, dict)])
    duplicates = find_duplicate_names([r for r in data if isinstance(r, dict)])

    status = 0
    if schema_errors:
        print("Schema errors (first 20):", file=sys.stderr)
        for e in schema_errors[:20]:
            print(f"  - {e}", file=sys.stderr)
        status = 1

    if duplicates:
        print("Duplicate MS名 detected:", file=sys.stderr)
        for name, count in sorted(duplicates.items(), key=lambda x: (-x[1], x[0])):
            print(f"  - {name}: {count}", file=sys.stderr)
        status = 1

    if typo_counts:
        print("Alias keys (typos) found:", file=sys.stderr)
        for alias, count in sorted(typo_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  - {alias} -> {KEY_ALIASES[alias]}: {count}", file=sys.stderr)
        if args.fail-on-typo:
            status = 1

    if status == 0:
        print(f"OK: validated {len(data)} records")
    return status


if __name__ == "__main__":
    raise SystemExit(main())

