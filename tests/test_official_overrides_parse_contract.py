"""official_overrides の 3 読み込み経路に対する互換契約。"""

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
    "records_fallback": {
        "schema_version": "1",
        "active": True,
        "review_after": "2026-10-01",
        "records": [
            {
                "MS名": "互換機III_LV1",
                "values": {"HP": 27000},
                "stale_values": {"HP": 23500},
            }
        ],
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


@pytest.mark.parametrize("case_name", CASES)
def test_pipeline_load_contract_matrix(case_name: str, tmp_path: Path, capsys) -> None:
    overrides_dir = tmp_path / "official_overrides"
    case_path = _write_case(overrides_dir, CASES[case_name])

    if case_name == "invalid_json":
        with pytest.raises(JSONDecodeError) as exc_info:
            update_msdata.load_official_overrides(overrides_dir)
        assert str(exc_info.value) == (
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
        )
    elif case_name == "top_level_not_object":
        with pytest.raises(ValueError) as exc_info:
            update_msdata.load_official_overrides(overrides_dir)
        assert (
            str(exc_info.value)
            == f"official override file must be an object: {case_path}"
        )
    elif case_name == "overrides_not_list":
        with pytest.raises(ValueError) as exc_info:
            update_msdata.load_official_overrides(overrides_dir)
        assert (
            str(exc_info.value)
            == f"official override entries must be a list: {case_path}"
        )
    elif case_name == "entry_not_dict":
        with pytest.raises(ValueError) as exc_info:
            update_msdata.load_official_overrides(overrides_dir)
        assert str(exc_info.value) == (
            f"official override entry must be an object: {case_path}#0"
        )
    elif case_name == "missing_required_key":
        with pytest.raises(ValueError) as exc_info:
            update_msdata.load_official_overrides(overrides_dir)
        assert (
            str(exc_info.value)
            == f"official override entry missing MS名: {case_path}#0"
        )
    elif case_name == "active_false":
        assert update_msdata.load_official_overrides(overrides_dir) == BASE_OVERRIDES
    else:
        assert update_msdata.load_official_overrides(overrides_dir) == {
            "互換機Ⅲ_LV1": {"HP": {"value": 27000, "stale_value": 23500}},
            **BASE_OVERRIDES,
        }

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("case_name", CASES)
def test_audit_load_contract_matrix(case_name: str, tmp_path: Path, capsys) -> None:
    overrides_dir = tmp_path / "official_overrides"
    _write_case(overrides_dir, CASES[case_name])

    if case_name == "invalid_json":
        with pytest.raises(JSONDecodeError) as exc_info:
            load_lifecycle_metadata(overrides_dir)
        assert str(exc_info.value) == (
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
        )
    elif case_name == "records_fallback":
        assert load_lifecycle_metadata(overrides_dir) == {
            ("互換機Ⅲ_LV1", "HP"): {
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
        with pytest.raises(JSONDecodeError) as exc_info:
            validate_official_overrides_schema.main(argv)
        assert str(exc_info.value) == (
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
        )
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        return
    elif case_name == "top_level_not_object":
        with pytest.raises(
            AttributeError, match="'list' object has no attribute 'get'"
        ):
            validate_official_overrides_schema.main(argv)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        return
    else:
        rc = validate_official_overrides_schema.main(argv)
        schema_error = {
            "overrides_not_list": f"{case_path}: overrides: {{}} is not of type 'array'",
            "entry_not_dict": (
                f"{case_path}: overrides/0: 'bad' is not of type 'object'"
            ),
            "missing_required_key": (
                f"{case_path}: overrides/0: 'MS名' is a required property"
            ),
            "records_fallback": (
                f"{case_path}: <root>: 'overrides' is a required property"
            ),
        }.get(case_name)
        semantic_error = {
            "overrides_not_list": (
                "official override entries must be a list: " f"{case_path}"
            ),
            "entry_not_dict": (
                "official override entry must be an object: " f"{case_path}#0"
            ),
            "missing_required_key": (
                "official override entry missing MS名: " f"{case_path}#0"
            ),
        }.get(case_name)
        expected_messages = [schema_error] if schema_error else []
        if semantic_error:
            expected_messages.append(
                f"{overrides_dir}: semantic validation failed: {semantic_error}"
            )
        expected_stderr = "".join(
            f"ERROR: {message}\n" for message in expected_messages
        )
        assert rc == (1 if expected_messages else 0)

    captured = capsys.readouterr()
    assert captured.out == (
        "OK: official_overrides schema\n" if case_name == "active_false" else ""
    )
    assert captured.err == expected_stderr
