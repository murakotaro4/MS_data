from pathlib import Path

from scripts.extract_skills import extract_skill_owners_rows_table


FIXTURES = Path(__file__).with_name("fixtures")


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_extract_skill_owners_rows_table_fixture():
    data = extract_skill_owners_rows_table(load_fixture("extract_skill_owners_rowspan.html"))
    rows = {(row["skill"], row["level"], row["role"]): row["owners"] for row in data["rows"]}

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
