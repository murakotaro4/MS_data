"""atwiki 取得品質の監視レポートを JSON で出力する。"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import report_msdata_diff


def _load_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _count_jsonl(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _records_index(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    data = _load_json(path, [])
    if not isinstance(data, list):
        return {}
    indexed, _, _ = report_msdata_diff.index_by_name(data)
    return indexed


def _url(item: dict[str, Any]) -> str:
    value = item.get("url")
    return value if isinstance(value, str) else ""


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_current_attempt(entry: dict[str, Any], run_started_at: datetime | None) -> bool:
    if run_started_at is None:
        return True
    attempted_at = _parse_datetime(entry.get("attempted_at"))
    if attempted_at is None:
        return False
    return attempted_at >= run_started_at


def _is_failed_fetch(entry: dict[str, Any]) -> bool:
    return entry.get("ok") is False or bool(entry.get("error"))


def _warning(
    warning_id: str,
    message: str,
    *,
    observed: int | float,
    threshold: int | float,
) -> dict[str, Any]:
    return {
        "id": warning_id,
        "severity": "warning",
        "message": message,
        "observed": observed,
        "threshold": threshold,
    }


def evaluate_quality_warnings(
    report: dict[str, Any],
    *,
    max_failure_rate: float,
    min_detail_record_ratio: float,
    full_diff_warning_count: int,
) -> list[dict[str, Any]]:
    detail_fetch = report.get("detail_fetch", {})
    details = report.get("details", {})
    msdata_diff = report.get("msdata_diff", {})
    index = report.get("index", {})
    warnings: list[dict[str, Any]] = []

    attempted = int(detail_fetch.get("attempted_url_count", 0) or 0)
    failed = int(detail_fetch.get("failed_url_count", 0) or 0)
    if attempted > 0:
        failure_rate = failed / attempted
        if failure_rate > max_failure_rate:
            warnings.append(
                _warning(
                    "high_failure_rate",
                    "詳細取得の失敗率がしきい値を超えています。",
                    observed=round(failure_rate, 6),
                    threshold=max_failure_rate,
                )
            )

        jsonl_records = int(details.get("jsonl_records", 0) or 0)
        detail_record_ratio = jsonl_records / attempted
        if detail_record_ratio < min_detail_record_ratio:
            warnings.append(
                _warning(
                    "low_detail_record_ratio",
                    "候補URL数に対して詳細レコード数が少なすぎます。",
                    observed=round(detail_record_ratio, 6),
                    threshold=min_detail_record_ratio,
                )
            )

    changed_total = sum(
        int(msdata_diff.get(key, 0) or 0) for key in ("added", "removed", "changed")
    )
    if bool(index.get("full_update")) and changed_total >= full_diff_warning_count:
        warnings.append(
            _warning(
                "large_full_update_diff",
                "full更新の msData 差分件数がしきい値以上です。",
                observed=changed_total,
                threshold=full_diff_warning_count,
            )
        )

    return warnings


def _write_github_output(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={value}\n")


def _append_step_summary(report: dict[str, Any], path: Path | None) -> None:
    summary_path = path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    warnings = report.get("warnings", [])
    detail_fetch = report["detail_fetch"]
    msdata_diff = report["msdata_diff"]
    lines = [
        "### atwiki 取得品質",
        f"- warnings: {len(warnings)}",
        f"- attempted_url_count: {detail_fetch['attempted_url_count']}",
        f"- successful_url_count: {detail_fetch['successful_url_count']}",
        f"- failed_url_count: {detail_fetch['failed_url_count']}",
        f"- cache_utilization: {detail_fetch['cache_utilization']}",
        (
            "- msdata_diff: "
            f"+{msdata_diff['added']} -{msdata_diff['removed']} "
            f"~{msdata_diff['changed']}"
        ),
    ]
    for warning in warnings:
        lines.append(f"- warning[{warning['id']}]: {warning['message']}")
    with Path(summary_path).open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(f"{line}\n")


def _warning_summary(warnings: list[dict[str, Any]]) -> str:
    if not warnings:
        return "なし"
    return "; ".join(str(item["id"]) for item in warnings)


def build_report(
    *,
    report_date: str,
    source_run_id: str,
    index_path: Path,
    changed_index_path: Path,
    changed_meta_path: Path,
    detail_fetch_state_path: Path,
    details_json_path: Path,
    details_jsonl_path: Path,
    before_msdata_path: Path | None,
    current_msdata_path: Path | None,
    full_update: bool = False,
    max_failure_rate: float = 0.10,
    min_detail_record_ratio: float = 0.80,
    full_diff_warning_count: int = 200,
) -> dict[str, Any]:
    index_data = _load_json(index_path, [])
    changed_index = _load_json(changed_index_path, [])
    changed_meta = _load_json(changed_meta_path, {})
    detail_state = _load_json(detail_fetch_state_path, {})
    if not isinstance(index_data, list):
        index_data = []
    if not isinstance(changed_index, list):
        changed_index = []
    if not isinstance(changed_meta, dict):
        changed_meta = {}
    if not isinstance(detail_state, dict):
        detail_state = {}
    detail_items = detail_state.get("items", detail_state)
    if not isinstance(detail_items, dict):
        detail_items = {}
    run_started_at = _parse_datetime(detail_state.get("run_started_at"))

    candidate_urls = {_url(item) for item in changed_index if isinstance(item, dict)}
    candidate_urls.discard("")
    candidate_count = int(changed_meta.get("candidate_count", len(candidate_urls)))
    attempted_url_count = len(candidate_urls) if candidate_urls else candidate_count

    if candidate_urls:
        candidate_state_entries = [
            entry
            for url, entry in detail_items.items()
            if isinstance(entry, dict)
            and url in candidate_urls
            and _is_current_attempt(entry, run_started_at)
        ]
    elif candidate_count > 0:
        candidate_state_entries = [
            entry
            for entry in detail_items.values()
            if isinstance(entry, dict) and _is_current_attempt(entry, run_started_at)
        ]
    else:
        candidate_state_entries = []
    http_status_counts: Counter[str] = Counter()
    for entry in candidate_state_entries:
        status = entry.get("http_status")
        key = str(status) if status is not None else "unknown"
        http_status_counts[key] += 1

    failed_attempt_count = sum(
        1 for entry in candidate_state_entries if _is_failed_fetch(entry)
    )
    successful_url_count = len(candidate_state_entries) - failed_attempt_count
    failed_url_count = failed_attempt_count + max(
        0, attempted_url_count - len(candidate_state_entries)
    )
    conditional_cache_hit_count = http_status_counts.get("304", 0)
    cache_utilization = (
        conditional_cache_hit_count / successful_url_count
        if successful_url_count
        else 0.0
    )

    before_index = _records_index(before_msdata_path)
    current_index = _records_index(current_msdata_path)
    if before_index and current_index:
        old_count, new_count, added, removed, changed = report_msdata_diff.diff_summary(
            before_index, current_index
        )
    else:
        old_count = new_count = added = removed = changed = 0

    details_json = _load_json(details_json_path, [])
    details_json_count = len(details_json) if isinstance(details_json, list) else 0

    report: dict[str, Any] = {
        "schema_version": "1",
        "report_date": report_date,
        "source_run_id": source_run_id,
        "index": {
            "total_count": len(index_data),
            "candidate_count": candidate_count,
            "full_update": bool(full_update),
            "fast_path": bool(changed_meta.get("fast_path", False)),
            "fallback_reason": changed_meta.get("fallback_reason") or "none",
            "age_coverage": changed_meta.get("age_coverage", 0.0),
            "reason_counts": changed_meta.get("reason_counts", {}),
        },
        "detail_fetch": {
            "attempted_url_count": attempted_url_count,
            "successful_url_count": successful_url_count,
            "failed_url_count": failed_url_count,
            "http_status_counts": dict(sorted(http_status_counts.items())),
            "conditional_cache_hit_count": conditional_cache_hit_count,
            "cache_utilization": round(cache_utilization, 6),
            "state_entry_count": len(detail_items),
        },
        "details": {
            "json_records": details_json_count,
            "jsonl_records": _count_jsonl(details_jsonl_path),
        },
        "msdata_diff": {
            "old_count": old_count,
            "new_count": new_count,
            "added": added,
            "removed": removed,
            "changed": changed,
        },
    }
    report["warnings"] = evaluate_quality_warnings(
        report,
        max_failure_rate=max_failure_rate,
        min_detail_record_ratio=min_detail_record_ratio,
        full_diff_warning_count=full_diff_warning_count,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--index", type=Path, default=Path("cache/index.json"))
    parser.add_argument(
        "--changed-index", type=Path, default=Path("cache/index_changed.json")
    )
    parser.add_argument(
        "--changed-meta", type=Path, default=Path("cache/index_changed_meta.json")
    )
    parser.add_argument(
        "--detail-fetch-state",
        type=Path,
        default=Path("cache/detail_fetch_state.json"),
    )
    parser.add_argument("--details-json", type=Path, default=Path("cache/details.json"))
    parser.add_argument(
        "--details-jsonl", type=Path, default=Path("cache/details.jsonl")
    )
    parser.add_argument("--before-msdata", type=Path, default=None)
    parser.add_argument("--current-msdata", type=Path, default=Path("msData.json"))
    parser.add_argument("--full-update", action="store_true")
    parser.add_argument("--max-failure-rate", type=float, default=0.10)
    parser.add_argument("--min-detail-record-ratio", type=float, default=0.80)
    parser.add_argument("--full-diff-warning-count", type=int, default=200)
    parser.add_argument("--github-output", type=Path, default=None)
    parser.add_argument("--step-summary", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_report(
        report_date=args.report_date,
        source_run_id=args.source_run_id,
        index_path=args.index,
        changed_index_path=args.changed_index,
        changed_meta_path=args.changed_meta,
        detail_fetch_state_path=args.detail_fetch_state,
        details_json_path=args.details_json,
        details_jsonl_path=args.details_jsonl,
        before_msdata_path=args.before_msdata,
        current_msdata_path=args.current_msdata,
        full_update=args.full_update,
        max_failure_rate=args.max_failure_rate,
        min_detail_record_ratio=args.min_detail_record_ratio,
        full_diff_warning_count=args.full_diff_warning_count,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    warnings = report["warnings"]
    if args.github_output is not None:
        _write_github_output(
            args.github_output,
            {
                "warning_count": len(warnings),
                "warning_summary": _warning_summary(warnings),
            },
        )
    _append_step_summary(report, args.step_summary)
    print(f"atwiki quality report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
