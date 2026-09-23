from ms_data.audit import detect_msdata_rollbacks

from helpers import write_json


def test_detect_protected_rollback_fails(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    out = tmp_path / "rollback.md"
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
    write_json(old, [{"MS名": "ザクⅢ改_LV1", "HP": 27000}])
    write_json(new, [{"MS名": "ザクⅢ改_LV1", "HP": 23500}])

    rc = detect_msdata_rollbacks.main(
        [
            "--old",
            str(old),
            "--new",
            str(new),
            "--official-overrides-dir",
            str(overrides_dir),
            "--out",
            str(out),
            "--fail-on-protected-rollback",
        ]
    )

    assert rc == 1
    text = out.read_text(encoding="utf-8")
    assert "- protected_rollback: 1" in text
    assert "ザクⅢ改_LV1" in text


def test_numeric_decrease_is_reported_without_failure(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()
    write_json(overrides_dir / "empty.json", {"schema_version": "1", "overrides": []})
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    out = tmp_path / "rollback.md"
    write_json(old, [{"MS名": "テスト機_LV1", "HP": 20000}])
    write_json(new, [{"MS名": "テスト機_LV1", "HP": 19000}])

    rc = detect_msdata_rollbacks.main(
        [
            "--old",
            str(old),
            "--new",
            str(new),
            "--official-overrides-dir",
            str(overrides_dir),
            "--out",
            str(out),
            "--fail-on-protected-rollback",
        ]
    )

    assert rc == 0
    assert "- numeric_decrease: 1" in out.read_text(encoding="utf-8")


def test_mixed_level_change_is_reported(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()
    write_json(overrides_dir / "empty.json", {"schema_version": "1", "overrides": []})
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    out = tmp_path / "rollback.md"
    write_json(
        old,
        [
            {"MS名": "テスト機_LV1", "HP": 20000},
            {"MS名": "テスト機_LV2", "HP": 21000},
        ],
    )
    write_json(
        new,
        [
            {"MS名": "テスト機_LV1", "HP": 22000},
            {"MS名": "テスト機_LV2", "HP": 20500},
        ],
    )

    rc = detect_msdata_rollbacks.main(
        [
            "--old",
            str(old),
            "--new",
            str(new),
            "--official-overrides-dir",
            str(overrides_dir),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "- mixed_level_change: 1" in text
    assert "テスト機 / HP" in text
