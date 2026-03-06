#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator


FILE_SCHEMAS = {
    Path("data/skills_catalog.json"): Path("schema/skills_catalog.schema.json"),
    Path("data/skill_owners.json"): Path("schema/skill_owners.schema.json"),
    Path("data/skills_params.json"): Path("schema/skills_params.schema.json"),
    Path("data/skill_owners_flat.json"): Path("schema/skill_owners_flat.schema.json"),
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_against_schema(data: Any, schema_path: Path) -> list[str]:
    schema = load_json(schema_path)
    validator = Draft7Validator(schema)
    return [error.message for error in validator.iter_errors(data)]


def validate_file(data_path: Path, schema_path: Path) -> list[str]:
    if not data_path.exists():
        return [f"missing file: {data_path}"]
    if not schema_path.exists():
        return [f"missing schema: {schema_path}"]
    data = load_json(data_path)
    return validate_against_schema(data, schema_path)


def resolve_targets(paths: list[Path]) -> tuple[dict[Path, Path], list[str]]:
    if not paths:
        return FILE_SCHEMAS, []

    known_by_resolved = {
        path.resolve(): (path, schema_path)
        for path, schema_path in FILE_SCHEMAS.items()
    }
    targets: dict[Path, Path] = {}
    errors: list[str] = []
    for path in paths:
        resolved = path.resolve()
        matched = known_by_resolved.get(resolved)
        if matched is None:
            supported = ", ".join(str(candidate) for candidate in sorted(FILE_SCHEMAS))
            errors.append(f"unsupported path: {path} (supported: {supported})")
            continue
        canonical_path, schema_path = matched
        targets[canonical_path] = schema_path
    return targets, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate committed skills data files")
    ap.add_argument(
        "--path",
        dest="paths",
        action="append",
        type=Path,
        default=[],
        help="Validate only the given data file(s)",
    )
    args = ap.parse_args(argv)

    targets, target_errors = resolve_targets(args.paths)
    if target_errors:
        for error in target_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2

    status = 0
    for data_path, schema_path in targets.items():
        errors = validate_file(data_path, schema_path)
        if errors:
            print(f"Schema errors: {data_path}", file=sys.stderr)
            for error in errors[:20]:
                print(f"  - {error}", file=sys.stderr)
            status = 1
        else:
            print(f"OK: {data_path}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
