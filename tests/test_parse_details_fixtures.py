from pathlib import Path

from scripts.scrape_msdata import parse_details


FIXTURES = Path(__file__).with_name("fixtures")


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_details_space_only_fixture():
    per_level = parse_details(load_fixture("parse_details_space_only.html"))

    assert set(per_level) == {1}
    rec = per_level[1]
    assert rec["属性"] == "汎用"
    assert rec["出撃_地上可"] is False
    assert rec["出撃_宇宙可"] is True
    assert rec["環境適正_地上"] is False
    assert rec["環境適正_宇宙"] is True
    assert "旋回_地上_通常時" not in rec
    assert rec["旋回_宇宙_通常時"] == 72


def test_parse_details_transform_and_fullst_fixture():
    per_level = parse_details(load_fixture("parse_details_transform_fullst.html"))

    assert set(per_level) == {1, 2}
    lv1 = per_level[1]
    lv2 = per_level[2]

    assert lv1["属性"] == "強襲"
    assert lv1["スピード_変形時"] == 190
    assert lv1["高速移動_変形時"] == 235
    assert lv1["射撃補正_変形時"] == 38
    assert lv1["格闘補正_変形時"] == 30
    assert lv1["旋回_地上_変形時"] == 95
    assert [entry["name"] for entry in lv1["fullst"]] == ["強行出撃", "AD-PA", "AD-PA"]
    assert [entry["points"] for entry in lv1["fullst"]] == [None, 2200, 4400]

    assert [entry["name"] for entry in lv2["fullst"]] == ["強行出撃"]
    assert all(entry["points"] is None for entry in lv2["fullst"])


def test_parse_details_tr5_sparse_fullst_keeps_lv4_record():
    per_level = parse_details(load_fixture("parse_details_tr5_sparse_fullst.html"))

    assert set(per_level) == {1, 2, 3, 4}
    assert per_level[3]["MS名"] == "ギャプランTR-5_LV3"
    assert per_level[4]["MS名"] == "ギャプランTR-5_LV4"
    assert per_level[4]["コスト"] == 650
    assert per_level[4]["HP"] == 25000
    assert per_level[4]["スラスター"] == 55

    lv3_fullst = per_level[3]["fullst"]
    assert [entry["name"] for entry in lv3_fullst] == [
        "AD-PA",
        "シールド構造強化",
        "プロペラントタンク",
        "複合拡張パーツスロット",
        "シールド構造強化",
        "AD-PA",
    ]
    assert [entry["points"] for entry in lv3_fullst] == [
        None,
        1260,
        1890,
        2520,
        5040,
        7560,
    ]

    lv4_fullst = per_level[4]["fullst"]
    assert [entry["name"] for entry in lv4_fullst] == [
        "シールド構造強化",
        "プロペラントタンク",
        "複合拡張パーツスロット",
        "シールド構造強化",
        "AD-PA",
        "AD-PA",
    ]
    assert [entry["points"] for entry in lv4_fullst] == [
        None,
        None,
        None,
        None,
        None,
        630,
    ]
