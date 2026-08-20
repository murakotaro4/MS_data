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

# カウンター欄に登場する既知の種別。未編集ページのテンプレートには
# 候補がそのまま羅列されて残るため、placeholder 判定の語彙として使う。
COUNTER_TYPES = frozenset(
    {
        "押し倒し",
        "投げ",
        "連打攻撃",
        "水平射撃",
        "蹴り飛ばし",
        "連続格闘",
        "膝蹴り",
        "特殊",
    }
)


def normalize_symbol_text(s: str) -> str:
    """全角記号を半角へ寄せ、空白を正規化する（解析前の共通前処理）。"""
    return clean_text(
        s.replace("\u3000", " ")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("％", "%")
        .replace("：", ":")
        .replace("，", ",")
        .replace("（", "(")
        .replace("）", ")")
    )


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


def looks_like_ticket_count(text: str) -> bool:
    """必要階級欄の値がリサイクルチケット数（純数字）かを判定する。

    atwiki のステータステーブルでは「必要リサイクルチケット」と
    「必要階級」が隣接しており、チケット数だけが階級欄へ誤配置される
    ことがある（例: キャノンガン pages/6138, 2026-08-20 実測で LV1=225 /
    LV2=260）。階級の正規値は「少尉01」等の名称か空欄であり、純数字は
    チケット数とみなす。
    """
    t = normalize_symbol_text(text).replace(",", "").replace("\xa0", "")
    return bool(re.fullmatch(r"\d+", t))


def is_counter_placeholder(text: str) -> bool:
    """カウンター欄がテンプレートの候補羅列のまま（未記入）かを判定する。

    正当な値は単一種別か「地上：押し倒し 宇宙：蹴り飛ばし」のような
    接頭辞付きの組み合わせのみ。接頭辞（：/:）なしで既知の種別が
    3 つ以上空白区切りで並ぶ場合はテンプレート未編集とみなす。
    """
    t = clean_text(text)
    if "：" in t or ":" in t:
        return False
    tokens = t.split()
    if len(tokens) < 3:
        return False
    return all(token in COUNTER_TYPES for token in tokens)


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
