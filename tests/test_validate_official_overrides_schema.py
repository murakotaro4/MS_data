import json
from pathlib import Path

from ms_data.validation import validate_official_overrides_schema


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _schema_path():
    return Path("schema/official_overrides.schema.json")


def test_validate_official_overrides_schema_accepts_valid_file(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    _write_json(
        overrides_dir / "valid.json",
        {
            "schema_version": "1",
            "active": True,
            "review_after": "2026-06-07",
            "remove_after": "2026-06-30",
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV3",
                    "values": {"HP": 28500},
                    "stale_values": {"HP": 23000},
                }
            ],
        },
    )

    messages = validate_official_overrides_schema.validate(
        overrides_dir=overrides_dir,
        schema_path=_schema_path(),
    )

    assert messages == []


def test_validate_official_overrides_schema_accepts_empty_directory(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()

    messages = validate_official_overrides_schema.validate(
        overrides_dir=overrides_dir,
        schema_path=_schema_path(),
    )

    assert messages == []


def test_validate_official_overrides_schema_rejects_missing_stale_value(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    _write_json(
        overrides_dir / "invalid.json",
        {
            "schema_version": "1",
            "active": True,
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV3",
                    "values": {"HP": 28500},
                }
            ],
        },
    )

    messages = validate_official_overrides_schema.validate(
        overrides_dir=overrides_dir,
        schema_path=_schema_path(),
    )

    assert any("stale_values" in message for message in messages)


def test_validate_official_overrides_schema_rejects_key_mismatch(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    _write_json(
        overrides_dir / "invalid.json",
        {
            "schema_version": "1",
            "active": True,
            "overrides": [
                {
                    "MS名": "ザクⅢ改_LV3",
                    "values": {"HP": 28500, "スラスター": 80},
                    "stale_values": {"HP": 23000},
                }
            ],
        },
    )

    messages = validate_official_overrides_schema.validate(
        overrides_dir=overrides_dir,
        schema_path=_schema_path(),
    )

    assert any("stale_values missing keys" in message for message in messages)
