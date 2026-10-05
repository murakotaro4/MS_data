import re
from datetime import date

import pytest

from ms_data.audit import audit_official_overrides

from helpers import write_json


def test_audit_reports_protected_and_upstream_current(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    write_json(
        overrides_dir / "20260528.json",
        {
            "schema_version": "1",
            "review_after": "2026-05-01",
            "remove_after": "2026-06-30",
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV1",
                    "values": {"HP": 27000, "スピード": 145},
                    "stale_values": {"HP": 23500, "スピード": 140},
                }
            ],
        },
    )
    before = tmp_path / "before.json"
    raw = tmp_path / "raw.json"
    current = tmp_path / "current.json"
    out = tmp_path / "audit.md"
    write_json(before, [{"MS名": "ザクⅢ改_LV1", "HP": 27000, "スピード": 145}])
    write_json(raw, [{"MS名": "ザクⅢ改_LV1", "HP": 23500, "スピード": 145}])
    write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000, "スピード": 145}])

    index = tmp_path / "index.json"
    state = tmp_path / "state.json"
    meta = tmp_path / "meta.json"
    url = "https://example.test/1"
    write_json(index, [{"name": "ザクⅢ改", "url": url}])
    write_json(meta, {"generated_at": "2026-05-31T00:00:00Z"})
    write_json(
        state,
        {
            "run_started_at": "2026-05-31T00:01:00Z",
            "items": {
                url: {
                    "attempted_at": "2026-05-31T00:01:00Z",
                    "fetched_at": "2026-05-31T00:01:01Z",
                    "ok": True,
                    "http_status": 200,
                    "network_fetched": True,
                    "parse_status": "parsed",
                    "override_values": {"ザクⅢ改_LV1": {"HP": 23500, "スピード": 145}},
                }
            },
        },
    )
    rc = audit_official_overrides.main(
        [
            "--index",
            str(index),
            "--detail-fetch-state",
            str(state),
            "--changed-meta",
            str(meta),
            "--overrides-dir",
            str(overrides_dir),
            "--before",
            str(before),
            "--raw",
            str(raw),
            "--current",
            str(current),
            "--out",
            str(out),
            "--today",
            "2026-05-31",
            "--fail-on-protected-rollback",
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "- protected_by_override: 1" in text
    assert "- upstream_current: 1" in text
    assert "- review_due: 2" in text
    assert "ザクⅢ改_LV1" in text


def test_audit_treats_missing_raw_override_record_as_not_upstream_current(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    write_json(
        overrides_dir / "20260528.json",
        {
            "schema_version": "1",
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV1",
                    "values": {"HP": 27000},
                    "stale_values": {"HP": 23500},
                }
            ],
        },
    )
    before = tmp_path / "before.json"
    raw = tmp_path / "raw.json"
    current = tmp_path / "current.json"
    out = tmp_path / "audit.md"
    write_json(before, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])
    write_json(raw, [{"MS名": "別機体_LV1", "HP": 12500}])
    write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])

    rc = audit_official_overrides.main(
        [
            "--overrides-dir",
            str(overrides_dir),
            "--before",
            str(before),
            "--raw",
            str(raw),
            "--current",
            str(current),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "- already_protected: 1" in text
    assert "- upstream_current:" not in text


def test_audit_fails_when_current_value_is_stale(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    write_json(
        overrides_dir / "20260528.json",
        {
            "schema_version": "1",
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV1",
                    "values": {"HP": 27000},
                    "stale_values": {"HP": 23500},
                }
            ],
        },
    )
    current = tmp_path / "current.json"
    out = tmp_path / "audit.md"
    write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 23500}])

    rc = audit_official_overrides.main(
        [
            "--overrides-dir",
            str(overrides_dir),
            "--current",
            str(current),
            "--out",
            str(out),
            "--fail-on-protected-rollback",
        ]
    )

    assert rc == 1
    assert "protected_rollback" in out.read_text(encoding="utf-8")


def test_audit_can_fail_when_override_remove_date_is_due(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    write_json(
        overrides_dir / "20260528.json",
        {
            "schema_version": "1",
            "remove_after": "2026-05-31",
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV1",
                    "values": {"HP": 27000},
                    "stale_values": {"HP": 23500},
                }
            ],
        },
    )
    current = tmp_path / "current.json"
    out = tmp_path / "audit.md"
    write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])

    rc = audit_official_overrides.main(
        [
            "--overrides-dir",
            str(overrides_dir),
            "--current",
            str(current),
            "--out",
            str(out),
            "--today",
            "2026-05-31",
            "--fail-on-remove-due",
        ]
    )

    assert rc == 1
    text = out.read_text(encoding="utf-8")
    assert "- remove_due: 1" in text


def test_audit_writes_github_output_and_step_summary(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    write_json(
        overrides_dir / "20260528.json",
        {
            "schema_version": "1",
            "review_after": "2026-05-01",
            "remove_after": "2026-06-30",
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV1",
                    "values": {"HP": 27000},
                    "stale_values": {"HP": 23500},
                }
            ],
        },
    )
    current = tmp_path / "current.json"
    out = tmp_path / "audit.md"
    github_output = tmp_path / "github_output.txt"
    step_summary = tmp_path / "summary.md"
    write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])

    rc = audit_official_overrides.main(
        [
            "--overrides-dir",
            str(overrides_dir),
            "--current",
            str(current),
            "--out",
            str(out),
            "--today",
            "2026-05-31",
            "--github-output",
            str(github_output),
            "--step-summary",
            str(step_summary),
        ]
    )

    assert rc == 0
    output_text = github_output.read_text(encoding="utf-8")
    assert "review_due=1" in output_text
    assert "remove_due=0" in output_text
    assert "due_count=1" in output_text
    assert re.search(r"^due_fingerprint=[0-9a-f]{64}$", output_text, re.MULTILINE)
    assert "### official_overrides 期限監査" in step_summary.read_text(encoding="utf-8")


def _due_rows():
    rows, _, _ = audit_official_overrides.build_audit(
        overrides={
            "ザクⅢ改_LV1": {
                "HP": {"value": 27000, "stale_value": 23500},
                "スピード": {"value": 145, "stale_value": 140},
            }
        },
        current_records={},
        raw_records={},
        before_records={},
        lifecycle_metadata={
            ("ザクⅢ改_LV1", field): {
                "file": "20260528.json",
                "review_after": "2026-05-01",
                "remove_after": "2026-06-30",
            }
            for field in ("HP", "スピード")
        },
        today=date(2026, 5, 31),
    )
    return rows


def test_due_fingerprint_ignores_row_order_and_daily_fetch_metadata():
    rows = _due_rows()
    next_day = [
        {
            **row,
            "attempted_at": "2026-06-01T00:00:00Z",
            "fetched_at": "2026-06-01T00:00:01Z",
            "before": 0,
            "raw": 1,
            "current": 2,
            "status": "upstream_current",
            "evidence_status": "match",
        }
        for row in reversed(rows)
    ]
    scheduled = {**rows[0], "MS名": "別機体_LV1", "lifecycle": "scheduled"}

    fingerprint = audit_official_overrides.build_due_fingerprint(rows)
    assert audit_official_overrides.build_due_fingerprint(next_day) == fingerprint
    assert (
        audit_official_overrides.build_due_fingerprint([*rows, scheduled])
        == fingerprint
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MS名", "別機体_LV1"),
        ("field", "スラスター"),
        ("lifecycle", "remove_due"),
        ("review_after", "2026-05-02"),
        ("remove_after", "2026-07-01"),
        ("override", 27500),
        ("stale", 24000),
        ("override_file", "20260601.json"),
    ],
)
def test_due_fingerprint_changes_when_same_count_targets_or_settings_change(key, value):
    rows = _due_rows()
    changed = [{**rows[0], key: value}, rows[1]]

    assert len(rows) == len(changed)
    assert audit_official_overrides.build_due_fingerprint(
        rows
    ) != audit_official_overrides.build_due_fingerprint(changed)
