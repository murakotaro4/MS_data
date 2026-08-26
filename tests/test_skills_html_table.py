import pytest
from bs4 import BeautifulSoup

from ms_data.scraping.skills_html import (
    SKILL_URL,
    _effects_from_lines,
    _extract_activation,
    _extract_duration,
    _parse_grants,
    _select_main_skill_table,
    _split_lines,
    extract_skill_rows_table,
)


def _skill_table(row_count: int, table_id: str = "skills") -> str:
    rows = "".join(
        f"<tr><th>スキル{i}</th><td>LV{i}</td><td>説明{i}</td></tr>"
        for i in range(1, row_count + 1)
    )
    return f'<table id="{table_id}">{rows}</table>'


@pytest.mark.parametrize("row_count", [0, 4])
def test_select_main_skill_table_rejects_score_below_five(row_count):
    soup = BeautifulSoup(_skill_table(row_count), "lxml")

    assert _select_main_skill_table(soup) is None


def test_select_main_skill_table_accepts_score_five():
    soup = BeautifulSoup(_skill_table(5), "lxml")

    selected = _select_main_skill_table(soup)

    assert selected is not None
    assert selected["id"] == "skills"


def test_select_main_skill_table_uses_highest_score():
    html = _skill_table(5, "candidate") + _skill_table(6, "main")
    soup = BeautifulSoup(html, "lxml")

    selected = _select_main_skill_table(soup)

    assert selected is not None
    assert selected["id"] == "main"


def test_extract_skill_rows_table_returns_empty_below_threshold():
    assert extract_skill_rows_table(_skill_table(4)) == {
        "source": SKILL_URL,
        "rows": [],
    }


def test_extract_skill_rows_table_handles_three_two_and_one_td_rows():
    html = """
    <table>
      <tr><th>能力UP「EXAM」</th><td>LV1</td><td>共通説明</td><td>詳細1<br/>続き</td></tr>
      <tr><th>採点用2</th><td>LV2</td><td>説明2</td><td>詳細2</td></tr>
      <tr><th>採点用3</th><td>LV3</td><td>説明3</td><td>詳細3</td></tr>
      <tr><th>採点用4</th><td>LV4</td><td>説明4</td><td>詳細4</td></tr>
      <tr><th>採点用5</th><td>LV5</td><td>説明5</td><td>詳細5</td></tr>
      <tr><th>採点対象外</th></tr>
      <tr><td>見出し行</td><td>無視される</td></tr>
      <tr><td>LV6</td><td>詳細6<br/>続き</td></tr>
      <tr><td>LV7</td></tr>
    </table>
    """

    result = extract_skill_rows_table(html)

    assert result["source"] == SKILL_URL
    assert len(result["rows"]) == 7
    assert result["rows"][0] == {
        "skill": "能力UP「EXAM」",
        "level": 1,
        "desc": "共通説明",
        "details_text": "詳細1 続き",
        "details_html": "詳細1<br/>続き",
    }
    assert result["rows"][-2] == {
        "skill": "採点対象外",
        "level": 6,
        "desc": "説明5",
        "details_text": "詳細6 続き",
        "details_html": "詳細6<br/>続き",
    }
    assert result["rows"][-1] == {
        "skill": "採点対象外",
        "level": 7,
        "desc": "説明5",
        "details_text": "",
        "details_html": "",
    }


def test_extract_activation_collects_auto_and_both_conditions():
    result = _extract_activation(
        "タッチパッドを押すと自動で発動。HP 30%以下、使用から 12秒 経過で発動可"
    )

    assert result == {
        "type": "auto",
        "trigger": "touchpad",
        "conditions": {"hp_leq_percent": 30, "after_seconds_to_trigger": 12},
    }


def test_extract_duration_uses_generic_seconds_fallback():
    assert _extract_duration("特殊効果の時間は 75秒") == 75


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("緊急回避制御 Lv2が付与", {"skill": "緊急回避制御", "level": 2}),
        ("付与なし", None),
    ],
)
def test_parse_grants_documents_current_format(text, expected):
    assert _parse_grants(text) == expected


def test_effects_from_lines_handles_resistance_team_heal_and_both_tags():
    effects, aux = _effects_from_lines(
        [
            "",
            "各耐性 + 8",
            "自機及び味方を 1200 回復",
            "発動中は無敵かつダメージリアクション無効",
        ]
    )

    assert effects == {"各耐性": {"op": "add", "value": 8}}
    assert aux == {
        "hp_heal_team": 1200,
        "tags": ["invincible_on_cast", "no_reaction_on_cast"],
    }


def test_split_lines_keeps_plain_line_and_splits_bullets():
    assert _split_lines("前置き<br/>・射撃補正＋5・格闘補正＋10") == [
        "前置き",
        "射撃補正+5",
        "格闘補正+10",
    ]
