"""差分検出: 一覧（index）から再取得が必要な機体だけを選び出す。

毎日の自動更新で全ページを取得し直すと atwiki への負荷が大きいため、
一覧ページに出る「更新経過時間」と前回実行の記録（プロビナンス・
詳細取得状態）を突き合わせて、変化した可能性のあるページだけを選ぶ。

選定モードは3つ（select_changed_index_items の docstring 参照）:
- full       : 全件選択（--force-full）
- revalidate : 週次再検証。機体ごとに更新時刻と前回取得時刻を直接比較
- fast       : 平日の通常運転。前回実行時刻からの経過で足切り

選ばれた項目には change_reasons（選定理由のリスト）が付与される。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ms_data.core.ms_names import extract_ms_base_name
from ms_data.scraping.text_values import parse_iso_datetime


def find_latest_provenance(
    reports_dir: Path,
) -> tuple[Path | None, dict[str, Any] | None]:
    """reports/ から generated_at が最新のプロビナンスを探す。

    壊れたファイル・generated_at 欠落はスキップする。
    """
    latest_path: Path | None = None
    latest_data: dict[str, Any] | None = None
    latest_generated_at: datetime | None = None
    for path in sorted(reports_dir.glob("provenance_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            generated_at = parse_iso_datetime(str(data["generated_at"]))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if latest_generated_at is None or generated_at > latest_generated_at:
            latest_generated_at = generated_at
            latest_path = path
            latest_data = data
    return latest_path, latest_data


def load_msdata_base_index(path: Path) -> dict[str, dict[str, Any]]:
    """msData.json を「基底名 → コスト/属性/wiki_url」の索引に変換する。

    LV 違いは同じ基底名に畳む（最初に現れたレコードを採用）。
    読めない・形式不正の場合は空 dict を返し、呼び出し側で全件扱いになる。
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for record in data:
        if not isinstance(record, dict):
            continue
        ms_name = record.get("MS名")
        if not isinstance(ms_name, str):
            continue
        base_name = extract_ms_base_name(ms_name)
        if not base_name or base_name in result:
            continue
        result[base_name] = {
            "cost": record.get("コスト"),
            "attr": record.get("属性"),
            "wiki_url": record.get("wiki_url"),
        }
    return result


def _detail_state_fetched_at(
    detail_fetch_state: dict[str, dict[str, Any]], url: str
) -> datetime | None:
    """詳細取得状態から該当 URL の前回取得時刻を返す（無効値は None）。"""
    entry = detail_fetch_state.get(url)
    if not isinstance(entry, dict):
        return None
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, str):
        return None
    try:
        return parse_iso_datetime(fetched_at)
    except (TypeError, ValueError):
        return None


def _identity_reasons(
    item: dict[str, Any], previous_msdata_index: dict[str, dict[str, Any]]
) -> list[str]:
    """index 項目と既存 msData の同一性を比較し、差分理由を返す。

    理由の意味:
    - new_name        : msData に存在しない機体（新規追加）
    - cost_changed    : 一覧のコストが msData と異なる
    - attr_changed    : 一覧の属性が msData と異なる
    - wiki_url_changed: 詳細ページ URL が変わった（ページ移転）
    """
    reasons: list[str] = []
    name = item.get("name")
    existing = previous_msdata_index.get(name) if isinstance(name, str) else None
    if existing is None:
        reasons.append("new_name")
        return reasons
    item_cost = item.get("cost")
    if isinstance(item_cost, int) and existing.get("cost") != item_cost:
        reasons.append("cost_changed")
    item_attr = item.get("属性")
    if isinstance(item_attr, str) and item_attr and existing.get("attr") != item_attr:
        reasons.append("attr_changed")
    current_url = item.get("url")
    if (
        isinstance(current_url, str)
        and isinstance(existing.get("wiki_url"), str)
        and existing.get("wiki_url") != current_url
    ):
        reasons.append("wiki_url_changed")
    return reasons


def _stale_detail_reason(
    item: dict[str, Any],
    *,
    stale_detail_enabled: bool,
    detail_fetch_state: dict[str, dict[str, Any]] | None,
    stale_detail_seconds: int | None,
    now_utc: datetime,
) -> list[str]:
    """前回の詳細取得が古すぎる（または記録が無い）場合に理由を返す。

    stale_detail_cache: 前回取得から stale_detail_seconds 以上経過、
    もしくは取得記録なし。キャッシュの陳腐化を防ぐ保険として、
    更新検知に漏れたページも一定周期で再取得させる。
    """
    url = item.get("url")
    if not (stale_detail_enabled and isinstance(url, str)):
        return []
    fetched_at = _detail_state_fetched_at(detail_fetch_state or {}, url)
    if fetched_at is None:
        return ["stale_detail_cache"]
    detail_age_seconds = int(
        max(0, (now_utc - fetched_at.astimezone(timezone.utc)).total_seconds())
    )
    if detail_age_seconds >= int(stale_detail_seconds or 0):
        return ["stale_detail_cache"]
    return []


def _append_selected(
    item: dict[str, Any],
    reasons: list[str],
    selected: list[dict[str, Any]],
    reason_counts: dict[str, int],
) -> None:
    """理由付きで選択リストに追加し、理由別カウントを更新する。"""
    selected_item = dict(item)
    selected_item["change_reasons"] = reasons
    selected.append(selected_item)
    for reason in reasons:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1


def select_changed_index_items(
    items: list[dict[str, Any]],
    *,
    previous_generated_at: datetime | None,
    previous_msdata_index: dict[str, dict[str, Any]],
    now: datetime | None = None,
    freshness_window_seconds: int = 3600,
    force_full: bool = False,
    revalidate: bool = False,
    min_age_coverage: float = 0.95,
    detail_fetch_state: dict[str, dict[str, Any]] | None = None,
    stale_detail_seconds: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """index 項目から再取得候補を選び、(候補リスト, 選定メタ情報) を返す。

    モードと判定基準:
    - full（force_full=True）: 無条件に全件。
    - revalidate: 機体ごとに「ページ最終更新の最遅推定時刻
      （now - updated_age_seconds）が前回取得時刻より新しいか」を直接比較。
      前回プロビナンスに依存しないため、平日 fast 更新の失敗や
      取りこぼしを週次で回復できる（atwiki が ETag 非対応のための代替）。
    - fast: 前回実行からの経過時間 + 鮮度ウィンドウを閾値とし、
      updated_age_seconds がそれ以下（=前回実行以降に更新があり得る）の
      項目を選ぶ。同一性差分（_identity_reasons）と陳腐化
      （_stale_detail_reason）も常に併用する。

    フォールバック（全件選択に切り替える条件）:
    - missing_previous_provenance: fast で前回実行時刻が不明
    - low_age_coverage: updated_age_seconds の取得率が min_age_coverage 未満
      （一覧ページの構造変化などで更新時刻が信頼できない状態）
    """
    now = now or datetime.now(timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    total_count = len(items)
    age_count = sum(
        1 for item in items if isinstance(item.get("updated_age_seconds"), int)
    )
    age_coverage = (age_count / total_count) if total_count else 1.0
    stale_detail_enabled = (
        detail_fetch_state is not None
        and isinstance(stale_detail_seconds, int)
        and stale_detail_seconds > 0
    )

    meta: dict[str, Any] = {
        "mode": "full" if force_full else ("revalidate" if revalidate else "fast"),
        "fast_path": True,
        "fallback_reason": "",
        "candidate_count": 0,
        "total_count": total_count,
        "age_coverage": age_coverage,
        "freshness_window_seconds": freshness_window_seconds,
        "previous_generated_at": (
            previous_generated_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if previous_generated_at
            else None
        ),
        "elapsed_seconds": None,
        "threshold_seconds": None,
        "stale_detail_seconds": stale_detail_seconds if stale_detail_enabled else None,
        "detail_fetch_state_count": len(detail_fetch_state or {}),
        "reason_counts": {},
    }

    stale_kwargs = {
        "stale_detail_enabled": stale_detail_enabled,
        "detail_fetch_state": detail_fetch_state,
        "stale_detail_seconds": stale_detail_seconds,
        "now_utc": now_utc,
    }

    if force_full:
        meta["fast_path"] = False
        meta["fallback_reason"] = "force_full"
        meta["candidate_count"] = total_count
        return items, meta

    if revalidate:
        meta["fast_path"] = False
        if age_coverage < min_age_coverage:
            meta["fallback_reason"] = "low_age_coverage"
            meta["candidate_count"] = total_count
            return items, meta
        meta["fallback_reason"] = "revalidate"
        return _select_revalidate(items, previous_msdata_index, meta, **stale_kwargs)

    if previous_generated_at is None:
        meta["fast_path"] = False
        meta["fallback_reason"] = "missing_previous_provenance"
        meta["candidate_count"] = total_count
        return items, meta

    if age_coverage < min_age_coverage:
        meta["fast_path"] = False
        meta["fallback_reason"] = "low_age_coverage"
        meta["candidate_count"] = total_count
        return items, meta

    return _select_fast(
        items,
        previous_msdata_index,
        meta,
        previous_generated_at=previous_generated_at,
        freshness_window_seconds=freshness_window_seconds,
        **stale_kwargs,
    )


def _finish(
    selected: list[dict[str, Any]],
    reason_counts: dict[str, int],
    meta: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """候補数・理由別カウントを meta に反映して返す。"""
    meta["candidate_count"] = len(selected)
    meta["reason_counts"] = reason_counts
    return selected, meta


def _select_revalidate(
    items: list[dict[str, Any]],
    previous_msdata_index: dict[str, dict[str, Any]],
    meta: dict[str, Any],
    *,
    now_utc: datetime,
    stale_detail_enabled: bool,
    detail_fetch_state: dict[str, dict[str, Any]] | None,
    stale_detail_seconds: int | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """週次再検証モードの選定。

    機体ごとの選定理由:
    - missing_age          : 一覧から更新経過時間が取れなかった
    - missing_fetch_history: 詳細取得の記録なし（未取得 or 前回失敗）
    - updated_since_fetch  : ページの最終更新（の最遅推定時刻）が
                             前回取得より新しい
    - _identity_reasons / _stale_detail_reason 由来の理由も併用
    """
    selected: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    for item in items:
        reasons = _identity_reasons(item, previous_msdata_index)
        age_seconds = item.get("updated_age_seconds")
        url = item.get("url")
        fetched_at = (
            _detail_state_fetched_at(detail_fetch_state or {}, url)
            if isinstance(url, str)
            else None
        )
        if age_seconds is None:
            reasons.append("missing_age")
        if fetched_at is None:
            # 取得履歴なし（未取得 or 前回失敗）は必ず再取得。
            # stale_detail_cache も None で発火するため重複計上を避けて省略
            reasons.append("missing_fetch_history")
        else:
            if isinstance(age_seconds, int) and fetched_at.astimezone(
                timezone.utc
            ) <= now_utc - timedelta(seconds=age_seconds):
                # ページの最終更新（の最遅推定時刻）が前回取得より新しい
                reasons.append("updated_since_fetch")
            reasons.extend(
                _stale_detail_reason(
                    item,
                    stale_detail_enabled=stale_detail_enabled,
                    detail_fetch_state=detail_fetch_state,
                    stale_detail_seconds=stale_detail_seconds,
                    now_utc=now_utc,
                )
            )

        if reasons:
            _append_selected(item, reasons, selected, reason_counts)
    return _finish(selected, reason_counts, meta)


def _select_fast(
    items: list[dict[str, Any]],
    previous_msdata_index: dict[str, dict[str, Any]],
    meta: dict[str, Any],
    *,
    previous_generated_at: datetime,
    freshness_window_seconds: int,
    now_utc: datetime,
    stale_detail_enabled: bool,
    detail_fetch_state: dict[str, dict[str, Any]] | None,
    stale_detail_seconds: int | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """fast モード（平日の通常運転）の選定。

    閾値 = 前回実行からの経過秒 + 鮮度ウィンドウ。
    updated_age_seconds がこの閾値以下なら「前回実行以降に更新があり得る」
    として選定する（recent_update）。鮮度ウィンドウは一覧ページ自体の
    キャッシュ遅延を吸収するためのマージン。

    機体ごとの選定理由:
    - missing_age  : 一覧から更新経過時間が取れなかった
    - recent_update: 上記の閾値判定に該当
    - _identity_reasons / _stale_detail_reason 由来の理由も併用
    """
    elapsed_seconds = max(
        0,
        int((now_utc - previous_generated_at.astimezone(timezone.utc)).total_seconds()),
    )
    threshold_seconds = elapsed_seconds + freshness_window_seconds
    meta["elapsed_seconds"] = elapsed_seconds
    meta["threshold_seconds"] = threshold_seconds

    selected: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    for item in items:
        reasons = _identity_reasons(item, previous_msdata_index)

        age_seconds = item.get("updated_age_seconds")
        if age_seconds is None:
            reasons.append("missing_age")
        elif age_seconds <= threshold_seconds:
            reasons.append("recent_update")

        reasons.extend(
            _stale_detail_reason(
                item,
                stale_detail_enabled=stale_detail_enabled,
                detail_fetch_state=detail_fetch_state,
                stale_detail_seconds=stale_detail_seconds,
                now_utc=now_utc,
            )
        )

        if reasons:
            _append_selected(item, reasons, selected, reason_counts)

    return _finish(selected, reason_counts, meta)
