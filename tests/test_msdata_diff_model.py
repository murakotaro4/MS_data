"""msdata_diff_model（差分計算）の境界・不正入力テスト。

Markdown 描画を通した正常系は test_report_msdata_diff.py が担う。ここでは
描画経由では通らない分岐（不正レコード、値の種類ごとの整形、fullst の
非 dict 項目、LV なしの並び順）を直接確認する。
"""

from collections import Counter

from ms_data.reporting import msdata_diff_model as model


def test_index_by_name_counts_invalid_and_duplicate_records():
    first = {"MS名": "ガンダム_LV1", "HP": 1}
    last = {"MS名": "ガンダム_LV1", "HP": 2}
    records = [
        first,
        "not a dict",
        {"HP": 3},
        {"MS名": 123},
        {"MS名": "   "},
        last,
    ]

    indexed, name_counts, invalid_count = model.index_by_name(records)

    # 重複は後勝ちで保持し、件数は重複カウンタに残す
    assert indexed == {"ガンダム_LV1": last}
    assert name_counts == Counter({"ガンダム_LV1": 2})
    # 非 dict・MS名なし・非文字列・空白のみの4件
    assert invalid_count == 4


def test_global_keys_returns_union():
    assert model.global_keys([{"a": 1, "b": 2}, {"b": 3, "c": 4}]) == {"a", "b", "c"}
    assert model.global_keys([]) == set()


def test_diff_summary_and_field_counts():
    old = {
        "A_LV1": {"MS名": "A_LV1", "HP": 1, "旧項目": 0},
        "B_LV1": {"MS名": "B_LV1", "HP": 1},
        "C_LV1": {"MS名": "C_LV1", "HP": 1},
    }
    new = {
        "A_LV1": {"MS名": "A_LV1", "HP": 2, "新項目": None},
        "B_LV1": {"MS名": "B_LV1", "HP": 1},
        "D_LV1": {"MS名": "D_LV1", "HP": 1},
    }

    assert model.diff_summary(old, new) == (3, 3, 1, 1, 1)

    changed, added, removed = model.diff_field_counts(old, new)
    assert changed == Counter({"HP": 1})
    assert added == Counter({"新項目": 1})
    assert removed == Counter({"旧項目": 1})


def test_get_changed_records_detail_distinguishes_deleted_from_none():
    old = {"A_LV1": {"HP": 1, "旧項目": None, "同値": 5}}
    new = {"A_LV1": {"HP": 2, "新項目": None, "同値": 5}}

    result = model.get_changed_records_detail(old, new)

    assert len(result) == 1
    name, changes = result[0]
    assert name == "A_LV1"
    # 追加 → 削除 → 変更 の順。値が None でも欠落とは別扱いにする
    assert [(op, key) for op, key, _, _ in changes] == [
        ("added", "新項目"),
        ("removed", "旧項目"),
        ("changed", "HP"),
    ]
    added, removed, changed = changes
    assert added[2] is model._DELETED and added[3] is None
    assert removed[2] is None and removed[3] is model._DELETED
    assert changed[2:] == (1, 2)


def test_get_changed_records_detail_skips_unchanged_records():
    same = {"A_LV1": {"HP": 1}}
    assert model.get_changed_records_detail(same, {"A_LV1": {"HP": 1}}) == []


def test_format_value_plain_variants():
    assert model.format_value_plain(model._DELETED) == ""
    assert model.format_value_plain(None) == "null"
    assert model.format_value_plain(1200) == "1200"
    # 文字列は引用符なし・改行はエスケープして1行に保つ
    assert model.format_value_plain("少尉\n01") == "少尉\\n01"
    assert model.format_value_plain(["格闘", 1]) == '["格闘", 1]'
    assert model.format_value_plain({"名称": "盾"}) == '{"名称": "盾"}'


def test_format_value_plain_truncates_to_max_len():
    assert model.format_value_plain("あ" * 10, max_len=10) == "あ" * 10
    truncated = model.format_value_plain("あ" * 11, max_len=10)
    assert truncated == "あ" * 9 + "…"
    assert len(truncated) == 10


def test_fullst_point_text_distinguishes_missing_and_null():
    assert model.fullst_point_text({"name": "強行出撃"}) == "未設定"
    assert model.fullst_point_text({"name": "強行出撃", "points": None}) == "null"
    assert model.fullst_point_text({"name": "強行出撃", "points": 0}) == "0"
    assert model.fullst_point_text(None) == ""
    assert model.fullst_point_text("強行出撃") == ""


def test_indexed_fullst_items_counts_duplicates_and_non_dict_items():
    first = {"name": "フレーム補強", "level": 1, "points": 10}
    second = {"name": "フレーム補強", "level": 1, "points": 20}

    indexed = model.indexed_fullst_items([first, "強行出撃", second, {}])

    assert indexed == {
        ("フレーム補強", 1, 1): (1, first),
        ("強行出撃", "", 1): (2, "強行出撃"),
        ("フレーム補強", 1, 2): (3, second),
        ("", "", 1): (4, {}),
    }


def test_fullst_detail_rows_puts_removed_rows_last_and_tolerates_non_list():
    old = [
        {"name": "削除項目", "level": 1, "points": 5},
        {"name": "継続項目", "level": 2, "points": 10},
    ]
    new = [
        {"name": "追加項目", "level": 1},
        {"name": "継続項目", "level": 2, "points": None},
    ]

    assert model.fullst_detail_rows(old, new) == [
        ["", "1", "追加項目", "1", "", "未設定"],
        ["2", "2", "継続項目", "2", "10", "null"],
        ["1", "", "削除項目", "1", "5", ""],
    ]
    # fullst がリストでない（欠落・null）側は空として扱う
    assert model.fullst_detail_rows(None, new[:1]) == [
        ["", "1", "追加項目", "1", "", "未設定"]
    ]
    assert model.fullst_detail_rows(model._DELETED, None) == []


def test_level_sort_keys_place_names_without_level_last():
    names = ["ガンダム", "ガンダム_LV10", "ガンダム_LV2", "ザク_LV1"]

    assert sorted(names, key=model.level_sort_key) == [
        "ザク_LV1",
        "ガンダム_LV2",
        "ガンダム_LV10",
        "ガンダム",
    ]
    assert model.level_sort_key("ガンダム") == (999, "ガンダム")
    assert model.base_ms_name("ガンダム_LV10") == "ガンダム"
    # LV サフィックス以外（名前途中の _LV）は基底名に残す
    assert model.base_ms_name("試作_LV機_LV3") == "試作_LV機"
    assert sorted(names, key=model.ms_level_sort_key) == [
        "ガンダム_LV2",
        "ガンダム_LV10",
        "ガンダム",
        "ザク_LV1",
    ]
