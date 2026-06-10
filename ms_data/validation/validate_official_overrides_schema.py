"""official_overrides JSON の構造と項目契約を検証する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ms_data.core.json_io import load_json as _load_json
from scripts import update_msdata


def _iter_override_files(directory: Path) -> list[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"official_overrides directory not found: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(
            f"official_overrides path is not a directory: {directory}"
        )
    return sorted(directory.glob("*.json"))


def _validate_schema(path: Path, schema: dict[str, Any]) -> list[str]:
    data = _load_json(path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    messages: list[str] = []
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{path}: {location}: {error.message}")
    return messages


def _validate_stale_value_keys(path: Path) -> list[str]:
    data = _load_json(path)
    entries = data.get("overrides", data.get("records", []))
    messages: list[str] = []
    if not isinstance(entries, list):
        return messages
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        values = entry.get("values")
        stale_values = entry.get("stale_values")
        if not isinstance(values, dict) or not isinstance(stale_values, dict):
            continue
        normalized_values = update_msdata.apply_key_aliases(dict(values))
        normalized_stale_values = update_msdata.apply_key_aliases(dict(stale_values))
        missing = sorted(set(normalized_values) - set(normalized_stale_values))
        extra = sorted(set(normalized_stale_values) - set(normalized_values))
        if missing:
            messages.append(
                f"{path}: overrides/{index}/stale_values missing keys: {missing}"
            )
        if extra:
            messages.append(
                f"{path}: overrides/{index}/stale_values extra keys: {extra}"
            )
    return messages


def validate(
    *,
    overrides_dir: Path,
    schema_path: Path,
) -> list[str]:
    schema = _load_json(schema_path)
    messages: list[str] = []
    files = _iter_override_files(overrides_dir)
    if not files:
        messages.append(f"{overrides_dir}: no official override JSON files found")
        return messages

    for path in files:
        messages.extend(_validate_schema(path, schema))
        messages.extend(_validate_stale_value_keys(path))

    try:
        update_msdata.load_official_overrides(overrides_dir)
    except (
        Exception
    ) as exc:  # noqa: BLE001 - CLI validator should report all contract errors.
        messages.append(f"{overrides_dir}: semantic validation failed: {exc}")
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--overrides-dir",
        type=Path,
        default=update_msdata.OFFICIAL_OVERRIDES_DIR,
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("schema/official_overrides.schema.json"),
    )
    args = parser.parse_args(argv)

    messages = validate(overrides_dir=args.overrides_dir, schema_path=args.schema)
    for message in messages:
        print(f"ERROR: {message}", file=sys.stderr)
    if messages:
        return 1

    print("OK: official_overrides schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
