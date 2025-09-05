#!/usr/bin/env python3
"""
msData.json 更新ユーティリティ（uv 前提）

機能
- 入力 JSON（配列のレコード群）を読み込み、キー表記揺れを正規化
- 既存 msData とのマージ・重複（MS名）解消・ソート
- 差分サマリを表示しつつ JSON を整形保存（UTF-8, 2スペース, ソートキー）

使用例
- 既存ファイルを正規化のみ（上書き）:  uv run python scripts/update_msdata.py -i
- 新規データをマージして出力:         uv run python scripts/update_msdata.py -i path/to/new.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


CANONICAL_ORDER = (
    "MS名",
    "属性",
    "コスト",
    "HP",
    "スピード",
    "スラスター",
    "高速移動",
    "射撃補正",
    "格闘補正",
    "耐ビーム補正",
    "耐実弾補正",
    "耐格闘補正",
    "近スロット",
    "中スロット",
    "遠スロット",
    "旋回_地上_通常時",
    "旋回_宇宙_通常時",
    "カウンター",
    "再出撃時間",
    "格闘判定力",
    "fullst",
)

# 表記揺れ → 正規キー
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


def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    # 別名キーを正規キーへ移し替え（既存が無い場合のみ）
    for alias, target in KEY_ALIASES.items():
        if alias in rec and target not in rec:
            rec[target] = rec.pop(alias)
        elif alias in rec:
            rec.pop(alias)
    return rec


def iter_records_from_files(paths: Iterable[Path]) -> Iterable[Dict[str, Any]]:
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


def merge_by_msname(records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        name = rec.get("MS名")
        if not isinstance(name, str):
            # 無名レコードはスキップ
            continue
        merged[name] = rec
    return merged


def sort_records(recs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(r: Dict[str, Any]) -> Tuple[int, str]:
        cost = r.get("コスト")
        if not isinstance(cost, int):
            cost = 0
        name = r.get("MS名") or ""
        return (cost, str(name))

    return sorted(recs, key=key)


def stable_key_order(d: Dict[str, Any]) -> Dict[str, Any]:
    # 書き出し時の見やすさのために、おおよそのキー順を揃える
    ordered: Dict[str, Any] = {}
    for k in CANONICAL_ORDER:
        if k in d:
            ordered[k] = d[k]
    for k in sorted(d.keys() - ordered.keys()):
        ordered[k] = d[k]
    return ordered


def diff_summary(old: Dict[str, Dict[str, Any]], new: Dict[str, Dict[str, Any]]) -> str:
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
    return (
        f"records: {len(old_keys)} -> {len(new_keys)} | +{len(added)} -{len(removed)} ~{len(changed)}"
    )


def main(argv: List[str] | None = None) -> int:
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
    ap.add_argument("--no-sort", action="store_true", help="配列の並び替えを行わない")
    ap.add_argument("--dry-run", action="store_true", help="書き込みを行わない")
    args = ap.parse_args(argv)

    out_path = args.output

    base_records: List[Dict[str, Any]] = []
    if args.in_place and out_path.exists():
        try:
            base = load_json(out_path)
            if isinstance(base, list):
                base_records = [normalize_record(dict(e)) for e in base if isinstance(e, dict)]
        except Exception:
            pass

    new_records = list(iter_records_from_files(args.inputs)) if args.inputs else []
    merged_old = merge_by_msname(base_records)
    merged_new = merge_by_msname([*base_records, *new_records])

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

