import json

from ms_data.audit import audit_official_overrides


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_audit_reports_protected_and_upstream_current(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    _write_json(
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
    _write_json(before, [{"MS名": "ザクⅢ改_LV1", "HP": 27000, "スピード": 145}])
    _write_json(raw, [{"MS名": "ザクⅢ改_LV1", "HP": 23500, "スピード": 145}])
    _write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000, "スピード": 145}])

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
    _write_json(
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
    _write_json(before, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])
    _write_json(raw, [{"MS名": "別機体_LV1", "HP": 12500}])
    _write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])

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
    _write_json(
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
    _write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 23500}])

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
    _write_json(
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
    _write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])

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
    _write_json(
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
    _write_json(current, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])

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
    assert "### official_overrides 期限監査" in step_summary.read_text(encoding="utf-8")
