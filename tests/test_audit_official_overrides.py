import json

from scripts import audit_official_overrides


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_audit_reports_protected_and_upstream_current(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    _write_json(
        overrides_dir / "20260528.json",
        {
            "schema_version": "1",
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
            "--fail-on-protected-rollback",
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "- protected_by_override: 1" in text
    assert "- upstream_current: 1" in text
    assert "ザクⅢ改_LV1" in text


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
