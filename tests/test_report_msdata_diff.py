from datetime import datetime
from textwrap import dedent

from scripts.report_msdata_diff import build_report_lines


def test_build_report_lines_golden():
    old = [
        {"MS名": "A_LV1", "コスト": 300, "HP": 100},
        {"MS名": "B_LV1", "コスト": 350, "HP": 200},
    ]
    new = [
        {"MS名": "A_LV1", "コスト": 300, "HP": 110, "新項目": 1},
        {"MS名": "C_LV1", "コスト": 320, "HP": 150},
    ]

    lines, summary = build_report_lines(
        old,
        new,
        generated_at=datetime(2026, 3, 7, 12, 34, 56),
        old_label="old.json",
        new_label="new.json",
        list_limit=10,
        notes=["基準データ: old", "比較先データ: new"],
    )

    expected = (
        dedent(
            """
        # msData 差分レポート (20260307)

        - 生成日時: 2026-03-07 12:34:56
        - 比較対象: `old.json` → `new.json`
        - 基準データ: old
        - 比較先データ: new

        ## サマリ
        - レコード数: 2 → 2 | +1 -1 ~1
        - グローバル項目数: 3 → 4 | +1 -0
        - 追加された項目: 新項目
        - 削除された項目: なし

        ## 変更項目の頻度（上位）
        | 項目 | 件数 |
        | --- | --- |
        | HP | 1 |

        ## レコード単位で新規追加された項目（頻度）
        | 項目 | 件数 |
        | --- | --- |
        | 新項目 | 1 |

        ## レコード単位で削除された項目（頻度）
        | 項目 | 件数 |
        | --- | --- |
        | なし |  |

        ## 追加レコード一覧

        - 件数: 1

        ### C
        | LV | 属性 | コスト | HP | スピード | 高速移動 | スラスター | 射撃 | 格闘 | スロット(近/中/遠) | fullst |
        | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
        | LV1 |  | 320 | 150 |  |  |  |  |  |  | 0 |

        ## 削除レコード一覧

        - 件数: 1

        ### B
        | LV | 属性 | コスト | HP | スピード | 高速移動 | スラスター | 射撃 | 格闘 | スロット(近/中/遠) | fullst |
        | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
        | LV1 |  | 350 | 200 |  |  |  |  |  |  | 0 |

        ## 変更レコード一覧

        - 件数: 1

        ### A
        | LV | 項目 | 変更前 | 変更後 |
        | --- | --- | --- | --- |
        | LV1 | 新項目 |  | 1 |
        | LV1 | HP | 100 | 110 |
        """
        )
        .strip()
        .splitlines()
        + [""]
    )

    assert summary == "records: 2 -> 2 | +1 -1 ~1"
    assert lines == expected


def test_changed_records_are_grouped_by_base_ms_name():
    old = [
        {"MS名": "A_LV1", "HP": 100},
        {"MS名": "A_LV2", "HP": 200},
    ]
    new = [
        {"MS名": "A_LV1", "HP": 110},
        {"MS名": "A_LV2", "HP": 210},
    ]

    lines, _ = build_report_lines(
        old,
        new,
        generated_at=datetime(2026, 3, 7, 12, 34, 56),
        list_limit=10,
    )

    changed_start = lines.index("## 変更レコード一覧")
    changed_section = lines[changed_start:]

    assert changed_section.count("### A") == 1
    assert "| LV | 項目 | 変更前 | 変更後 |" in changed_section
    assert "| LV1 | HP | 100 | 110 |" in changed_section
    assert "| LV2 | HP | 200 | 210 |" in changed_section


def test_fullst_change_has_detail_table():
    old = [
        {
            "MS名": "A_LV2",
            "fullst": [
                {"name": "強行出撃", "level": 1, "points": None},
                {"name": "AD-PA", "level": 1, "points": None},
            ],
        },
    ]
    new = [
        {
            "MS名": "A_LV2",
            "fullst": [
                {"name": "AD-PA", "level": 1, "points": None},
                {"name": "強行出撃", "level": 1, "points": None},
            ],
        },
    ]

    lines, _ = build_report_lines(
        old,
        new,
        generated_at=datetime(2026, 3, 7, 12, 34, 56),
        list_limit=10,
    )

    assert "| LV2 | fullst | 2件 | 2件 |" in lines
    assert "LV2 fullst 明細:" in lines
    assert (
        "| 変更前 No | 変更後 No | 名称 | Lv | 変更前 points | 変更後 points |"
    ) in lines
    assert "| 1 | 2 | 強行出撃 | 1 | null | null |" in lines
    assert "| 2 | 1 | AD\\-PA | 1 | null | null |" in lines
