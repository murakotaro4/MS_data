import ms_data.validation.validate_msdata as vm

from helpers import make_minimal_ms_record, write_json


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
            make_minimal_ms_record(
                fullst=[{"name": "AD-PA", "level": 1, "points": "-"}],
            )
        ],
    )
    assert vm.main([str(path)]) == 1
