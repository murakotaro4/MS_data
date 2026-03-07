import json
from pathlib import Path

import scripts.validate_msdata as vm


def make_minimal_record(**overrides):
    record = {
        "MS\u540d": "test-ms_LV1",
        "\u5c5e\u6027": "\u6c4e\u7528",
        "\u30b3\u30b9\u30c8": 300,
        "HP": 12000,
        "\u30b9\u30d4\u30fc\u30c9": 125,
        "\u30b9\u30e9\u30b9\u30bf\u30fc": 65,
        "\u9ad8\u901f\u79fb\u52d5": 190,
        "\u5c04\u6483\u88dc\u6b63": 10,
        "\u683c\u95d8\u88dc\u6b63": 8,
        "\u8010\u30d3\u30fc\u30e0\u88dc\u6b63": 10,
        "\u8010\u5b9f\u5f3e\u88dc\u6b63": 12,
        "\u8010\u683c\u95d8\u88dc\u6b63": 8,
        "\u8fd1\u30b9\u30ed\u30c3\u30c8": 10,
        "\u4e2d\u30b9\u30ed\u30c3\u30c8": 8,
        "\u9060\u30b9\u30ed\u30c3\u30c8": 6,
    }
    record.update(overrides)
    return record


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_find_semantic_errors_detects_invalid_fullst_points_hyphen():
    errors = vm.find_semantic_errors(
        [
            {
                "MS\u540d": "test-ms_LV1",
                "fullst": [{"name": "AD-PA", "level": 1, "points": "-"}],
            }
        ]
    )
    assert any("fullst points must be an integer or null" in error for error in errors)


def test_find_semantic_errors_detects_invalid_fullst_points_text():
    errors = vm.find_semantic_errors(
        [
            {
                "MS\u540d": "test-ms_LV1",
                "fullst": [{"name": "AD-PA", "level": 1, "points": "abc"}],
            }
        ]
    )
    assert any("fullst points must be an integer or null" in error for error in errors)


def test_find_semantic_errors_detects_invalid_fullst_points_true():
    errors = vm.find_semantic_errors(
        [
            {
                "MS\u540d": "test-ms_LV1",
                "fullst": [{"name": "AD-PA", "level": 1, "points": True}],
            }
        ]
    )
    assert any("fullst points must be an integer or null" in error for error in errors)


def test_find_semantic_errors_detects_invalid_fullst_points_false():
    errors = vm.find_semantic_errors(
        [
            {
                "MS\u540d": "test-ms_LV1",
                "fullst": [{"name": "AD-PA", "level": 1, "points": False}],
            }
        ]
    )
    assert any("fullst points must be an integer or null" in error for error in errors)


def test_validate_msdata_main_fails_on_invalid_fullst_points(tmp_path):
    path = tmp_path / "msData.json"
    write_json(
        path,
        [
            make_minimal_record(
                fullst=[{"name": "AD-PA", "level": 1, "points": "-"}],
            )
        ],
    )
    assert vm.main([str(path)]) == 1
