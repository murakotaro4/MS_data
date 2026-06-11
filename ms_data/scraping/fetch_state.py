"""詳細ページ取得状態（detail_fetch_state）と取得統計の永続化。

detail_fetch_state.json は「URL → 最終取得の成否・時刻・セマンティックハッシュ」
を記録し、差分検出（change_detection）の陳腐化判定や週次再検証の比較に使う。
fetch_stats.json は atwiki への実負荷（リクエスト数・受信バイト数）の計測記録。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ms_data.core.json_io import load_json_or_default
from ms_data.scraping.text_values import extract_page_id


def load_detail_fetch_state(path: Path) -> dict[str, dict[str, Any]]:
    """detail_fetch_state.json を読み「URL → 取得記録」の dict にする。

    読めない・形式不正の場合は空 dict（全件未取得扱い）。
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    items = data.get("items")
    if isinstance(items, dict):
        return {
            str(url): entry for url, entry in items.items() if isinstance(entry, dict)
        }

    # Backward-compatible shape for ad-hoc state files: {url: {fetched_at: ...}}.
    return {
        str(url): entry
        for url, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("fetched_at"), str)
    }


def _utc_iso(value: datetime) -> str:
    """datetime を UTC の ISO 8601（"Z" 終端）文字列にする。"""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_detail_fetch_state(
    path: Path,
    items: dict[str, dict[str, Any]],
    generated_at: datetime,
    run_started_at: datetime | None = None,
) -> None:
    """取得状態を URL 昇順に整列して JSON 保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _utc_iso(generated_at),
        "items": dict(sorted(items.items())),
    }
    if run_started_at is not None:
        payload["run_started_at"] = _utc_iso(run_started_at)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def remember_detail_fetch(
    detail_state: dict[str, dict[str, Any]],
    url: str,
    item: dict[str, Any],
    meta: dict[str, Any],
    attempted_at: datetime | None = None,
) -> None:
    """取得成功を detail_state に記録する（キャッシュメタの時刻・ハッシュ付き）。"""
    fetched_at = meta.get("fetched_at")
    if not isinstance(fetched_at, str):
        fetched_at = _utc_iso(datetime.now(timezone.utc))
    detail_state[url] = {
        "name": item.get("name"),
        "page_id": item.get("page_id") or extract_page_id(url),
        "attempted_at": _utc_iso(attempted_at or datetime.now(timezone.utc)),
        "ok": True,
        "fetched_at": fetched_at,
        "http_status": meta.get("http_status"),
        "semantic_sha256": meta.get("semantic_sha256"),
    }


def remember_detail_fetch_failure(
    detail_state: dict[str, dict[str, Any]],
    url: str,
    item: dict[str, Any],
    error: Exception,
    attempted_at: datetime,
) -> None:
    """取得失敗を detail_state に記録する（fetched_at を持たない＝要再取得）。"""
    detail_state[url] = {
        "name": item.get("name"),
        "page_id": item.get("page_id") or extract_page_id(url),
        "attempted_at": _utc_iso(attempted_at),
        "ok": False,
        "http_status": None,
        "error": str(error),
    }


def write_fetch_stats(
    path: Path,
    phase: str,
    stats: dict[str, int],
    *,
    started_at: datetime,
    duration_seconds: float,
    reset: bool = False,
) -> None:
    """フェーズ別のネットワーク取得統計を JSON にマージ保存する。

    atwiki への実負荷（リクエスト数・受信バイト数）を検証可能にするための計測。
    同一実行内の index/details など複数フェーズを1ファイルに集約し、
    totals を再計算する。body_bytes は Content-Encoding 展開後のボディ長
    （実転送量は圧縮分だけ小さい。実行間の相対比較には影響しない）。
    reset=True で前回実行のフェーズを破棄する（実行の先頭フェーズで指定し、
    走らなかったフェーズの前回値が totals に混入するのを防ぐ）。
    """
    payload: dict[str, Any] = {"phases": {}}
    if not reset and path.exists():
        existing = load_json_or_default(path, {})
        if isinstance(existing, dict) and isinstance(existing.get("phases"), dict):
            payload["phases"] = existing["phases"]

    payload["phases"][phase] = {
        **stats,
        "started_at": _utc_iso(started_at),
        "duration_seconds": round(duration_seconds, 3),
    }
    totals: dict[str, Any] = {}
    for entry in payload["phases"].values():
        for key, value in entry.items():
            if key == "started_at":
                continue
            if isinstance(value, (int, float)):
                totals[key] = round(totals.get(key, 0) + value, 3)
    payload["totals"] = totals
    payload["generated_at"] = _utc_iso(datetime.now(timezone.utc))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
