#!/usr/bin/env python3
"""
msData.json 更新ユーティリティ（uv 前提）

機能
- 入力 JSON（配列のレコード群）を読み込み、キー表記揺れを正規化
- 既存 msData とのマージ・重複（MS名）解消・ソート
- 公式調整オーバーライドを適用し、未反映の取得元による巻き戻りを防止
- 差分サマリを表示しつつ JSON を整形保存（UTF-8, 2スペース, ソートキー）

使用例
- 既存ファイルを正規化のみ（上書き）:  uv run python -m ms_data.pipeline.update_msdata -i
- 新規データをマージして出力:         uv run python -m ms_data.pipeline.update_msdata -i path/to/new.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, TypedDict
from collections.abc import Iterable

from ms_data.core.json_io import load_json
from ms_data.core.ms_names import MS_NAME_WITH_LEVEL, normalize_ms_base_name
from ms_data.core.paths import OFFICIAL_OVERRIDES_DIR
from ms_data.core.labels import apply_key_aliases


CANONICAL_ORDER = (
    "MS名",
    "wiki_url",
    "属性",
    "出撃_地上可",
    "出撃_宇宙可",
    "環境適正_地上",
    "環境適正_宇宙",
    "環境適正_水中",
    "コスト",
    "HP",
    "耐実弾補正",
    "耐ビーム補正",
    "耐格闘補正",
    "射撃補正",
    "射撃補正_変形時",
    "射撃補正_変身時",
    "格闘補正",
    "格闘補正_変形時",
    "格闘補正_変身時",
    "スピード",
    "スピード_変形時",
    "高速移動",
    "高速移動_変形時",
    "スラスター",
    "旋回_地上_通常時",
    "旋回_宇宙_通常時",
    "旋回_変形時",
    "旋回_地上_変形時",
    "旋回_宇宙_変形時",
    "近スロット",
    "中スロット",
    "遠スロット",
    "カウンター",
    "再出撃時間",
    "格闘判定力",
    "レアリティ",
    "必要階級",
    "必要DP",
    "必要リサイクルチケット",
    "fullst",
)

OFFICIAL_OVERRIDE_VALUE_KEYS = set(CANONICAL_ORDER) - {"MS名"}


class OfficialOverrideValue(TypedDict, total=False):
    value: Any
    stale_value: Any


def normalize_ms_name(name: str) -> str:
    m = MS_NAME_WITH_LEVEL.match(name)
    if not m:
        return name
    base, lv = m.groups()
    return f"{normalize_ms_base_name(base)}_LV{lv}"


def extract_ms_base_name(name: str) -> str | None:
    m = MS_NAME_WITH_LEVEL.match(name)
    if not m:
        return None
    return normalize_ms_base_name(m.group(1))


def load_index_url_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    urls: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        url = entry.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        urls[normalize_ms_base_name(name)] = url
    return urls


INDEX_URL_MAP = load_index_url_map(Path("cache/index.json"))


def normalize_record(rec: dict[str, Any]) -> dict[str, Any]:
    name = rec.get("MS名")
    if isinstance(name, str):
        normalized_name = normalize_ms_name(name)
        rec["MS名"] = normalized_name
        base_name = extract_ms_base_name(normalized_name)
        if base_name and base_name in INDEX_URL_MAP and "wiki_url" not in rec:
            rec["wiki_url"] = INDEX_URL_MAP[base_name]
    # 別名キーを正規キーへ移し替え（既存が無い場合のみ）
    rec = apply_key_aliases(rec)
    # 数値項目で None は削除（schema適合のため）。
    INT_KEYS = {
        "コスト",
        "HP",
        "スピード",
        "スピード_変形時",
        "スラスター",
        "高速移動",
        "高速移動_変形時",
        "射撃補正",
        "射撃補正_変形時",
        "射撃補正_変身時",
        "格闘補正",
        "格闘補正_変形時",
        "格闘補正_変身時",
        "耐ビーム補正",
        "耐実弾補正",
        "耐格闘補正",
        "近スロット",
        "中スロット",
        "遠スロット",
        "旋回_地上_通常時",
        "旋回_地上_変形時",
        "旋回_宇宙_通常時",
        "旋回_宇宙_変形時",
        "旋回_変形時",
        "再出撃時間",
        "必要DP",
        "必要リサイクルチケット",
    }
    for k in list(rec.keys()):
        if k in INT_KEYS and rec.get(k) is None:
            rec.pop(k, None)

    # 出撃可否のフォールバック推定（両方未設定の場合のみ）
    if "出撃_地上可" not in rec and "出撃_宇宙可" not in rec:
        has_g = "旋回_地上_通常時" in rec
        has_s = "旋回_宇宙_通常時" in rec
        if has_g and has_s:
            rec["出撃_地上可"] = True
            rec["出撃_宇宙可"] = True
        elif has_g and not has_s:
            rec["出撃_地上可"] = True
            rec["出撃_宇宙可"] = False
        elif has_s and not has_g:
            rec["出撃_地上可"] = False
            rec["出撃_宇宙可"] = True

    # 回転値の補正: 宇宙専用/地上専用で片側のみ存在する場合、適切な側へ寄せる
    g = rec.get("出撃_地上可")
    s = rec.get("出撃_宇宙可")
    if g is False and s is True:
        if "旋回_宇宙_通常時" not in rec and "旋回_地上_通常時" in rec:
            rec["旋回_宇宙_通常時"] = rec.pop("旋回_地上_通常時")
        if "旋回_宇宙_変形時" not in rec and "旋回_地上_変形時" in rec:
            rec["旋回_宇宙_変形時"] = rec.pop("旋回_地上_変形時")
    if g is True and s is False:
        if "旋回_地上_通常時" not in rec and "旋回_宇宙_通常時" in rec:
            rec["旋回_地上_通常時"] = rec.pop("旋回_宇宙_通常時")
        if "旋回_地上_変形時" not in rec and "旋回_宇宙_変形時" in rec:
            rec["旋回_地上_変形時"] = rec.pop("旋回_宇宙_変形時")
    return rec


def iter_records_from_files(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    for p in paths:
        data = load_json(p)
        if isinstance(data, list):
            for e in data:
                if isinstance(e, dict):
                    yield normalize_record(dict(e))
        elif isinstance(data, dict):
            # 単一レコード or 包含
            yield normalize_record(dict(data))
        else:
            raise ValueError(f"Unsupported JSON structure in {p}")


def merge_by_msname(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rec in records:
        name = rec.get("MS名")
        if not isinstance(name, str):
            # 無名レコードはスキップ
            continue
        merged[name] = rec
    return merged


def load_official_overrides(
    directory: Path = OFFICIAL_OVERRIDES_DIR,
) -> dict[str, dict[str, OfficialOverrideValue]]:
    """公式調整由来の一時オーバーライドを読み込む。

    形式:
    {
      "schema_version": "1",
      "active": true,
      "overrides": [
        {
          "MS名": "ザクⅢ改_LV1",
          "values": {"HP": 27000},
          "stale_values": {"HP": 23500}
        }
      ]
    }
    """

    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise ValueError(f"official overrides path is not a directory: {directory}")

    overrides: dict[str, dict[str, OfficialOverrideValue]] = {}
    for path in sorted(directory.glob("*.json")):
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError(f"official override file must be an object: {path}")
        if data.get("active", True) is False:
            continue
        entries = data.get("overrides", data.get("records", []))
        if not isinstance(entries, list):
            raise ValueError(f"official override entries must be a list: {path}")

        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"official override entry must be an object: {path}#{index}"
                )
            raw_name = entry.get("MS名")
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ValueError(
                    f"official override entry missing MS名: {path}#{index}"
                )
            raw_values = entry.get("values")
            if not isinstance(raw_values, dict) or not raw_values:
                raise ValueError(
                    f"official override entry values must be a non-empty object: "
                    f"{path}#{index}"
                )

            values = apply_key_aliases(dict(raw_values))
            invalid_keys = sorted(set(values) - OFFICIAL_OVERRIDE_VALUE_KEYS)
            if invalid_keys:
                raise ValueError(
                    f"official override entry has invalid keys: {path}#{index} "
                    f"{invalid_keys}"
                )

            raw_stale_values = entry.get("stale_values", {})
            if not isinstance(raw_stale_values, dict):
                raise ValueError(
                    f"official override entry stale_values must be an object: "
                    f"{path}#{index}"
                )
            stale_values = apply_key_aliases(dict(raw_stale_values))
            invalid_stale_keys = sorted(set(stale_values) - set(values))
            if invalid_stale_keys:
                raise ValueError(
                    f"official override stale_values must match values keys: "
                    f"{path}#{index} {invalid_stale_keys}"
                )

            name = normalize_ms_name(raw_name)
            target = overrides.setdefault(name, {})
            for key, value in values.items():
                spec: OfficialOverrideValue = {"value": value}
                if key in stale_values:
                    spec["stale_value"] = stale_values[key]
                target[key] = spec
    return overrides


def apply_official_overrides(
    records_by_name: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, OfficialOverrideValue]],
) -> int:
    """既存/取得済みレコードへ公式オーバーライドを適用する。

    指定された項目だけを書き換えるため、atwiki 側で更新済みの別項目は
    通常どおり取り込まれる。
    """

    changed = 0
    for name, values in overrides.items():
        record = records_by_name.get(name)
        if record is None:
            continue
        for key, spec in values.items():
            value = spec["value"]
            current = record.get(key)
            if current == value:
                continue
            if "stale_value" in spec and current != spec["stale_value"]:
                continue
            record[key] = value
            changed += 1
    return changed


def write_records_snapshot(
    records_by_name: dict[str, dict[str, Any]],
    out_path: Path,
    *,
    sort: bool = True,
) -> None:
    records = list(records_by_name.values())
    if sort:
        records = sort_records(records)
    records = [stable_key_order(r) for r in records]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def sort_records(recs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple[int, str]:
        cost = r.get("コスト")
        if not isinstance(cost, int):
            cost = 0
        name = r.get("MS名") or ""
        return (cost, str(name))

    return sorted(recs, key=key)


def stable_key_order(d: dict[str, Any]) -> dict[str, Any]:
    # 書き出し時の見やすさのために、おおよそのキー順を揃える
    ordered: dict[str, Any] = {}
    for k in CANONICAL_ORDER:
        if k in d:
            ordered[k] = d[k]
    for k in sorted(d.keys() - ordered.keys()):
        ordered[k] = d[k]
    return ordered


def diff_summary(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> str:
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys
    changed = {
        k
        for k in common
        if json.dumps(old[k], sort_keys=True, ensure_ascii=False)
        != json.dumps(new[k], sort_keys=True, ensure_ascii=False)
    }
    return f"records: {len(old_keys)} -> {len(new_keys)} | +{len(added)} -{len(removed)} ~{len(changed)}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inputs", nargs="*", type=Path, help="入力JSON（配列）複数可")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("msData.json"),
        help="出力先（既定: msData.json）",
    )
    ap.add_argument(
        "-i",
        "--in-place",
        action="store_true",
        help="既存 msData.json を正規化/マージして上書き",
    )
    ap.add_argument(
        "--official-overrides-dir",
        type=Path,
        default=OFFICIAL_OVERRIDES_DIR,
        help="公式調整オーバーライドJSONのディレクトリ",
    )
    ap.add_argument(
        "--no-official-overrides",
        action="store_true",
        help="公式調整オーバーライドを適用しない",
    )
    default_raw_out = os.getenv("OFFICIAL_OVERRIDE_RAW_OUT") or None
    ap.add_argument(
        "--official-overrides-raw-out",
        type=Path,
        default=Path(default_raw_out) if default_raw_out else None,
        help="公式調整オーバーライド適用前の入力取得レコードを書き出す",
    )
    ap.add_argument("--no-sort", action="store_true", help="配列の並び替えを行わない")
    ap.add_argument("--dry-run", action="store_true", help="書き込みを行わない")
    args = ap.parse_args(argv)

    out_path = args.output

    base_records: list[dict[str, Any]] = []
    if args.in_place and out_path.exists():
        try:
            base = load_json(out_path)
            if isinstance(base, list):
                base_records = [
                    normalize_record(dict(e)) for e in base if isinstance(e, dict)
                ]
        except Exception:
            pass

    new_records = list(iter_records_from_files(args.inputs)) if args.inputs else []
    merged_old = merge_by_msname(base_records)
    merged_new = merge_by_msname([*base_records, *new_records])

    if args.official_overrides_raw_out is not None:
        write_records_snapshot(
            merge_by_msname(new_records),
            args.official_overrides_raw_out,
            sort=not args.no_sort,
        )

    if not args.no_official_overrides:
        try:
            official_overrides = load_official_overrides(args.official_overrides_dir)
            changed = apply_official_overrides(merged_new, official_overrides)
        except Exception as exc:
            print(f"エラー: 公式調整オーバーライドの適用に失敗: {exc}", file=sys.stderr)
            return 1
        if changed:
            print(
                "official-overrides: "
                f"{len(official_overrides)} records / {changed} values applied",
                file=sys.stderr,
            )

    print(diff_summary(merged_old, merged_new), file=sys.stderr)

    result_list = list(merged_new.values())
    if not args.no_sort:
        result_list = sort_records(result_list)
    result_list = [stable_key_order(r) for r in result_list]

    if args.dry_run:
        return 0

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result_list, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    tmp.replace(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
