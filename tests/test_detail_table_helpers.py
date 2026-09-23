from bs4 import BeautifulSoup

from ms_data.scraping.detail_page import (
    BASE_REQUIRED,
    apply_required_value_fallbacks,
    expand_cells,
    levels_from_table,
)


def _required_record(**overrides: object) -> dict[str, object]:
    rec: dict[str, object] = dict.fromkeys(BASE_REQUIRED, 1)
    rec["旋回_地上_通常時"] = 70
    rec.update(overrides)
    return rec


def test_levels_from_table_without_thead_skips_rows_without_th():
    html = (
        "<table>"
        "<tr><td>ノイズ</td><td>無視</td></tr>"
        "<tr><th>項目</th><th>LV1</th><th>LV2</th></tr>"
        "</table>"
    )
    table = BeautifulSoup(html, "lxml").find("table")
    assert table is not None
    assert levels_from_table(table) == [1, 2]


def test_expand_cells_truncates_and_pads_and_expands_colspan():
    html = "<tr>" "<td>a</td><td colspan='2'>b</td><td>c</td>" "</tr>"
    cells = BeautifulSoup(html, "lxml").find_all("td")
    assert expand_cells(cells, 4) == ["a", "b", "b", "c"]
    assert expand_cells(cells, 2) == ["a", "b"]
    assert expand_cells(cells[:1], 3) == ["a", None, None]


def test_apply_required_value_fallbacks_copies_thruster_from_previous_lv():
    per_level = {
        1: _required_record(スラスター=55),
        2: _required_record(),
    }
    del per_level[2]["スラスター"]
    apply_required_value_fallbacks(per_level, [1, 2])
    assert per_level[2]["スラスター"] == 55


def test_apply_required_value_fallbacks_skips_without_turn_value():
    per_level = {
        1: _required_record(スラスター=55),
        2: _required_record(),
    }
    del per_level[2]["スラスター"]
    del per_level[2]["旋回_地上_通常時"]
    apply_required_value_fallbacks(per_level, [1, 2])
    assert "スラスター" not in per_level[2]


def test_apply_required_value_fallbacks_skips_non_dict_records():
    per_level = {
        1: _required_record(スラスター=55),
        2: "not-a-record",
        3: _required_record(),
    }
    del per_level[3]["スラスター"]
    apply_required_value_fallbacks(per_level, [1, 2, 3])
    assert per_level[2] == "not-a-record"
    assert per_level[3]["スラスター"] == 55


def test_extract_row_labels_dedupes_and_normalizes():
    from bs4 import BeautifulSoup

    from ms_data.scraping.detail_page import extract_row_labels

    html = """
    <table>
      <tr><th>HP</th><td>1</td></tr>
      <tr><th>射撃補則</th><td>2</td></tr>
      <tr><th>HP</th><td>3</td></tr>
      <tr><td>no th</td></tr>
      <tr><th></th><td>empty</td></tr>
    </table>
    """
    table = BeautifulSoup(html, "lxml").find("table")

    raw, normalized = extract_row_labels(table)

    assert raw == ["HP", "射撃補則"]
    assert normalized[0] == "HP"
    assert "射撃補正" in normalized or "射撃補則" in normalized
    assert extract_row_labels(None) == ([], [])
