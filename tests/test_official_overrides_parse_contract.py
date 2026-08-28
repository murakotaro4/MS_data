"""official_overrides の 3 読み込み経路に対する厳格契約。"""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import pytest

from ms_data.audit.audit_official_overrides import load_lifecycle_metadata
from ms_data.pipeline import update_msdata
from ms_data.validation import validate_official_overrides_schema

BASE_ENTRY = {
    "MS名": "基準機_LV1",
    "values": {"HP": 10000},
    "stale_values": {"HP": 9000},
}
BASE_OVERRIDES = {"基準機_LV1": {"HP": {"value": 10000, "stale_value": 9000}}}
BASE_METADATA = {
    ("基準機_LV1", "HP"): {
        "file": "z-valid.json",
        "review_after": "2026-09-01",
        "remove_after": "",
    }
}


CASES: dict[str, Any] = {
    "invalid_json": "{broken",
    "top_level_not_object": [],
    "overrides_not_list": {
        "schema_version": "1",
        "active": True,
        "overrides": {},
    },
    "entry_not_dict": {
        "schema_version": "1",
        "active": True,
        "overrides": ["bad"],
    },
    "missing_required_key": {
        "schema_version": "1",
        "active": True,
        "overrides": [{"values": {"HP": 27000}, "stale_values": {"HP": 23500}}],
    },
    "records_only": {
        "schema_version": "1",
        "active": True,
        "records": [BASE_ENTRY],
    },
    "stale_values_missing": {
        "schema_version": "1",
        "active": True,
        "overrides": [{"MS名": "不正機_LV1", "values": {"HP": 27000}}],
    },
    "stale_values_not_object": {
        "schema_version": "1",
        "active": True,
        "overrides": [
            {"MS名": "不正機_LV1", "values": {"HP": 27000}, "stale_values": []}
        ],
    },
    "stale_values_empty": {
        "schema_version": "1",
        "active": True,
        "overrides": [
            {"MS名": "不正機_LV1", "values": {"HP": 27000}, "stale_values": {}}
        ],
    },
    "stale_values_subset": {
        "schema_version": "1",
        "active": True,
        "overrides": [
            {
                "MS名": "不正機_LV1",
                "values": {"HP": 27000, "スピード": 145},
                "stale_values": {"HP": 23500},
            }
        ],
    },
    "stale_values_extra": {
        "schema_version": "1",
        "active": True,
        "overrides": [
            {
                "MS名": "不正機_LV1",
                "values": {"HP": 27000},
                "stale_values": {"HP": 23500, "スピード": 140},
            }
        ],
    },
    "alias_normalized_match": {
        "schema_version": "1",
        "active": True,
        "review_after": "2026-10-01",
        "overrides": [
            {
                "MS名": "互換機III_LV1",
                "values": {"射撃補則": 35},
                "stale_values": {"射撃補正": 30},
            }
        ],
    },
    "active_false": {
        "schema_version": "1",
        "active": False,
        "overrides": [
            {
                "MS名": "無効機_LV1",
                "values": {"HP": 27000},
                "stale_values": {"HP": 23500},
            }
        ],
    },
    "active_false_invalid": {
        "schema_version": "1",
        "active": False,
        "overrides": [{"MS名": "無効機_LV1", "values": {"HP": 27000}}],
    },
}


def _write_case(directory: Path, payload: Any) -> Path:
    directory.mkdir()
    case_path = directory / "a-case.json"
    text = (
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    )
    case_path.write_text(text, encoding="utf-8")
    (directory / "z-valid.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "active": True,
                "review_after": "2026-09-01",
                "overrides": [BASE_ENTRY],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return case_path


def _loader_error(case_name: str, case_path: Path) -> str | None:
    location = f"{case_path}#0"
    return {
        "top_level_not_object": f"official override file must be an object: {case_path}",
        "overrides_not_list": f"official override entries must be a list: {case_path}",
        "entry_not_dict": f"official override entry must be an object: {location}",
        "missing_required_key": f"official override entry missing MS名: {location}",
        "records_only": f"official override overrides missing: {case_path}",
        "stale_values_missing": (
            "official override entry stale_values must be a non-empty object: "
            f"{location}"
        ),
        "stale_values_not_object": (
            "official override entry stale_values must be a non-empty object: "
            f"{location}"
        ),
        "stale_values_empty": (
            "official override entry stale_values must be a non-empty object: "
            f"{location}"
        ),
        "active_false_invalid": (
            "official override entry stale_values must be a non-empty object: "
            f"{location}"
        ),
        "stale_values_subset": (
            "official override stale_values keys must match values keys: "
            f"{location} missing=['スピード'] extra=[]"
        ),
        "stale_values_extra": (
            "official override stale_values keys must match values keys: "
            f"{location} missing=[] extra=['スピード']"
        ),
    }.get(case_name)


@pytest.mark.parametrize("case_name", CASES)
def test_pipeline_load_contract_matrix(case_name: str, tmp_path: Path, capsys) -> None:
    overrides_dir = tmp_path / "official_overrides"
    case_path = _write_case(overrides_dir, CASES[case_name])

    if case_name == "invalid_json":
        with pytest.raises(JSONDecodeError):
            update_msdata.load_official_overrides(overrides_dir)
    elif expected_error := _loader_error(case_name, case_path):
        with pytest.raises(ValueError) as exc_info:
            update_msdata.load_official_overrides(overrides_dir)
        assert str(exc_info.value) == expected_error
    elif case_name == "alias_normalized_match":
        assert update_msdata.load_official_overrides(overrides_dir) == {
            "互換機Ⅲ_LV1": {"射撃補正": {"value": 35, "stale_value": 30}},
            **BASE_OVERRIDES,
        }
    else:
        assert update_msdata.load_official_overrides(overrides_dir) == BASE_OVERRIDES

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("case_name", CASES)
def test_audit_load_contract_matrix(case_name: str, tmp_path: Path, capsys) -> None:
    overrides_dir = tmp_path / "official_overrides"
    case_path = _write_case(overrides_dir, CASES[case_name])

    if case_name == "invalid_json":
        with pytest.raises(JSONDecodeError):
            load_lifecycle_metadata(overrides_dir)
    elif expected_error := _loader_error(case_name, case_path):
        with pytest.raises(ValueError) as exc_info:
            load_lifecycle_metadata(overrides_dir)
        assert str(exc_info.value) == expected_error
    elif case_name == "alias_normalized_match":
        assert load_lifecycle_metadata(overrides_dir) == {
            ("互換機Ⅲ_LV1", "射撃補正"): {
                "file": "a-case.json",
                "review_after": "2026-10-01",
                "remove_after": "",
            },
            **BASE_METADATA,
        }
    else:
        assert load_lifecycle_metadata(overrides_dir) == BASE_METADATA

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("case_name", CASES)
def test_validation_cli_contract_matrix(case_name: str, tmp_path: Path, capsys) -> None:
    overrides_dir = tmp_path / "official_overrides"
    case_path = _write_case(overrides_dir, CASES[case_name])
    argv = [
        "--overrides-dir",
        str(overrides_dir),
        "--schema",
        "schema/official_overrides.schema.json",
    ]

    if case_name == "invalid_json":
        with pytest.raises(JSONDecodeError):
            validate_official_overrides_schema.main(argv)
        rc = None
    elif case_name in {
        "top_level_not_object",
        "overrides_not_list",
        "records_only",
    }:
        with pytest.raises(ValueError) as exc_info:
            validate_official_overrides_schema.main(argv)
        assert str(exc_info.value) == _loader_error(case_name, case_path)
        rc = None
    else:
        rc = validate_official_overrides_schema.main(argv)

    captured = capsys.readouterr()
    if rc is None:
        assert captured.out == ""
        assert captured.err == ""
        return

    valid_cases = {"active_false", "alias_normalized_match"}
    assert rc == (0 if case_name in valid_cases else 1)
    assert captured.out == (
        "OK: official_overrides schema\n" if case_name in valid_cases else ""
    )

    if expected_error := _loader_error(case_name, case_path):
        assert f"semantic validation failed: {expected_error}" in captured.err
    else:
        assert captured.err == ""

    if case_name == "active_false_invalid":
        assert "'stale_values' is a required property" in captured.err

    if case_name == "stale_values_subset":
        assert "stale_values missing keys: ['スピード']" in captured.err
    if case_name == "stale_values_extra":
        assert "stale_values extra keys: ['スピード']" in captured.err
