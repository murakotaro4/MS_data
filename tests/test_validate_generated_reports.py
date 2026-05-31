import json
from pathlib import Path

from scripts import validate_generated_reports


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_validate_generated_reports_accepts_current_report_shapes(tmp_path: Path):
    reports = tmp_path / "reports"
    schema_dir = Path("schema/reports")
    _write_json(
        reports / "atwiki_quality_20260531.json",
        {
            "schema_version": "1",
            "report_date": "20260531",
            "source_run_id": "1",
            "index": {
                "total_count": 1,
                "candidate_count": 1,
                "full_update": False,
                "fast_path": True,
                "fallback_reason": "none",
            },
            "detail_fetch": {
                "attempted_url_count": 1,
                "successful_url_count": 1,
                "failed_url_count": 0,
                "http_status_counts": {"200": 1},
                "conditional_cache_hit_count": 0,
                "cache_utilization": 0.0,
            },
            "details": {"json_records": 1, "jsonl_records": 1},
            "msdata_diff": {
                "old_count": 1,
                "new_count": 1,
                "added": 0,
                "removed": 0,
                "changed": 0,
            },
            "warnings": [],
        },
    )
    _write_json(
        reports / "auto_review_20260531.json",
        {
            "schema_version": "1",
            "generated_at": "2026-05-31T10:00:00Z",
            "report_date": "20260531",
            "source_run_id": "1",
            "pr_number": "97",
            "head_ref": "data/auto-update-20260531",
            "head_sha": "abc",
            "status": "stopped",
            "stop_reason": "no_response",
            "merge_ok": False,
            "merged": False,
            "findings": 0,
            "review_complete": False,
            "review": {
                "responded": False,
                "attempts_used": 3,
                "max_attempts": 3,
                "attempt_timeout_seconds": 420,
                "trigger_comment_ids": ["10"],
                "first_trigger_created_at": "2026-05-31T10:00:00Z",
            },
        },
    )
    (reports / "rollback_guard_20260531.md").write_text(
        "\n".join(
            [
                "# msData 巻き戻りガード",
                "- protected_rollback: 0",
                "- numeric_decrease: 0",
                "- mixed_level_change: 0",
            ]
        ),
        encoding="utf-8",
    )
    (reports / "official_overrides_audit_20260531.md").write_text(
        "\n".join(
            [
                "# official_overrides 監査",
                "- review_due: 0",
                "- remove_due: 0",
                "## 期限確認",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_generated_reports.validate_reports(reports, schema_dir) == []


def test_validate_generated_reports_rejects_missing_required_json_field(
    tmp_path: Path,
):
    reports = tmp_path / "reports"
    schema_dir = Path("schema/reports")
    _write_json(
        reports / "atwiki_quality_20260531.json",
        {
            "schema_version": "1",
            "report_date": "20260531",
        },
    )

    messages = validate_generated_reports.validate_reports(reports, schema_dir)

    assert any("source_run_id" in message for message in messages)
