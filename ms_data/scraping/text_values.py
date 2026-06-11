"""atwiki スクレイピングで使う文字列・数値変換の小物ユーティリティ。

URL の正規化、ページIDや更新経過時間の抽出、TTL 表記（"7d" など）の秒変換、
セル文字列の整数化・可否記号の真偽値化を提供する。
HTML 構造には依存しない純粋な文字列処理のみを置く。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ms_data.core.labels import clean_text

ATWIKI_BASE = "https://w.atwiki.jp"
PAGE_ID_RE = re.compile(r"/pages/(?P<page_id>\d+)\.html$")
UPDATED_AGE_RE = re.compile(r"\((?P<value>\d+)(?P<unit>[mhd])\)\s*$")

# 時間単位の秒換算表（extract_updated_age / parse_ttl で共用）
_SECONDS_PER_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def absolute_url(href: str) -> str:
    """atwiki 内の相対/プロトコル相対リンクを絶対 URL に変換する。"""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return ATWIKI_BASE + href
    if href.startswith("http"):
        return href
    return ATWIKI_BASE + "/" + href.lstrip("/")


def extract_page_id(url: str) -> int | None:
    """atwiki の詳細ページ URL（.../pages/<id>.html）からページ ID を取り出す。"""
    match = PAGE_ID_RE.search(url)
    if not match:
        return None
    return int(match.group("page_id"))


def extract_updated_age(title: str) -> tuple[str | None, int | None]:
    """一覧リンクの title 属性末尾「(3h)」等から更新経過時間を抽出する。

    戻り値は (表記そのまま, 秒換算)。見つからなければ (None, None)。
    """
    title = clean_text(title)
    match = UPDATED_AGE_RE.search(title)
    if not match:
        return None, None
    value = int(match.group("value"))
    unit = match.group("unit")
    return f"{value}{unit}", value * _SECONDS_PER_UNIT[unit]


def parse_iso_datetime(value: str) -> datetime:
    """ISO 8601 文字列を aware な datetime に変換する（"Z" 表記・naive も許容）。"""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_ttl(s: str) -> int:
    """ "7d", "72h", "3600s" などを秒に変換。単位なしは秒と解釈。"""
    s = str(s).strip().lower()
    if not s:
        return 7 * 24 * 3600
    m = re.fullmatch(r"(\d+)([smhd]?)", s)
    if not m:
        return int(float(s))
    val = int(m.group(1))
    unit = m.group(2) or "s"
    return val * _SECONDS_PER_UNIT.get(unit, 1)


def to_int(text: str) -> int | None:
    """セル文字列から最初の整数を取り出す。数値が無ければ None。"""
    if text is None:
        return None
    # 全角→半角、カンマや単位除去
    t = (
        text.replace(",", "")
        .replace("％", "%")
        .replace("秒", "")
        .replace("度/秒", "")
        .replace("[度/秒]", "")
        .replace("\xa0", " ")
    )
    m = re.search(r"-?\d+", t)
    return int(m.group(0)) if m else None


def symbol_to_bool(s: str) -> bool | None:
    """◯/×/可/不可 などの可否表記を真偽値に変換する。判定不能なら None。"""
    t = clean_text(s)
    # 記号/語を可否にマップ
    true_syms = {"◎", "◯", "○", "〇", "△", "可", "可能", "yes", "可○"}
    false_syms = {"×", "不可", "不可能", "no"}
    if t in true_syms:
        return True
    if t in false_syms:
        return False
    # テキスト内に含まれる場合
    if any(x in t for x in ["不可", "×"]):
        return False
    if any(x in t for x in ["可", "可能", "◯", "○", "〇", "◎", "△"]):
        return True
    return None
