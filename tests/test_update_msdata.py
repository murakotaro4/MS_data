import json

import pytest

from ms_data.pipeline import update_msdata


def test_normalize_record_assigns_wiki_url(monkeypatch):
    monkeypatch.setattr(
        update_msdata,
        "INDEX_URL_MAP",
        {"ザクⅡ": "https://example.com/zaku2"},
        raising=False,
    )
    record = {"MS名": "ザクII_LV1"}

    normalized = update_msdata.normalize_record(record)

    assert normalized["MS名"] == "ザクⅡ_LV1"
    assert normalized["wiki_url"] == "https://example.com/zaku2"


def test_stable_key_order_respects_priority():
    sample = {
        "MS名": "テスト_LV1",
        "耐ビーム補正": 10,
        "スピード": 100,
        "耐格闘補正": 5,
        "高速移動": 200,
        "耐実弾補正": 8,
        "射撃補正": 15,
        "格闘補正": 12,
        "スラスター": 60,
        "旋回_宇宙_通常時": 45,
        "旋回_地上_通常時": 40,
        "wiki_url": "https://example.com/test",
        "HP": 12000,
    }

    ordered = update_msdata.stable_key_order(sample)

    expected = [
        "MS名",
        "wiki_url",
        "HP",
        "耐実弾補正",
        "耐ビーム補正",
        "耐格闘補正",
        "射撃補正",
        "格闘補正",
        "スピード",
        "高速移動",
        "スラスター",
        "旋回_地上_通常時",
        "旋回_宇宙_通常時",
    ]
    actual = [k for k in ordered if k in expected]

    assert actual == expected


def test_apply_official_overrides_prevents_stale_rollback_only():
    records = {
        "ザクⅢ改_LV1": {
            "MS名": "ザクⅢ改_LV1",
            "HP": 23500,
            "スピード": 145,
        }
    }
    overrides = {
        "ザクⅢ改_LV1": {
            "HP": {"value": 27000, "stale_value": 23500},
        }
    }

    changed = update_msdata.apply_official_overrides(records, overrides)

    assert changed == 1
    assert records["ザクⅢ改_LV1"]["HP"] == 27000
    assert records["ザクⅢ改_LV1"]["スピード"] == 145


def test_apply_official_overrides_keeps_newer_non_stale_value():
    records = {
        "ザクⅢ改_LV1": {
            "MS名": "ザクⅢ改_LV1",
            "HP": 28000,
        }
    }
    overrides = {
        "ザクⅢ改_LV1": {
            "HP": {"value": 27000, "stale_value": 23500},
        }
    }

    changed = update_msdata.apply_official_overrides(records, overrides)

    assert changed == 0
    assert records["ザクⅢ改_LV1"]["HP"] == 28000


def test_update_main_allows_partial_updates_while_guarding_official_values(
    tmp_path, capsys
):
    msdata = tmp_path / "msData.json"
    incoming = tmp_path / "details.json"
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()

    msdata.write_text(
        json.dumps(
            [
                {
                    "MS名": "ザクⅢ改_LV1",
                    "HP": 27000,
                    "スピード": 140,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    incoming.write_text(
        json.dumps(
            [
                {
                    "MS名": "ザクⅢ改_LV1",
                    "HP": 23500,
                    "スピード": 145,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (overrides_dir / "20260528.json").write_text(
        json.dumps(
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
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = update_msdata.main(
        [
            "--in-place",
            "--output",
            str(msdata),
            "--official-overrides-dir",
            str(overrides_dir),
            str(incoming),
        ]
    )

    assert rc == 0
    output = json.loads(msdata.read_text(encoding="utf-8"))
    assert output == [{"MS名": "ザクⅢ改_LV1", "HP": 27000, "スピード": 145}]
    assert "official-overrides" in capsys.readouterr().err


def test_update_main_guards_confirmed_upper_level_hp_without_blocking_slots(
    tmp_path, capsys
):
    msdata = tmp_path / "msData.json"
    incoming = tmp_path / "details.json"
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()

    msdata.write_text(
        json.dumps(
            [
                {
                    "MS名": "ザクⅢ改_LV3",
                    "HP": 28500,
                    "近スロット": 26,
                    "中スロット": 19,
                    "遠スロット": 11,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    incoming.write_text(
        json.dumps(
            [
                {
                    "MS名": "ザクⅢ改_LV3",
                    "HP": 23000,
                    "近スロット": 27,
                    "中スロット": 22,
                    "遠スロット": 14,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (overrides_dir / "20260528.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "overrides": [
                    {
                        "MS名": "ザクⅢ改_LV3",
                        "values": {"HP": 28500},
                        "stale_values": {"HP": 23000},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = update_msdata.main(
        [
            "--in-place",
            "--output",
            str(msdata),
            "--official-overrides-dir",
            str(overrides_dir),
            str(incoming),
        ]
    )

    assert rc == 0
    output = json.loads(msdata.read_text(encoding="utf-8"))
    assert output == [
        {
            "MS名": "ザクⅢ改_LV3",
            "HP": 28500,
            "近スロット": 27,
            "中スロット": 22,
            "遠スロット": 14,
        }
    ]
    assert "official-overrides" in capsys.readouterr().err


def test_update_main_writes_raw_snapshot_before_official_overrides(tmp_path):
    msdata = tmp_path / "msData.json"
    incoming = tmp_path / "details.json"
    raw_out = tmp_path / "raw.json"
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()

    msdata.write_text(
        json.dumps([{"MS名": "ザクⅢ改_LV1", "HP": 27000}], ensure_ascii=False),
        encoding="utf-8",
    )
    incoming.write_text(
        json.dumps([{"MS名": "ザクⅢ改_LV1", "HP": 23500}], ensure_ascii=False),
        encoding="utf-8",
    )
    (overrides_dir / "20260528.json").write_text(
        json.dumps(
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
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = update_msdata.main(
        [
            "--in-place",
            "--output",
            str(msdata),
            "--official-overrides-dir",
            str(overrides_dir),
            "--official-overrides-raw-out",
            str(raw_out),
            str(incoming),
        ]
    )

    assert rc == 0
    assert json.loads(raw_out.read_text(encoding="utf-8")) == [
        {"MS名": "ザクⅢ改_LV1", "HP": 23500}
    ]
    assert json.loads(msdata.read_text(encoding="utf-8")) == [
        {"MS名": "ザクⅢ改_LV1", "HP": 27000}
    ]


def test_update_main_raw_snapshot_excludes_unfetched_base_records(tmp_path):
    msdata = tmp_path / "msData.json"
    incoming = tmp_path / "details.json"
    raw_out = tmp_path / "raw.json"
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()

    msdata.write_text(
        json.dumps(
            [
                {"MS名": "ザクⅢ改_LV1", "HP": 27000},
                {"MS名": "別機体_LV1", "HP": 12000},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    incoming.write_text(
        json.dumps([{"MS名": "別機体_LV1", "HP": 12500}], ensure_ascii=False),
        encoding="utf-8",
    )
    (overrides_dir / "20260528.json").write_text(
        json.dumps(
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
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = update_msdata.main(
        [
            "--in-place",
            "--output",
            str(msdata),
            "--official-overrides-dir",
            str(overrides_dir),
            "--official-overrides-raw-out",
            str(raw_out),
            str(incoming),
        ]
    )

    assert rc == 0
    assert json.loads(raw_out.read_text(encoding="utf-8")) == [
        {"MS名": "別機体_LV1", "HP": 12500}
    ]
    assert json.loads(msdata.read_text(encoding="utf-8")) == [
        {"MS名": "ザクⅢ改_LV1", "HP": 27000},
        {"MS名": "別機体_LV1", "HP": 12500},
    ]


def test_load_official_overrides_normalizes_names_and_stale_values(tmp_path):
    overrides_dir = tmp_path / "official_overrides"
    overrides_dir.mkdir()
    (overrides_dir / "override.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "overrides": [
                    {
                        "MS名": "ザクIII改_LV1",
                        "values": {"HP": 27000},
                        "stale_values": {"HP": 23500},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    overrides = update_msdata.load_official_overrides(overrides_dir)

    assert overrides == {
        "ザクⅢ改_LV1": {
            "HP": {"value": 27000, "stale_value": 23500},
        }
    }


def test_update_main_warns_and_uses_default_for_broken_base_json(tmp_path, capsys):
    msdata = tmp_path / "msData.json"
    incoming = tmp_path / "details.json"
    msdata.write_text("{broken", encoding="utf-8")
    incoming.write_text(
        json.dumps([{"MS名": "テスト機_LV1", "HP": 10000}], ensure_ascii=False),
        encoding="utf-8",
    )

    rc = update_msdata.main(
        [
            "--in-place",
            "--output",
            str(msdata),
            "--no-official-overrides",
            str(incoming),
        ]
    )

    assert rc == 0
    assert json.loads(msdata.read_text(encoding="utf-8")) == [
        {"MS名": "テスト機_LV1", "HP": 10000}
    ]
    assert "warning: failed to load base data" in capsys.readouterr().err


def test_update_main_warns_and_uses_default_for_invalid_utf8_base(
    tmp_path, capsys
):
    msdata = tmp_path / "msData.json"
    incoming = tmp_path / "details.json"
    msdata.write_bytes(b"\xff")
    incoming.write_text(
        json.dumps([{"MS名": "テスト機_LV1", "HP": 10000}], ensure_ascii=False),
        encoding="utf-8",
    )

    rc = update_msdata.main(
        [
            "--in-place",
            "--output",
            str(msdata),
            "--no-official-overrides",
            str(incoming),
        ]
    )

    assert rc == 0
    assert json.loads(msdata.read_text(encoding="utf-8")) == [
        {"MS名": "テスト機_LV1", "HP": 10000}
    ]
    assert "warning: failed to load base data" in capsys.readouterr().err


def test_update_main_does_not_swallow_base_programming_error(
    tmp_path, monkeypatch
):
    msdata = tmp_path / "msData.json"
    msdata.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        update_msdata,
        "load_json",
        lambda path: (_ for _ in ()).throw(TypeError("bad base")),
    )

    with pytest.raises(TypeError, match="bad base"):
        update_msdata.main(
            [
                "--in-place",
                "--output",
                str(msdata),
                "--no-official-overrides",
            ]
        )


def test_load_index_url_map_normalizes_names_and_skips_invalid_entries(tmp_path):
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps(
            [
                {"name": "ザクII", "url": "https://example.com/zaku2"},
                {"name": "名前のみ"},
                {"url": "https://example.com/url-only"},
                "dict ではない要素",
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert update_msdata.load_index_url_map(path) == {
        "ザクⅡ": "https://example.com/zaku2"
    }


def test_load_index_url_map_returns_empty_for_missing_broken_or_non_list(tmp_path):
    assert update_msdata.load_index_url_map(tmp_path / "missing.json") == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert update_msdata.load_index_url_map(broken) == {}

    non_list = tmp_path / "non_list.json"
    non_list.write_text('{"name": "x"}', encoding="utf-8")
    assert update_msdata.load_index_url_map(non_list) == {}


def test_normalize_record_keeps_existing_wiki_url_and_ignores_non_str_name(
    monkeypatch,
):
    monkeypatch.setattr(
        update_msdata, "INDEX_URL_MAP", {"ザクⅡ": "https://example.com/new"}
    )
    kept = update_msdata.normalize_record(
        {"MS名": "ザクⅡ_LV1", "wiki_url": "https://example.com/old"}
    )
    assert kept["wiki_url"] == "https://example.com/old"

    unnamed = update_msdata.normalize_record({"MS名": 123})
    assert unnamed["MS名"] == 123
    assert "wiki_url" not in unnamed


def test_normalize_record_infers_deployment_from_turn_keys():
    both = update_msdata.normalize_record(
        {"旋回_地上_通常時": 40, "旋回_宇宙_通常時": 45}
    )
    assert (both["出撃_地上可"], both["出撃_宇宙可"]) == (True, True)

    ground = update_msdata.normalize_record({"旋回_地上_通常時": 40})
    assert (ground["出撃_地上可"], ground["出撃_宇宙可"]) == (True, False)

    space = update_msdata.normalize_record({"旋回_宇宙_通常時": 45})
    assert (space["出撃_地上可"], space["出撃_宇宙可"]) == (False, True)

    none = update_msdata.normalize_record({})
    assert "出撃_地上可" not in none and "出撃_宇宙可" not in none


def test_normalize_record_does_not_override_explicit_deployment():
    rec = update_msdata.normalize_record(
        {"出撃_宇宙可": True, "旋回_地上_通常時": 40, "旋回_宇宙_通常時": 45}
    )
    assert "出撃_地上可" not in rec
    assert rec["旋回_地上_通常時"] == 40


def test_normalize_record_moves_turn_values_to_matching_side():
    space_only = update_msdata.normalize_record(
        {
            "出撃_地上可": False,
            "出撃_宇宙可": True,
            "旋回_地上_通常時": 40,
            "旋回_地上_変形時": 30,
        }
    )
    assert space_only["旋回_宇宙_通常時"] == 40
    assert space_only["旋回_宇宙_変形時"] == 30
    assert "旋回_地上_通常時" not in space_only
    assert "旋回_地上_変形時" not in space_only

    ground_only = update_msdata.normalize_record(
        {
            "出撃_地上可": True,
            "出撃_宇宙可": False,
            "旋回_宇宙_通常時": 45,
            "旋回_宇宙_変形時": 35,
        }
    )
    assert ground_only["旋回_地上_通常時"] == 45
    assert ground_only["旋回_地上_変形時"] == 35
    assert "旋回_宇宙_通常時" not in ground_only


def test_normalize_record_turn_fix_keeps_existing_correct_side_values():
    rec = update_msdata.normalize_record(
        {
            "出撃_地上可": False,
            "出撃_宇宙可": True,
            "旋回_宇宙_通常時": 45,
            "旋回_地上_通常時": 40,
        }
    )
    assert rec["旋回_宇宙_通常時"] == 45
    assert rec["旋回_地上_通常時"] == 40


def test_normalize_record_drops_null_nullable_int_values():
    # set の反復順はハッシュ依存で "HP" と衝突し得るため、キーを固定する
    key = "スピード"
    assert key in update_msdata.NULLABLE_INT_KEYS
    rec = update_msdata.normalize_record({key: None, "HP": 100})
    assert key not in rec
    assert rec["HP"] == 100


def test_iter_records_from_files_handles_list_dict_and_rejects_scalar(tmp_path):
    as_list = tmp_path / "list.json"
    as_list.write_text(
        json.dumps([{"MS名": "A_LV1"}, "skip"], ensure_ascii=False),
        encoding="utf-8",
    )
    as_dict = tmp_path / "dict.json"
    as_dict.write_text('{"MS名": "B_LV1"}', encoding="utf-8")

    names = [
        r["MS名"] for r in update_msdata.iter_records_from_files([as_list, as_dict])
    ]
    assert names == ["A_LV1", "B_LV1"]

    scalar = tmp_path / "scalar.json"
    scalar.write_text("123", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported JSON structure"):
        list(update_msdata.iter_records_from_files([scalar]))


def test_merge_by_msname_last_wins_and_skips_unnamed():
    merged = update_msdata.merge_by_msname(
        [
            {"MS名": "A_LV1", "HP": 1},
            {"HP": 2},
            {"MS名": 5, "HP": 3},
            {"MS名": "A_LV1", "HP": 4},
        ]
    )
    assert merged == {"A_LV1": {"MS名": "A_LV1", "HP": 4}}
