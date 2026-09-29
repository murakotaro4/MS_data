"""テスト共通ヘルパー（MS レコード factory / JSON 書き出し）。

pytest が tests/ を sys.path に載せるため `from helpers import ...` で参照する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# schema の required を満たす最小レコード（旋回は地上側で満たす）
_MINIMAL_RECORD: dict[str, Any] = {
    "MS名": "テスト機_LV1",
    "属性": "汎用",
    "コスト": 300,
    "HP": 12000,
    "スピード": 125,
    "スラスター": 65,
    "高速移動": 190,
    "射撃補正": 20,
    "格闘補正": 15,
    "耐ビーム補正": 12,
    "耐実弾補正": 10,
    "耐格闘補正": 8,
    "近スロット": 10,
    "中スロット": 8,
    "遠スロット": 6,
}

# 一般的な地上機を模した任意項目（wiki_url / 旋回 / 出撃可否）
_FULL_EXTRAS: dict[str, Any] = {
    "wiki_url": "https://example.com/ms/test",
    "旋回_地上_通常時": 75,
    "出撃_地上可": True,
    "出撃_宇宙可": True,
}


def make_ms_record(ms_name: str = "テスト機_LV1", **overrides: Any) -> dict[str, Any]:
    """必須項目 + 代表的な任意項目を持つ MS レコードを返す。"""
    record = {**_MINIMAL_RECORD, **_FULL_EXTRAS, "MS名": ms_name}
    record.update(overrides)
    return record


def make_minimal_ms_record(**overrides: Any) -> dict[str, Any]:
    """schema の required だけを満たす MS レコードを返す（旋回・出撃可否なし）。"""
    record = dict(_MINIMAL_RECORD)
    record.update(overrides)
    return record


def write_json(path: Path, data: object, *, indent: int | None = 2) -> None:
    """親ディレクトリを作ってから UTF-8 / ensure_ascii=False で JSON を書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8"
    )
