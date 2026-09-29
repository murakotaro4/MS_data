#!/usr/bin/env python3
"""
msData.json 検証ユーティリティ（uv 前提）

検証内容
- JSON Schema による構造/型チェック（schema/msData.schema.json）
- キーの表記揺れ（別名キー）の検出
- `MS名` の重複チェック

使用例
- 基本検証:          uv run python -m ms_data.validation.validate_msdata msData.json
- 追加で別名をエラー扱い: uv run python -m ms_data.validation.validate_msdata msData.json --fail-on-typo
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from ms_data.core import paths
from ms_data.core.json_io import load_json
from ms_data.core.labels import KEY_ALIASES
from ms_data.core.ms_names import extract_ms_base_name
from ms_data.core.paths import MSDATA_SCHEMA as SCHEMA_PATH


def validate_schema(data: Any, schema_path: Path) -> list[str]:
    """JSON Schema 検証を行い、エラーメッセージのリストを返す。"""
    schema = load_json(schema_path)
    v = Draft7Validator(schema)
    errors = [e.message for e in v.iter_errors(data)]
    return errors


def load_allowed_keys(schema_path: Path) -> set[str]:
    """スキーマが許容するレコードのキー集合を取り出す。"""
    schema = load_json(schema_path)
    return set(schema["items"]["properties"].keys())


def find_typos(records: list[dict[str, Any]]) -> dict[str, int]:
    """別名キー（KEY_ALIASES に登録された表記揺れ）の出現数を数える。"""
    c = Counter()
    for r in records:
        for alias in KEY_ALIASES:
            if alias in r:
                c[alias] += 1
    return dict(c)


def find_duplicate_names(records: list[dict[str, Any]]) -> dict[str, int]:
    """重複する MS名 とその件数を返す。"""
    c = Counter(r.get("MS名") for r in records if isinstance(r.get("MS名"), str))
    return {k: v for k, v in c.items() if v > 1}


def find_unknown_keys(
    records: Iterable[dict[str, Any]], allowed_keys: set[str]
) -> dict[str, int]:
    """スキーマに無いキーの出現数を数える。"""
    counts: Counter[str] = Counter()
    for record in records:
        for key in record:
            if key not in allowed_keys:
                counts[key] += 1
    return dict(counts)


def _fullst_order_key(points: Any) -> int | None:
    """fullst の points を昇順検証用の整数に変換する。

    None（引き継ぎ項目）は先頭扱いの -1、整数化できない値（bool 含む）は
    不正値として None を返す。
    """
    if points is None:
        return -1
    if isinstance(points, bool):
        return None
    try:
        return int(points)
    except (TypeError, ValueError):
        return None


def find_semantic_errors(records: Iterable[dict[str, Any]]) -> list[str]:
    """スキーマでは表現できない意味的な整合性エラーを検出する。

    検査項目:
    - fullst の points が整数/null であること、昇順であること、重複が無いこと
    - 出撃不可の側に旋回値が存在しないこと（地上/宇宙）
    - 同一機体（基底名）の LV 間で属性・wiki_url が一致すること
    """
    errors: list[str] = []
    base_attrs: dict[str, set[str]] = defaultdict(set)
    base_urls: dict[str, set[str]] = defaultdict(set)

    for record in records:
        ms_name = record.get("MS名")
        base_name = extract_ms_base_name(ms_name) if isinstance(ms_name, str) else None

        if base_name:
            attr = record.get("属性")
            if isinstance(attr, str):
                base_attrs[base_name].add(attr)

            wiki_url = record.get("wiki_url")
            if isinstance(wiki_url, str) and wiki_url.strip():
                base_urls[base_name].add(wiki_url.strip())

        fullst = record.get("fullst")
        if isinstance(fullst, list):
            seen_entries: set[tuple[Any, Any, Any]] = set()
            prev_order: int | None = None
            for idx, item in enumerate(fullst):
                if not isinstance(item, dict):
                    continue
                points = item.get("points")
                order = _fullst_order_key(points)
                if order is None:
                    errors.append(
                        f"{ms_name}: fullst points must be an integer or null (index={idx}, value={points!r})"
                    )
                    continue
                if prev_order is not None and order < prev_order:
                    errors.append(
                        f"{ms_name}: fullst points must be sorted ascending (index={idx})"
                    )
                    break
                prev_order = order

                key = (item.get("name"), item.get("level"), order)
                if points is not None:
                    if key in seen_entries:
                        errors.append(
                            f"{ms_name}: duplicated fullst entry detected ({item.get('name')}, level={item.get('level')}, points={order})"
                        )
                        break
                    seen_entries.add(key)

        ground_turn_keys = {"旋回_地上_通常時", "旋回_地上_変形時"}
        space_turn_keys = {"旋回_宇宙_通常時", "旋回_宇宙_変形時"}
        if record.get("出撃_地上可") is False and any(
            key in record for key in ground_turn_keys
        ):
            errors.append(
                f"{ms_name}: ground sortie is false but ground turn values exist"
            )
        if record.get("出撃_宇宙可") is False and any(
            key in record for key in space_turn_keys
        ):
            errors.append(
                f"{ms_name}: space sortie is false but space turn values exist"
            )

    for base_name, attrs in sorted(base_attrs.items()):
        if len(attrs) > 1:
            errors.append(
                f"{base_name}: 属性 mismatch across levels ({', '.join(sorted(attrs))})"
            )
    for base_name, urls in sorted(base_urls.items()):
        if len(urls) > 1:
            errors.append(f"{base_name}: wiki_url mismatch across levels")

    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, nargs="?", default=paths.MSDATA)
    ap.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    ap.add_argument("--fail-on-typo", action="store_true")
    args = ap.parse_args(argv)

    data = load_json(args.path)
    if not isinstance(data, list):
        print("ERROR: top-level must be an array", file=sys.stderr)
        return 2

    dict_records = [r for r in data if isinstance(r, dict)]
    schema_errors = validate_schema(data, args.schema)
    allowed_keys = load_allowed_keys(args.schema)
    typo_counts = find_typos(dict_records)
    duplicates = find_duplicate_names(dict_records)
    unknown_keys = find_unknown_keys(dict_records, allowed_keys)
    semantic_errors = find_semantic_errors(dict_records)

    status = 0
    if schema_errors:
        print("Schema errors (first 20):", file=sys.stderr)
        for e in schema_errors[:20]:
            print(f"  - {e}", file=sys.stderr)
        status = 1

    if unknown_keys:
        print("Unknown keys found:", file=sys.stderr)
        for key, count in sorted(unknown_keys.items(), key=lambda x: (-x[1], x[0])):
            print(f"  - {key}: {count}", file=sys.stderr)
        status = 1

    if duplicates:
        print("Duplicate MS名 detected:", file=sys.stderr)
        for name, count in sorted(duplicates.items(), key=lambda x: (-x[1], x[0])):
            print(f"  - {name}: {count}", file=sys.stderr)
        status = 1

    if semantic_errors:
        print("Semantic errors (first 20):", file=sys.stderr)
        for error in semantic_errors[:20]:
            print(f"  - {error}", file=sys.stderr)
        status = 1

    if typo_counts:
        print("Alias keys (typos) found:", file=sys.stderr)
        for alias, count in sorted(typo_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  - {alias} -> {KEY_ALIASES[alias]}: {count}", file=sys.stderr)
        if args.fail_on_typo:
            status = 1

    if status == 0:
        print(f"OK: validated {len(data)} records")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
