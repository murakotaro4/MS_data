"""カウンター欄のテンプレート候補羅列（未記入ページ）の検出と除去のテスト。

新規作成された機体ページではカウンター欄にテンプレートの候補
（押し倒し/投げ/連打攻撃/...）が羅列されたまま残ることがある
（例: フルアーマー・ガンナーガンダム, pages/7696）。
これを実データとして取り込まないことを確認する。
"""

from bs4 import BeautifulSoup

import ms_data.scraping.scrape_msdata as sm

# pages/7696 で実際に観測されたテンプレート未編集のカウンター欄
TEMPLATE_FULL = "押し倒し 投げ 連打攻撃 水平射撃 蹴り飛ばし 連続格闘 特殊"


def test_is_counter_placeholder_detects_template_enumeration():
    # テンプレート全候補の羅列
    assert sm.is_counter_placeholder(TEMPLATE_FULL) is True
    # 一部だけ消した編集途中（既知種別3つ以上の羅列）も未記入扱い
    assert sm.is_counter_placeholder("押し倒し 投げ 特殊") is True


def test_is_counter_placeholder_keeps_legitimate_values():
    # 単一種別
    assert sm.is_counter_placeholder("蹴り飛ばし") is False
    assert sm.is_counter_placeholder("特殊") is False
    # 接頭辞付きの組み合わせ（実データに存在する正当な形式）
    assert sm.is_counter_placeholder("地上：押し倒し 宇宙：蹴り飛ばし") is False
    assert sm.is_counter_placeholder("通常：蹴り飛ばし 高性能：特殊") is False
    assert sm.is_counter_placeholder("通常:蹴り飛ばし 高性能:特殊") is False
    assert sm.is_counter_placeholder(
        "地上：連打攻撃 宇宙：蹴り飛ばし 高性能：特殊"
    ) is False
    # 2語まで・未知語混在は正当値の可能性を残す
    assert sm.is_counter_placeholder("押し倒し 投げ") is False
    assert sm.is_counter_placeholder("押し倒し 投げ 新カウンター") is False
    assert sm.is_counter_placeholder("") is False


def _build_records(counter_cell: str) -> dict:
    html = f"""
    <table>
      <tr><th>項目</th><th>LV1</th></tr>
      <tr><th>カウンター</th><td>{counter_cell}</td></tr>
      <tr><th>格闘判定力</th><td>弱</td></tr>
    </table>
    """
    table = BeautifulSoup(html, "html.parser").find("table")
    return sm.build_base_records(table, "テスト機", [1])


def test_build_base_records_blanks_template_counter():
    rec = _build_records(TEMPLATE_FULL)[1]
    assert rec["カウンター"] == ""
    # 他のテキストフィールドには影響しない
    assert rec["格闘判定力"] == "弱"


def test_build_base_records_keeps_real_counter():
    rec = _build_records("地上：押し倒し 宇宙：蹴り飛ばし")[1]
    assert rec["カウンター"] == "地上：押し倒し 宇宙：蹴り飛ばし"
