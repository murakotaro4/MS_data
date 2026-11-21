"""巻き戻りガード・公式オーバーライドの不変条件（プロパティベーステスト）。"""

from __future__ import annotations

import copy
from datetime import date, timedelta

from hypothesis import example, given
from hypothesis import strategies as st

from ms_data.audit.detect_msdata_rollbacks import (
    NUMERIC_GUARD_FIELDS,
    detect_numeric_changes,
    detect_protected_rollbacks,
)
from ms_data.pipeline.official_overrides import (
    OfficialOverrideValue,
    apply_official_overrides,
)

_MS_NAMES = st.sampled_from(["ガンダム_LV1", "ガンダム_LV2", "ザクⅡ_LV1", "ジム_LV1"])
_GUARD_FIELDS = st.sampled_from(sorted(NUMERIC_GUARD_FIELDS))
_STAT_VALUE = st.integers(min_value=0, max_value=50000)


def _records_st():
    return st.dictionaries(
        keys=_MS_NAMES,
        values=st.dictionaries(keys=_GUARD_FIELDS, values=_STAT_VALUE, max_size=5),
        max_size=4,
    )


def _override_spec_st(today: date):
    return st.builds(
        lambda val, stale, exp_delta: (
            {
                "value": val,
                "stale_value": stale,
                **(
                    {"expires_after": (today + timedelta(days=exp_delta)).isoformat()}
                    if exp_delta is not None
                    else {}
                ),
            }
        ),
        val=_STAT_VALUE,
        stale=_STAT_VALUE,
        exp_delta=st.one_of(st.none(), st.integers(min_value=-10, max_value=10)),
    )


@given(
    records=_records_st(),
    overrides=st.dictionaries(
        keys=_MS_NAMES,
        values=st.dictionaries(
            keys=_GUARD_FIELDS,
            values=_override_spec_st(date(2026, 11, 20)),
            max_size=3,
        ),
        max_size=4,
    ),
)
@example(
    records={"ザクⅢ改_LV1": {"MS名": "ザクⅢ改_LV1", "HP": 23500, "スピード": 145}},
    overrides={"ザクⅢ改_LV1": {"HP": {"value": 27000, "stale_value": 23500}}},
)
@example(
    records={"ザクⅢ改_LV1": {"MS名": "ザクⅢ改_LV1", "HP": 28000}},
    overrides={"ザクⅢ改_LV1": {"HP": {"value": 27000, "stale_value": 23500}}},
)
def test_apply_official_overrides_is_idempotent_and_respects_guards(records, overrides):
    today = date(2026, 11, 20)
    before = copy.deepcopy(records)
    working = copy.deepcopy(records)

    first_changed = apply_official_overrides(working, overrides, today=today)
    after_first = copy.deepcopy(working)
    second_changed = apply_official_overrides(working, overrides, today=today)

    # 冪等性: 2回目の適用は必ず変更 0 件・レコード不変
    assert second_changed == 0
    assert working == after_first

    # 各項目の安全条件を全件検証
    expected_changed = 0
    for name, orig_rec in before.items():
        new_rec = after_first[name]
        name_overrides = overrides.get(name, {})
        for field, orig_val in orig_rec.items():
            if field not in name_overrides:
                # 未指定フィールドは絶対に書き換わらない
                assert new_rec[field] == orig_val
                continue
            spec = name_overrides[field]
            expiry = spec.get("expires_after")
            is_expired = bool(expiry) and today > date.fromisoformat(expiry)
            if is_expired:
                # 期限切れは絶対に書き換わらない
                assert new_rec[field] == orig_val
            elif orig_val != spec["stale_value"]:
                # stale_value 不一致は絶対に書き換わらない
                assert new_rec[field] == orig_val
            else:
                # 有効期限内かつ stale_value 一致なら必ず公式値になる
                assert new_rec[field] == spec["value"]
                expected_changed += int(orig_val != spec["value"])

    assert first_changed == expected_changed


@given(
    name=_MS_NAMES,
    field=_GUARD_FIELDS,
    override_val=_STAT_VALUE,
    stale_val=_STAT_VALUE,
)
def test_protected_rollback_detection_and_override_protection_soundness(
    name: str, field: str, override_val: int, stale_val: int
):
    overrides: dict[str, dict[str, OfficialOverrideValue]] = {
        name: {field: {"value": override_val, "stale_value": stale_val}}
    }
    old = {name: {field: override_val}}
    new = {name: {field: stale_val}}

    findings = detect_protected_rollbacks(old, new, overrides)
    # old == override_val かつ new == stale_val なら必ず検出される
    assert len(findings) == 1
    assert findings[0]["MS名"] == name
    assert findings[0]["field"] == field

    # 同じ new に公式オーバーライドを適用すれば、巻き戻りは必ず 0 件になる
    if override_val != stale_val:
        protected_new = copy.deepcopy(new)
        changed = apply_official_overrides(
            protected_new, overrides, today=date(2026, 11, 20)
        )
        assert changed == 1
        assert detect_protected_rollbacks(old, protected_new, overrides) == []


@given(old=_records_st(), new=_records_st())
def test_detect_numeric_changes_reflexivity_and_antisymmetry(old, new):
    assert detect_numeric_changes(old, old) == []

    forward = detect_numeric_changes(old, new)
    backward = detect_numeric_changes(new, old)

    fwd_inc = sum(1 for c in forward if c["type"] == "numeric_increase")
    fwd_dec = sum(1 for c in forward if c["type"] == "numeric_decrease")
    bwd_inc = sum(1 for c in backward if c["type"] == "numeric_increase")
    bwd_dec = sum(1 for c in backward if c["type"] == "numeric_decrease")

    assert fwd_inc == bwd_dec
    assert fwd_dec == bwd_inc
    assert len(forward) == len(backward)
