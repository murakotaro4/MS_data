import json
from pathlib import Path

from ms_data.audit import detect_msdata_rollbacks
from ms_data.pipeline import update_msdata

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


def _write_zaku_iii_kai_override(tmp_path: Path) -> Path:
    """2026-05-28 調整時に実在した ザクⅢ改_LV3 HP の override を再現する。

    実データ（data/official_overrides/）は期限到達で撤去されるため、
    回帰シナリオは fixture として固定する。
    """
    payload = {
        "schema_version": "1",
        "active": True,
        "overrides": [
            {
                "MS名": "ザクⅢ改_LV3",
                "values": {"HP": 28500},
                "stale_values": {"HP": 23000},
            }
        ],
    }
    (tmp_path / "20260528_balance.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def test_zaku_iii_kai_lv3_stale_hp_is_detected_as_protected_rollback(tmp_path):
    overrides = update_msdata.load_official_overrides(
        _write_zaku_iii_kai_override(tmp_path)
    )
    old = {"ザクⅢ改_LV3": {"MS名": "ザクⅢ改_LV3", "HP": 28500}}
    new = {"ザクⅢ改_LV3": {"MS名": "ザクⅢ改_LV3", "HP": 23000}}

    protected = detect_msdata_rollbacks.detect_protected_rollbacks(old, new, overrides)

    assert protected == [
        {
            "MS名": "ザクⅢ改_LV3",
            "field": "HP",
            "old": 28500,
            "new": 23000,
            "override": 28500,
            "stale": 23000,
            "type": "protected_rollback",
        }
    ]
