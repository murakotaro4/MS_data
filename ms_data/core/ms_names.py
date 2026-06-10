"""MS 名（機体名）の解析・正規化ユーティリティ。"""

from __future__ import annotations

import re

MS_NAME_WITH_LEVEL = re.compile(r"^(?P<base>.+)_LV(?P<level>\d+)$")
RE_LV_SUFFIX = re.compile(r"_LV(\d+)$")


def extract_ms_base_name(name: str) -> str | None:
    """"ガンダム_LV3" → "ガンダム"。正規化は行わない。"""
    match = MS_NAME_WITH_LEVEL.match(name)
    if not match:
        return None
    return match.group("base")


def normalize_ms_base_name(name: str) -> str:
    """表記揺れ（括弧・ローマ数字・ギリシャ文字 Z など）を正規化する。"""
    out = name
    out = out.replace("[", "［").replace("]", "］")
    out = out.replace("III", "Ⅲ").replace("II", "Ⅱ")
    out = re.sub(r"ZZ(?=ガンダム)", "ΖΖ", out)
    out = re.sub(r"Z(?=ガンダム3号機)", "Ζ", out)
    out = re.sub(r"Z(?=ガンダム)", "Ζ", out)
    out = out.replace("Ｖ", "V")
    return out


def ms_name_to_series_level(name: str) -> tuple[str, int | None]:
    """"ガンダム_LV3" → ("ガンダム", 3)。LV サフィックスが無ければ (name, None)。"""
    m = RE_LV_SUFFIX.search(name)
    if not m:
        return name, None
    return name[: m.start()], int(m.group(1))
