"""JSON 読み込みの共通ユーティリティ。

例外はそのまま送出する（SystemExit への変換やログ出力は呼び出し元の責務）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_json_or_default(path: Path | None, default: Any) -> Any:
    """ファイルが無い場合に default を返す寛容版。"""
    if path is None or not path.exists():
        return default
    return load_json(path)
