import json
from pathlib import Path

from ms_data.audit import detect_msdata_rollbacks
from ms_data.pipeline import update_msdata


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


def test_zaku_iii_kai_lv3_official_override_prevents_known_hp_rollback(tmp_path):
    overrides = update_msdata.load_official_overrides(
        _write_zaku_iii_kai_override(tmp_path)
    )
    records = {
        "ザクⅢ改_LV3": {
            "MS名": "ザクⅢ改_LV3",
            "HP": 23000,
        }
    }

    changed = update_msdata.apply_official_overrides(records, overrides)

    assert changed == 1
    assert records["ザクⅢ改_LV3"]["HP"] == 28500


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
