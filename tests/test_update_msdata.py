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
