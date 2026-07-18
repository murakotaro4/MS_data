from pathlib import Path

from ms_data.scraping.extract_skills import extract_skill_owners_rows_table


FIXTURES = Path(__file__).with_name("fixtures")


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_extract_skill_owners_rows_table_fixture():
    data = extract_skill_owners_rows_table(
        load_fixture("extract_skill_owners_rowspan.html")
    )
    rows = {
        (row["skill"], row["level"], row["role"]): row["owners"] for row in data["rows"]
    }

    assert ("能力UP「EXAM」", 1, "強襲") in rows
    assert [owner["name"] for owner in rows[("能力UP「EXAM」", 1, "強襲")]] == [
        "イフリート改",
        "ブルーディスティニー1号機",
    ]
    assert [owner["name"] for owner in rows[("能力UP「EXAM」", 1, "汎用")]] == [
        "ブルーディスティニー3号機"
    ]
    assert rows[("能力UP「EXAM」", 1, "支援")] == []
    assert [owner["name"] for owner in rows[("能力UP「HADES」", 1, "強襲")]] == [
        "ペイルライダーDII"
    ]
    assert [owner["name"] for owner in rows[("能力UP「HADES」", 1, "汎用")]] == [
        "トーリス・リッター"
    ]
    assert all(
        owner["name"] != "混入してはいけない機体"
        for owners in rows.values()
        for owner in owners
    )


def test_owner_section_limits_tables_and_preserves_block_behavior():
    data = extract_skill_owners_rows_table(
        load_fixture("extract_skill_owners_section.html")
    )
    rows = {(row["skill"], row["level"], row["role"]): row for row in data["rows"]}

    zeus_assault = rows[("能力UP「ZEUS」", 2, "強襲")]
    assert [owner["name"] for owner in zeus_assault["owners"]] == [
        "アンカー行の機体",
        "rowspan継承機体",
    ]
    assert zeus_assault["block_index"] == 0

    hades_general = rows[("能力UP「HADES」", 1, "汎用")]
    assert [owner["name"] for owner in hades_general["owners"]] == [
        "次アンカー行の機体"
    ]
    assert hades_general["block_index"] == 1

    assert all(
        owner["name"] not in {"前セクションの機体", "次セクションの機体"}
        for row in data["rows"]
        for owner in row["owners"]
    )
    assert {row["block_index"] for row in data["rows"]} == {0, 1}


def test_candidate_owner_tables_fallback_without_section_heading():
    data = extract_skill_owners_rows_table(
        load_fixture("extract_skill_owners_fallback.html")
    )

    rows = {
        (row["skill"], row["level"], row["role"]): row["owners"] for row in data["rows"]
    }
    assert [owner["name"] for owner in rows[("能力UP「ALICE」", 1, "支援")]] == [
        "フォールバック機体"
    ]
    assert all(
        owner["name"] != "候補外テーブルの機体"
        for owners in rows.values()
        for owner in owners
    )


def test_no_candidate_owner_table_returns_empty_rows():
    data = extract_skill_owners_rows_table(
        load_fixture("extract_skill_owners_empty.html")
    )

    assert data["rows"] == []
