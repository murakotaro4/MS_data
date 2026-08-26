"""Markdown テーブル生成の出力バイト列を固定する golden テスト。"""

from __future__ import annotations

import pytest

from ms_data.audit.audit_field_completeness import (
    _append_table as append_field_completeness_table,
)
from ms_data.audit.audit_official_overrides import (
    _append_lifecycle_table as append_official_overrides_lifecycle_table,
)
from ms_data.audit.audit_official_overrides import (
    _append_table as append_official_overrides_table,
)
from ms_data.audit.detect_msdata_rollbacks import _append_rows as append_rollback_rows
from ms_data.reporting.report_msdata_diff import append_table as append_diff_table


def _bytes(lines: list[str]) -> bytes:
    return "\n".join(lines).encode("utf-8")


def test_diff_table_empty_golden_bytes() -> None:
    lines: list[str] = []

    append_diff_table(lines, ["名前", "値"], [])

    expected = ("| 名前 | 値 |\n" "| --- | --- |\n" "| なし |  |").encode("utf-8")
    assert _bytes(lines) == expected


def test_diff_table_non_empty_golden_bytes() -> None:
    lines: list[str] = []

    append_diff_table(
        lines,
        ["名前", "値"],
        [["ガンダム", "100"], ["ザク|Ⅱ", ""]],
    )

    expected = (
        "| 名前 | 値 |\n" "| --- | --- |\n" "| ガンダム | 100 |\n" "| ザク|Ⅱ |  |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_field_completeness_table_empty_golden_bytes() -> None:
    lines: list[str] = []

    append_field_completeness_table(lines, [])

    expected = (
        "| MS名 | 項目 | 分類 | 値 | 理由 | review_after |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| なし |  |  |  |  |  |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_field_completeness_table_non_empty_golden_bytes() -> None:
    lines: list[str] = []
    rows = [
        {
            "MS名": "ガンダム_LV1",
            "field": "カウンター",
            "category": "empty_value",
            "value": {"候補": ["連続格闘", None]},
            "reason": "要確認",
            "review_after": "2026-09-01",
        }
    ]

    append_field_completeness_table(lines, rows)

    expected = (
        "| MS名 | 項目 | 分類 | 値 | 理由 | review_after |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| ガンダム_LV1 | カウンター | empty_value | "
        '{"候補": ["連続格闘", null]} | 要確認 | 2026-09-01 |'
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_field_completeness_table_preserves_partial_output_on_error() -> None:
    lines: list[str] = []
    rows = [
        {
            "MS名": "ガンダム_LV1",
            "field": "カウンター",
            "category": "empty_value",
            "value": None,
        },
        {"field": "HP", "category": "missing_key"},
    ]

    with pytest.raises(KeyError, match="MS名"):
        append_field_completeness_table(lines, rows)

    expected = (
        "| MS名 | 項目 | 分類 | 値 | 理由 | review_after |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| ガンダム_LV1 | カウンター | empty_value |  |  |  |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_official_overrides_table_empty_golden_bytes() -> None:
    lines: list[str] = []

    append_official_overrides_table(lines, [])

    expected = (
        "| MS名 | 項目 | 状態 | 変更前 | 取得値 | 現在値 | override | stale |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| なし |  |  |  |  |  |  |  |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_official_overrides_table_non_empty_golden_bytes() -> None:
    lines: list[str] = []
    rows = [
        {
            "MS名": "ザクⅡ_LV2",
            "field": "fullst",
            "status": "protected_by_override",
            "before": None,
            "raw": [1, "二"],
            "current": {"値": 3},
            "override": [4],
            "stale": None,
        }
    ]

    append_official_overrides_table(lines, rows)

    expected = (
        "| MS名 | 項目 | 状態 | 変更前 | 取得値 | 現在値 | override | stale |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        '| ザクⅡ_LV2 | fullst | protected_by_override |  | [1, "二"] | '
        '{"値": 3} | [4] |  |'
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_official_overrides_table_preserves_partial_output_on_error() -> None:
    lines: list[str] = []
    rows = [
        {
            "MS名": "ザクⅡ_LV2",
            "field": "HP",
            "status": "protected_by_override",
            "before": 100,
            "raw": 90,
            "current": 100,
            "override": 100,
            "stale": 90,
        },
        {"field": "HP"},
    ]

    with pytest.raises(KeyError, match="MS名"):
        append_official_overrides_table(lines, rows)

    expected = (
        "| MS名 | 項目 | 状態 | 変更前 | 取得値 | 現在値 | override | stale |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| ザクⅡ_LV2 | HP | protected_by_override | 100 | 90 | 100 | 100 | 90 |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_official_overrides_lifecycle_table_empty_golden_bytes() -> None:
    lines: list[str] = []

    append_official_overrides_lifecycle_table(lines, [])

    expected = (
        "| MS名 | 項目 | 期限状態 | review_after | remove_after | 状態 | override | 取得値 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| なし |  |  |  |  |  |  |  |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_official_overrides_lifecycle_table_non_empty_golden_bytes() -> None:
    lines: list[str] = []
    rows = [
        {
            "MS名": "Ζガンダム_LV1",
            "field": "HP",
            "lifecycle": "review_due",
            "review_after": "2026-08-01",
            "remove_after": "2026-10-01",
            "status": "current_matches_override",
            "override": {"値": 20000},
            "raw": [19000, None],
        }
    ]

    append_official_overrides_lifecycle_table(lines, rows)

    expected = (
        "| MS名 | 項目 | 期限状態 | review_after | remove_after | 状態 | override | 取得値 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| Ζガンダム_LV1 | HP | review_due | 2026-08-01 | 2026-10-01 | "
        'current_matches_override | {"値": 20000} | [19000, null] |'
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_official_overrides_lifecycle_table_preserves_partial_output_on_error() -> None:
    lines: list[str] = []
    rows = [
        {
            "MS名": "Ζガンダム_LV1",
            "field": "HP",
            "lifecycle": "review_due",
            "review_after": "2026-08-01",
            "remove_after": "2026-10-01",
            "status": "current_matches_override",
            "override": 20000,
            "raw": 19000,
        },
        {"field": "HP"},
    ]

    with pytest.raises(KeyError, match="MS名"):
        append_official_overrides_lifecycle_table(lines, rows)

    expected = (
        "| MS名 | 項目 | 期限状態 | review_after | remove_after | 状態 | override | 取得値 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| Ζガンダム_LV1 | HP | review_due | 2026-08-01 | 2026-10-01 | "
        "current_matches_override | 20000 | 19000 |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_rollback_rows_empty_golden_bytes() -> None:
    lines: list[str] = []

    append_rollback_rows(lines, [])

    expected = (
        "| 種別 | MS名 | 項目 | 変更前 | 変更後 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| なし |  |  |  |  |"
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_rollback_rows_non_empty_golden_bytes() -> None:
    lines: list[str] = []
    rows = [
        {
            "type": "numeric_decrease",
            "MS名": "百式_LV1",
            "field": "HP",
            "old": {"値": 18000},
            "new": [17000, None],
        }
    ]

    append_rollback_rows(lines, rows)

    expected = (
        "| 種別 | MS名 | 項目 | 変更前 | 変更後 |\n"
        "| --- | --- | --- | --- | --- |\n"
        '| numeric_decrease | 百式_LV1 | HP | {"値": 18000} | [17000, null] |'
    ).encode("utf-8")
    assert _bytes(lines) == expected


def test_rollback_rows_preserves_partial_output_on_error() -> None:
    lines: list[str] = []
    rows = [
        {
            "type": "numeric_decrease",
            "MS名": "百式_LV1",
            "field": "HP",
            "old": 18000,
            "new": 17000,
        },
        {"MS名": "百式_LV2", "field": "HP"},
    ]

    with pytest.raises(KeyError, match="type"):
        append_rollback_rows(lines, rows)

    expected = (
        "| 種別 | MS名 | 項目 | 変更前 | 変更後 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| numeric_decrease | 百式_LV1 | HP | 18000 | 17000 |"
    ).encode("utf-8")
    assert _bytes(lines) == expected
