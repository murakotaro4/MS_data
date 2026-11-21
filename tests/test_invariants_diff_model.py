"""差分モデルの保存則・整合性不変条件（プロパティベーステスト）。"""

from __future__ import annotations

from collections import Counter

from hypothesis import example, given
from hypothesis import strategies as st

from ms_data.reporting.msdata_diff_model import (
    diff_field_counts,
    diff_summary,
    fullst_detail_rows,
    get_changed_records_detail,
    index_by_name,
)

_KEYS = st.sampled_from(["HP", "スピード", "コスト", "属性", "近スロット"])
_VALUES = st.one_of(
    st.integers(min_value=0, max_value=30000),
    st.sampled_from(["汎用", "強襲", "支援"]),
    st.none(),
)
_RECORD = st.dictionaries(keys=_KEYS, values=_VALUES, max_size=5)
_RECORD_MAP = st.dictionaries(
    keys=st.sampled_from(["MS_A_LV1", "MS_A_LV2", "MS_B_LV1", "MS_C_LV1", "MS_D_LV1"]),
    values=_RECORD,
    max_size=5,
)


@given(old=_RECORD_MAP, new=_RECORD_MAP)
def test_diff_summary_conservation_reflexivity_and_symmetry(old, new):
    # 反射律: 同一データの差分は常に 0
    assert diff_summary(old, old) == (len(old), len(old), 0, 0, 0)

    old_n, new_n, added, removed, changed = diff_summary(old, new)

    # 件数保存則と範囲制約
    assert old_n == len(old)
    assert new_n == len(new)
    assert old_n + added - removed == new_n
    assert 0 <= added <= new_n
    assert 0 <= removed <= old_n
    assert 0 <= changed <= min(old_n, new_n)

    # 対称律: old/new を反転すると added/removed が入れ替わり changed は保存
    rev_old_n, rev_new_n, rev_added, rev_removed, rev_changed = diff_summary(new, old)
    assert (rev_old_n, rev_new_n) == (new_n, old_n)
    assert (rev_added, rev_removed, rev_changed) == (removed, added, changed)


@given(old=_RECORD_MAP, new=_RECORD_MAP)
@example(old={"A_LV1": {"HP": 1}}, new={"A_LV1": {"HP": 1}})
def test_changed_records_detail_agrees_with_summary_and_field_counts(old, new):
    _, _, _, _, changed_count = diff_summary(old, new)
    details = get_changed_records_detail(old, new)
    changed_fields, added_fields, removed_fields = diff_field_counts(old, new)

    assert len(details) == changed_count
    if old == new:
        assert details == []

    agg_changed: Counter[str] = Counter()
    agg_added: Counter[str] = Counter()
    agg_removed: Counter[str] = Counter()
    for _, ops in details:
        assert len(ops) > 0
        for op, field, _, _ in ops:
            if op == "changed":
                agg_changed[field] += 1
            elif op == "added":
                agg_added[field] += 1
            elif op == "removed":
                agg_removed[field] += 1
            else:
                raise AssertionError(f"unexpected op: {op}")

    assert agg_changed == changed_fields
    assert agg_added == added_fields
    assert agg_removed == removed_fields


_FULLST_ITEM = st.fixed_dictionaries(
    {
        "name": st.sampled_from(["フレーム補強", "AD-FCS", "強行出撃"]),
        "level": st.integers(min_value=1, max_value=5),
        "points": st.one_of(st.none(), st.integers(min_value=100, max_value=5000)),
    }
)


@given(
    old_items=st.lists(_FULLST_ITEM, max_size=8),
    new_items=st.lists(_FULLST_ITEM, max_size=8),
)
def test_fullst_detail_rows_bounds_and_identity(old_items, new_items):
    rows = fullst_detail_rows(old_items, new_items)
    assert (
        max(len(old_items), len(new_items))
        <= len(rows)
        <= len(old_items) + len(new_items)
    )
    assert all(len(row) == 6 for row in rows)

    same_rows = fullst_detail_rows(old_items, old_items)
    assert len(same_rows) == len(old_items)
    for row in same_rows:
        # 同一配列比較なら old_pos == new_pos かつ old_points == new_points
        assert row[0] == row[1]
        assert row[4] == row[5]


@given(
    records=st.lists(
        st.one_of(
            st.fixed_dictionaries(
                {"MS名": st.sampled_from(["A_LV1", "B_LV1", "", "   "])}
            ),
            st.fixed_dictionaries({"other": st.integers()}),
            st.integers(),
            st.none(),
        ),
        max_size=12,
    )
)
def test_index_by_name_preserves_total_record_count(records):
    indexed, counts, invalid = index_by_name(records)
    assert sum(counts.values()) + invalid == len(records)
    assert len(indexed) == len(counts)
