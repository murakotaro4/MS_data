"""JST 日付の生成・解析に使用する共通ヘルパー。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def parse_yyyymmdd_jst(yyyymmdd: str) -> datetime:
    return datetime.strptime(yyyymmdd, "%Y%m%d").replace(tzinfo=JST)


def today_jst() -> str:
    return datetime.now(JST).strftime("%Y%m%d")
