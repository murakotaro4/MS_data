"""実通知の差分fixtureをCLIから生成し、左右比較とテキストの意味を検証する。"""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ms_data.reporting.build_update_mail_body import main
from ms_data.reporting.report_msdata_diff import build_report_lines
from ms_data.reporting.update_mail_html import prepare_update_mail
from ms_data.reporting.update_mail_model import enhancement_lines, localize_mail_body


def test_actual_20261009_mail_comparison(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures/reports/diff_msdata_20261009.md"
    text, html = tmp_path / "mail.txt", tmp_path / "mail.html"
    assert (
        main(
            [
                "--report-date",
                "20261009",
                "--result",
                "マージ済み",
                "--changed",
                "true",
                "--diff-path",
                str(fixture),
                "--out",
                str(text),
                "--html-out",
                str(html),
            ]
        )
        == 0
    )
    soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
    tables = soup.select(".enhancements")
    assert len(tables) == 2
    expected = [
        [
            ("AD-PA", 1, 1030),
            ("耐格闘装甲補強", 1, 2060),
            ("フレーム補強", 1, 3090),
            ("複合拡張パーツスロット", 1, 4120),
            ("AD-PA", 4, 8240),
            ("緊急格闘防御機構", 1, 12360),
        ],
        [
            ("耐ビーム装甲補強", 1, 660),
            ("耐格闘装甲補強", 1, 1320),
            ("AD-PA", 1, 1980),
            ("複合拡張パーツスロット", 1, 2650),
            ("耐ビーム装甲補強", 4, 5300),
            ("AD-PA", 4, 7950),
        ],
    ]
    plain = text.read_text(encoding="utf-8")
    for table, skills in zip(tables, expected, strict=True):
        assert [th.get_text() for th in table.select("thead th")] == [
            "強化項目・強化Lv",
            "変更前",
            "変更後",
        ]
        rows = table.select("tbody tr")
        assert len(rows) == 6
        for row, (name, level, points) in zip(rows, skills, strict=True):
            assert [cell.get_text(" ", strip=True) for cell in row.select("th,td")] == [
                f"{name} 強化Lv{level}",
                "値なし",
                f"{points:,}",
            ]
            assert f"{name}（強化Lv{level}）" in plain
            assert str(points) in plain
    for name in ["ディマーテル", "プロトタイプΖΖガンダム", "キャノンガンダム"]:
        assert name in soup.get_text() and name in plain
    assert "必要リサイクルチケット" in soup.get_text() and "380" in plain
    assert "機体LV2" in soup.get_text()
    assert "必要強化値" in soup.get_text() and "必要強化値" in plain
    assert "null" not in plain and "fullst" not in plain
    assert "6件 | 6件" not in plain
    assert len(html.read_bytes()) <= 80 * 1024


@pytest.mark.parametrize(
    "before,after,expected",
    [
        (
            [
                {"name": "A", "level": 1, "points": 0},
                {"name": "A", "level": 4, "points": 10},
            ],
            [
                {"name": "A", "level": 4, "points": 10},
                {"name": "A", "level": 1, "points": 0},
            ],
            [
                ["A 強化Lv4", "10（順序2）", "10（順序1）"],
                ["A 強化Lv1", "0（順序1）", "0（順序2）"],
            ],
        ),
        (
            [{"name": "A", "level": 1}, {"name": "A", "level": 1, "points": None}],
            [
                {"name": "A", "level": 1, "points": 0},
                {"name": "A", "level": 1, "points": 10},
            ],
            [["A 強化Lv1", "未設定", "0"], ["A 強化Lv1", "値なし", "10"]],
        ),
        (
            [{"name": "旧|名称", "level": 1, "points": 10}],
            [{"name": "新\\名称", "level": 4, "points": 20}],
            [
                ["新\\名称 強化Lv4", "項目なし", "20（順序1）"],
                ["旧|名称 強化Lv1", "10（順序1）", "項目なし"],
            ],
        ),
        (
            [
                {"name": "A", "level": 1, "points": 10},
                {"name": "B", "level": 1, "points": 20},
            ],
            [
                {"name": "B", "level": 1, "points": 25},
                {"name": "A", "level": 1, "points": 10},
            ],
            [
                ["B 強化Lv1", "20（順序2）", "25（順序1）"],
                ["A 強化Lv1", "10（順序1）", "10（順序2）"],
            ],
        ),
        (
            [],
            [{"name": "A", "level": 1, "points": None}],
            [["A 強化Lv1", "項目なし", "値なし（順序1）"]],
        ),
        (
            [{"name": "A", "level": 1, "points": 0}],
            [],
            [["A 強化Lv1", "0（順序1）", "項目なし"]],
        ),
    ],
)
def test_generated_diff_identity_and_order(
    before: list[dict], after: list[dict], expected: list[list[str]]
) -> None:
    report, _ = build_report_lines(
        [{"MS名": "試作機_LV2", "fullst": before}],
        [{"MS名": "試作機_LV2", "fullst": after}],
    )
    body = "- 結果: マージ済み\n- msData.json変更: true\n" + "\n".join(report)
    view, html = prepare_update_mail(body)
    soup = BeautifulSoup(html, "html.parser")
    actual = [
        [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        for row in soup.select(".enhancements tbody tr")
    ]
    assert actual == expected
    plain = localize_mail_body(body, view=view)
    for row in expected:
        for cell in row[1:]:
            assert cell in plain


def test_unknown_fullst_table_is_preserved_and_machine_scope_is_local() -> None:
    broken = [
        "### 試作機",
        "| LV2 | fullst | 6件 | 6件 |",
        "LV2 fullst 明細（変更後No順）:",
        "| 未知 | 形式 |",
        "| --- | --- |",
        "| 原情報 | null |",
    ]
    assert enhancement_lines(broken)[1:] == broken[1:]
    valid = [
        "### 別機体",
        "| LV2 | fullst | 1件 | 1件 |",
        "LV2 fullst 明細（変更後No順）:",
        "| 変更前 No | 変更後 No | 名称 | Lv | 変更前 points | 変更後 points |",
        "| --- | --- | --- | --- | --- | --- |",
        "| 1 | 1 | A | 1 | null | 10 |",
    ]
    converted = enhancement_lines(broken + valid)
    assert "| LV2 | fullst | 6件 | 6件 |" in converted
    assert "| LV2 | fullst | 1件 | 1件 |" not in converted
    for bad_row in [
        "|  | 1 | A | 1 | 999 | 10 |",
        "| 1 |  | A | 1 | 10 | 999 |",
        "| x | 1 | A | 1 | 0 | 10 |",
    ]:
        malformed = [*valid[:-1], bad_row]
        assert enhancement_lines(malformed) == malformed


def test_actual_mail_audits_share_html_and_text_meaning() -> None:
    body = (Path(__file__).parent / "fixtures/mail/actual-20261009.md").read_text(
        encoding="utf-8"
    )
    view, html = prepare_update_mail(body)
    plain = localize_mail_body(body, view=view)
    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select(".enhancements tbody tr")) == 12
    assert not view.attention
    assert "今回のチェックで要確認の項目なし" in plain
    assert "ガブスレイ" in plain and "ガブスレイ" in soup.get_text()
    assert "37806098586" in plain
    assert "値なし" in plain and "未掲載・空欄・補完等" in plain
    assert len(html.encode("utf-8")) < 80 * 1024
