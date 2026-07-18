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
from typing import Any
from collections.abc import Iterable

from ms_data.core.json_io import load_json
from ms_data.core.ms_names import (
    MS_NAME_WITH_LEVEL,
    normalize_ms_base_name,
    normalize_ms_name,
)
from ms_data.core.paths import OFFICIAL_OVERRIDES_DIR
from ms_data.core.labels import apply_key_aliases

# 後方互換 re-export（監査・検証モジュールとテストが本モジュール属性として参照）
from ms_data.pipeline import official_overrides as _official_overrides
from ms_data.pipeline.official_overrides import (
    OfficialOverrideValue,
    apply_official_overrides,
)


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

# オーバーライドで指定可能な値キーの集合（MS名は識別子なので除外）
OFFICIAL_OVERRIDE_VALUE_KEYS = set(CANONICAL_ORDER) - {"MS名"}

# 数値項目のうち None を「未取得」とみなして削除するキー（schema 適合のため）
NULLABLE_INT_KEYS = {
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


def extract_ms_base_name(name: str) -> str | None:
    """LV 付き機体名から正規化済みの基底名を取り出す。

    注意: core.ms_names.extract_ms_base_name と異なり、基底名の表記揺れ
    正規化（normalize_ms_base_name）まで行う。
    """
    m = MS_NAME_WITH_LEVEL.match(name)
    if not m:
        return None
    return normalize_ms_base_name(m.group(1))


def load_index_url_map(path: Path) -> dict[str, str]:
    """cache/index.json から「正規化済み基底名 → wiki_url」の対応表を作る。"""
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


# import 時に cache/index.json を読み込むモジュール状態。
# テストが本モジュール属性として monkeypatch する前提のため、
# 名前・初期化タイミングを変更しないこと。
INDEX_URL_MAP = load_index_url_map(Path("cache/index.json"))


def _normalize_name_and_url(rec: dict[str, Any]) -> None:
    """MS名の表記揺れを正規化し、wiki_url 欠落を index 由来の値で補完する。

    INDEX_URL_MAP はモジュール global 経由で参照する（テストが差し替えるため）。
    """
    name = rec.get("MS名")
    if not isinstance(name, str):
        return
    normalized_name = normalize_ms_name(name)
    rec["MS名"] = normalized_name
    base_name = extract_ms_base_name(normalized_name)
    if base_name and base_name in INDEX_URL_MAP and "wiki_url" not in rec:
        rec["wiki_url"] = INDEX_URL_MAP[base_name]


def _drop_null_int_values(rec: dict[str, Any]) -> None:
    """数値項目の None を「未取得」として削除する（schema 適合のため）。"""
    for k in list(rec.keys()):
        if k in NULLABLE_INT_KEYS and rec.get(k) is None:
            rec.pop(k, None)


def _infer_deployment(rec: dict[str, Any]) -> None:
    """出撃可否が両方未設定の場合、旋回値がどちら側にあるかで推定する。

    scraping 側（detail_page.apply_deployment_fallbacks）にも同種の推定が
    あるが、パイプライン二段の防御的重複として意図的に残している
    （スクレイプを経ない手動投入レコードもここで補完される）。
    """
    if "出撃_地上可" in rec or "出撃_宇宙可" in rec:
        return
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


def _fix_turn_side(rec: dict[str, Any]) -> None:
    """宇宙専用/地上専用機で誤った側に入った旋回値を正しいキーへ寄せる。

    scraping 側（detail_page.normalize_turn_values）と同種の補正の
    防御的重複（_infer_deployment と同じ理由）。
    """
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


def normalize_record(rec: dict[str, Any]) -> dict[str, Any]:
    """取得レコード1件を msData の正規形に整える。

    処理順序に依存関係があるため変更しないこと:
    MS名正規化 → 別名キー適用 → None 数値の削除 → 出撃可否の推定 →
    旋回キーの補正（出撃可否確定後でないと判定できない）。
    """
    _normalize_name_and_url(rec)
    # 別名キーを正規キーへ移し替え（既存が無い場合のみ）
    rec = apply_key_aliases(rec)
    _drop_null_int_values(rec)
    _infer_deployment(rec)
    _fix_turn_side(rec)
    return rec


def iter_records_from_files(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    """入力 JSON 群からレコードを正規化しながら順に取り出す。"""
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
    """MS名をキーに後勝ちでマージする（同名は新しいレコードで置き換え）。"""
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
    """公式調整オーバーライドを読み込む（後方互換の窓口）。

    実装は ms_data.pipeline.official_overrides。許容キー集合
    （CANONICAL_ORDER 由来の OFFICIAL_OVERRIDE_VALUE_KEYS）を束ねて委譲する。
    """
    return _official_overrides.load_official_overrides(
        directory, valid_value_keys=OFFICIAL_OVERRIDE_VALUE_KEYS
    )


def write_records_snapshot(
    records_by_name: dict[str, dict[str, Any]],
    out_path: Path,
    *,
    sort: bool = True,
) -> None:
    """レコード群を msData.json と同じ整形ルールで書き出す。"""
    records = list(records_by_name.values())
    if sort:
        records = sort_records(records)
    records = [stable_key_order(r) for r in records]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def sort_records(recs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """コスト昇順 → MS名昇順で並べ替える。"""

    def key(r: dict[str, Any]) -> tuple[int, str]:
        cost = r.get("コスト")
        if not isinstance(cost, int):
            cost = 0
        name = r.get("MS名") or ""
        return (cost, str(name))

    return sorted(recs, key=key)


def stable_key_order(d: dict[str, Any]) -> dict[str, Any]:
    """CANONICAL_ORDER に従ってキー順を揃える（未知キーは末尾にソート順）。"""
    # 書き出し時の見やすさのために、おおよそのキー順を揃える
    ordered: dict[str, Any] = {}
    for k in CANONICAL_ORDER:
        if k in d:
            ordered[k] = d[k]
    for k in sorted(d.keys() - ordered.keys()):
        ordered[k] = d[k]
    return ordered


def diff_summary(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> str:
    """更新前後のレコード数と追加/削除/変更件数の1行サマリを作る。"""
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
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"warning: failed to load base data from {out_path}: {exc}",
                file=sys.stderr,
            )
        else:
            if isinstance(base, list):
                base_records = [
                    normalize_record(dict(e)) for e in base if isinstance(e, dict)
                ]

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
