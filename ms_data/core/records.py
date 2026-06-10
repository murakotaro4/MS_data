"""msData 形式のレコード列を扱う共通ユーティリティ。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_records_by_name(path: Path) -> dict[str, dict[str, Any]]:
    """JSON 配列を読み込み、MS名 をキーにした辞書へ変換する。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"record file must be a JSON array: {path}")
    records: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"record must be an object: {path}#{index}")
        name = item.get("MS名")
        if isinstance(name, str) and name.strip():
            records[name] = item
    return records
