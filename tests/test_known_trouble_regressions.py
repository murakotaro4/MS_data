from pathlib import Path

from scripts import detect_msdata_rollbacks, update_msdata


def test_zaku_iii_kai_lv3_official_override_prevents_known_hp_rollback():
    overrides = update_msdata.load_official_overrides(Path("data/official_overrides"))
    records = {
        "ザクⅢ改_LV3": {
            "MS名": "ザクⅢ改_LV3",
            "HP": 23000,
        }
    }

    changed = update_msdata.apply_official_overrides(records, overrides)

    assert changed == 1
    assert records["ザクⅢ改_LV3"]["HP"] == 28500


def test_zaku_iii_kai_lv3_stale_hp_is_detected_as_protected_rollback():
    overrides = update_msdata.load_official_overrides(Path("data/official_overrides"))
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
