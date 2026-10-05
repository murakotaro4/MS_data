"""期限確認の対象選定と、今回の取得証拠の共通判定。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from ms_data.core.dates import JST
from ms_data.core.ms_names import extract_ms_base_name, normalize_ms_base_name
from ms_data.pipeline import official_overrides, update_msdata


def parse_date(value: str) -> date:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date()
    return date.fromisoformat(value)


def audit_date(value: str | None) -> date:
    if value:
        return parse_date(value)
    return datetime.now(JST).date()


def _date_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def load_lifecycle_metadata(
    directory: Path,
) -> dict[tuple[str, str], dict[str, str]]:
    """override 値単位の期限メタデータを読み込む。"""

    if not directory.exists() or not directory.is_dir():
        return {}

    # 期限情報だけを読む経路でも、適用経路と同じ strict 契約を先に通す。
    update_msdata.load_official_overrides(directory)

    metadata: dict[tuple[str, str], dict[str, str]] = {}
    for path in official_overrides.iter_official_override_files(directory):
        data = official_overrides.load_official_override_data(path)
        parsed = official_overrides.parse_official_override_data(data, source=path)
        if not parsed.active:
            continue

        file_review_after = _date_text(parsed.data.get("review_after"))
        file_remove_after = _date_text(parsed.data.get("remove_after"))
        entries = parsed.entries
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("MS名")
            raw_values = entry.get("values")
            if not isinstance(raw_name, str) or not isinstance(raw_values, dict):
                continue
            values = update_msdata.apply_key_aliases(dict(raw_values))
            name = update_msdata.normalize_ms_name(raw_name)
            review_after = _date_text(entry.get("review_after")) or file_review_after
            remove_after = _date_text(entry.get("remove_after")) or file_remove_after
            for field in values:
                metadata[(name, field)] = {
                    "file": path.name,
                    "review_after": review_after,
                    "remove_after": remove_after,
                }
    return metadata


def classify_lifecycle(meta: dict[str, str], today: date) -> str:
    remove_after = meta.get("remove_after", "")
    review_after = meta.get("review_after", "")
    if remove_after and today >= parse_date(remove_after):
        return "remove_due"
    if review_after and today >= parse_date(review_after):
        return "review_due"
    if remove_after or review_after:
        return "scheduled"
    return "not_set"


def due_base_names(directory: Path, today: date) -> set[str]:
    return {
        extract_ms_base_name(name) or name
        for (name, _field), meta in load_lifecycle_metadata(directory).items()
        if classify_lifecycle(meta, today) in {"review_due", "remove_due"}
    }


def include_due_items(
    items: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    meta: dict[str, Any],
    directory: Path,
    today: date,
) -> list[dict[str, Any]]:
    """通常の選定理由を維持し、期限確認理由を独立して加える。"""
    due = due_base_names(directory, today)
    by_url = {item.get("url"): dict(item) for item in selected}
    due_urls: set[str] = set()
    for item in items:
        if normalize_ms_base_name(item.get("name", "")) not in due or not item.get(
            "url"
        ):
            continue
        url = item["url"]
        candidate = by_url.setdefault(url, dict(item))
        candidate["change_reasons"] = list(candidate.get("change_reasons", []))
        if "official_override_due" not in candidate["change_reasons"]:
            candidate["change_reasons"].append("official_override_due")
        due_urls.add(url)
    meta["official_override_due_urls"] = sorted(due_urls)
    if due_urls:
        meta["reason_counts"]["official_override_due"] = len(due_urls)
    meta["candidate_count"] = len(by_url)
    return list(by_url.values())


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def value_evidence(
    name: str,
    field: str,
    index: list[dict[str, Any]],
    state: dict[str, Any],
    selection_time: Any = None,
    today: date | None = None,
) -> dict[str, Any]:
    """過去runやキャッシュの値を今回の上流確認と混同しない。"""
    base = extract_ms_base_name(name) or name
    urls = {
        item.get("url")
        for item in index
        if isinstance(item, dict)
        and normalize_ms_base_name(item.get("name", "")) == base
        and item.get("url")
    }
    url = next(iter(urls)) if len(urls) == 1 else ""
    result: dict[str, Any] = {
        "evidence_status": "not_fetched",
        "url": url,
        "fetched_at": "",
        "attempted_at": "",
        "http_status": None,
        "raw": None,
    }
    run = _timestamp(state.get("run_started_at"))
    selected = _timestamp(selection_time)
    entries = state.get("items", {})
    entry = entries.get(url, {}) if isinstance(entries, dict) else {}
    if not isinstance(entry, dict):
        return result
    if (
        not run
        or not selected
        or (today is not None and run.astimezone(JST).date() != today)
        or _timestamp(entry.get("attempted_at")) != run
        or run < selected
    ):
        return result
    result.update(
        attempted_at=entry.get("attempted_at", ""),
        fetched_at=entry.get("fetched_at", entry.get("response_fetched_at", "")),
        http_status=entry.get("http_status"),
    )
    if entry.get("ok") is not True:
        result["evidence_status"] = entry.get("failure_stage", "fetch_failed")
        return result
    if entry.get("parse_status") != "parsed":
        result["evidence_status"] = (
            "parse_failed" if entry.get("parse_status") == "failed" else "not_parsed"
        )
        return result
    records = entry.get("override_values", {})
    values = records.get(name, {}) if isinstance(records, dict) else {}
    if not isinstance(values, dict):
        values = {}
    result["raw"] = values.get(field)
    fetched = _timestamp(entry.get("fetched_at"))
    if (
        entry.get("network_fetched") is not True
        or not fetched
        or fetched < run
        or entry.get("http_status") not in {200, 304}
    ):
        result["evidence_status"] = "cached_only"
    elif result["raw"] is None:
        result["evidence_status"] = "value_missing"
    else:
        result["evidence_status"] = "available"
    return result
