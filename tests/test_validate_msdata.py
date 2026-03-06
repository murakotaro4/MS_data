import json
from pathlib import Path

import scripts.validate_msdata as vm


def make_record(ms_name: str = "テスト機_LV1", **overrides):
    record = {
        "MS名": ms_name,
        "wiki_url": "https://example.com/ms/test",
        "属性": "汎用",
        "コスト": 300,
        "HP": 12000,
        "耐実弾補正": 10,
        "耐ビーム補正": 12,
        "耐格闘補正": 8,
        "射撃補正": 20,
        "格闘補正": 15,
        "スピード": 125,
        "高速移動": 190,
        "スラスター": 65,
        "旋回_地上_通常時": 75,
        "近スロット": 10,
        "中スロット": 8,
        "遠スロット": 6,
        "出撃_地上可": True,
        "出撃_宇宙可": True,
    }
    record.update(overrides)
    return record


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_validate_msdata_main_accepts_valid_minimal_data(tmp_path):
    path = tmp_path / "msData.json"
    write_json(path, [make_record()])
    assert vm.main([str(path)]) == 0


def test_find_unknown_keys_detects_unmapped_key():
    unknown = vm.find_unknown_keys([make_record(謎キー=1)], vm.load_allowed_keys(vm.SCHEMA_PATH))
    assert unknown == {"謎キー": 1}


def test_validate_msdata_main_fails_on_unknown_key(tmp_path):
    path = tmp_path / "msData.json"
    write_json(path, [make_record(謎キー=1)])
    assert vm.main([str(path)]) == 1


def test_find_semantic_errors_detects_fullst_points_order():
    errors = vm.find_semantic_errors(
        [
            make_record(
                fullst=[
                    {"name": "AD-PA", "level": 1, "points": 3000},
                    {"name": "AD-FCS", "level": 1, "points": 2000},
                ]
            )
        ]
    )
    assert any("fullst points must be sorted ascending" in error for error in errors)


def test_find_semantic_errors_detects_exact_duplicate_fullst_entry():
    errors = vm.find_semantic_errors(
        [
            make_record(
                fullst=[
                    {"name": "AD-PA", "level": 1, "points": 3000},
                    {"name": "AD-PA", "level": 1, "points": 3000},
                ]
            )
        ]
    )
    assert any("duplicated fullst entry detected" in error for error in errors)


def test_find_semantic_errors_allows_same_name_level_with_different_points():
    errors = vm.find_semantic_errors(
        [
            make_record(
                fullst=[
                    {"name": "AD-PA", "level": 1, "points": 3000},
                    {"name": "AD-PA", "level": 1, "points": 4500},
                ]
            )
        ]
    )
    assert not errors


def test_find_semantic_errors_allows_duplicate_none_points_fullst_entries():
    errors = vm.find_semantic_errors(
        [
            make_record(
                fullst=[
                    {"name": "AD-PA", "level": 1, "points": None},
                    {"name": "AD-PA", "level": 1, "points": None},
                ]
            )
        ]
    )
    assert not errors


def test_find_semantic_errors_detects_attr_mismatch_across_levels():
    errors = vm.find_semantic_errors(
        [
            make_record(ms_name="テスト機_LV1", 属性="汎用"),
            make_record(ms_name="テスト機_LV2", 属性="強襲"),
        ]
    )
    assert any("属性 mismatch across levels" in error for error in errors)


def test_find_semantic_errors_detects_wiki_url_mismatch_across_levels():
    errors = vm.find_semantic_errors(
        [
            make_record(ms_name="テスト機_LV1", wiki_url="https://example.com/ms/a"),
            make_record(ms_name="テスト機_LV2", wiki_url="https://example.com/ms/b"),
        ]
    )
    assert any("wiki_url mismatch across levels" in error for error in errors)


def test_find_semantic_errors_detects_sortie_turn_contradiction():
    errors = vm.find_semantic_errors(
        [
            make_record(
                出撃_地上可=False,
                出撃_宇宙可=True,
                旋回_宇宙_通常時=70,
                旋回_地上_通常時=75,
            )
        ]
    )
    assert any("ground sortie is false but ground turn values exist" in error for error in errors)
