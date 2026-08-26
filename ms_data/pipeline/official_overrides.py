"""公式調整オーバーライドの読み込みと適用。

ゲーム本体のバランス調整が atwiki に反映されるまでの間、msData.json の
特定項目を公式値で上書きし、未反映の取得元による「巻き戻り」を防ぐ仕組み。
定義ファイルは data/official_overrides/*.json（スキーマは
schema/official_overrides.schema.json）。

許容される値キーの集合は呼び出し側（update_msdata の CANONICAL_ORDER 由来）
から注入する。後方互換の窓口は ms_data.pipeline.update_msdata 側にあり、
監査・検証モジュールはそちら経由で参照する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple, TypedDict

from ms_data.core.json_io import load_json
from ms_data.core.labels import apply_key_aliases
from ms_data.core.ms_names import normalize_ms_name


class OfficialOverrideValue(TypedDict, total=False):
    """1項目分のオーバーライド指定。

    - value      : 適用する公式値
    - stale_value: 「この値だったときだけ上書きする」旧値。
      atwiki 側が公式値に追随した後は条件不一致となり適用されなくなる
    """

    value: Any
    stale_value: Any


class ParsedOfficialOverrideData(NamedTuple):
    """検証前の official_overrides 1ファイル分。"""

    data: Any
    active: bool
    entries: Any


def iter_official_override_files(directory: Path) -> list[Path]:
    """official_overrides の JSON ファイルを現行順序で列挙する。"""

    return sorted(directory.glob("*.json"))


def load_official_override_data(path: Path) -> Any:
    """official_overrides の JSON を検証せず読み込む。"""

    return load_json(path)


def parse_official_override_data(data: Any) -> ParsedOfficialOverrideData:
    """active と entries fallback だけを解決し、raw 構造を返す。

    data の型検証は adapter の責務。非 object を渡した場合の例外も変換しない。
    """

    return ParsedOfficialOverrideData(
        data=data,
        active=data.get("active", True) is not False,
        entries=data.get("overrides", data.get("records", [])),
    )


def load_official_overrides(
    directory: Path,
    *,
    valid_value_keys: set[str],
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

    values のキーは valid_value_keys（msData の正規フィールド集合）に
    含まれている必要があり、stale_values のキーは values の部分集合に限る。
    形式不正は ValueError として呼び出し側で実行を止める（黙って無視しない）。
    """

    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise ValueError(f"official overrides path is not a directory: {directory}")

    overrides: dict[str, dict[str, OfficialOverrideValue]] = {}
    for path in iter_official_override_files(directory):
        data = load_official_override_data(path)
        if not isinstance(data, dict):
            raise ValueError(f"official override file must be an object: {path}")
        parsed = parse_official_override_data(data)
        if not parsed.active:
            continue
        entries = parsed.entries
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
            invalid_keys = sorted(set(values) - valid_value_keys)
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
    通常どおり取り込まれる。stale_value 付きの項目は、現在値が stale_value と
    一致するときのみ上書きする（atwiki が追随済みなら触らない）。
    戻り値は書き換えた値の個数。
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
