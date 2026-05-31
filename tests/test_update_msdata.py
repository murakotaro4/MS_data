import json

from scripts import update_msdata


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
