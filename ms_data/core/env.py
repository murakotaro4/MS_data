"""環境変数の取得ヘルパー（ワークフロー・CLI からの設定値解決に使用）。"""

from __future__ import annotations

import os


def env_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def env_int(name: str, default: int) -> int:
    value = env_str(name)
    if value is None:
        return default
    return int(value)


def env_float(name: str, default: float) -> float:
    value = env_str(name)
    if value is None:
        return default
    return float(value)


def env_flag(name: str) -> bool:
    value = (env_str(name, "") or "").strip().lower()
    return value not in {"", "0", "false", "no", "off"}
