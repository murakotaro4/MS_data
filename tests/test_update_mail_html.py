from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ms_data.reporting import build_update_mail_body
from ms_data.reporting.report_msdata_diff import build_report_lines
from ms_data.reporting.update_mail_html import render_update_mail

ROOT = Path(__file__).resolve().parents[1]


def _body(report: str, *, changed: bool = True) -> str:
    return (
        "msData 定期更新を実行しました。\n\n"
        "- 実行日: 20260930\n"
        f"- 結果: {'マージ済み' if changed else '成功（差分なし）'}\n"
        f"- msData.json変更: {str(changed).lower()}\n\n" + report
    )


def _report(old: list[dict], new: list[dict]) -> str:
    lines, _ = build_report_lines(old, new)
    # 実際の通知ビルダーが使用するサマリ見出しに置き換える。
    return "\n".join(lines).replace("## サマリ", "## 差分サマリ")


def test_cli_builds_card_mail_and_keeps_original_plain_body(tmp_path: Path) -> None:
    text = tmp_path / "mail.txt"
    html = tmp_path / "html" / "mail.html"
    args = [
        "--report-date",
        "20260601",
        "--result",
        "マージ済み",
        "--changed",
        "true",
        "--diff-path",
        str(ROOT / "tests/fixtures/reports/diff_msdata_20260601.md"),
        "--out",
        str(text),
    ]
    build_update_mail_body.main(args)
    plain_before = text.read_text(encoding="utf-8")
    assert build_update_mail_body.main([*args, "--html-out", str(html)]) == 0
    assert text.read_text(encoding="utf-8") == plain_before
    soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
    names = [node.get_text() for node in soup.select(".machine-name")]
    assert names.count("ガズアル") == 1
    assert "ネロ" in names
    card = soup.select(".machine")[names.index("ガズアル")]
    assert [node.get_text() for node in card.select(".level")] == ["LV2", "LV3", "LV4"]
    assert "18,000" in card.get_text()
    assert "20,000" in card.get_text()
    assert "+2,000" in card.get_text()
    assert [node.get_text() for node in soup.select(".stat-value")] == ["1", "14", "0"]
    assert "2026 / 06 / 01" in soup.get_text()


@pytest.mark.parametrize("same_path_text", [True, False])
@pytest.mark.parametrize("existing", [True, False])
def test_cli_rejects_same_plain_and_html_output_path_before_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    same_path_text: bool,
    existing: bool,
) -> None:
    output_dir = tmp_path / "output"
    out = output_dir / "body.txt"
    html_out = out if same_path_text else output_dir / "foo" / ".." / "body.txt"
    if existing:
        output_dir.mkdir()
        (output_dir / "foo").mkdir()
        out.write_text("既存内容\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        build_update_mail_body.main(
            [
                "--report-date",
                "20260930",
                "--result",
                "検証",
                "--changed",
                "false",
                "--out",
                str(out),
                "--html-out",
                str(html_out),
            ]
        )

    assert exc_info.value.code == 2
    assert (
        "--out と --html-out には異なるパスを指定してください。"
        in capsys.readouterr().err
    )
    if existing:
        assert out.read_text(encoding="utf-8") == "既存内容\n"
    else:
        assert not output_dir.exists()


def test_cli_rejects_hard_linked_plain_and_html_output_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "body.txt"
    html_out = tmp_path / "body.html"
    out.write_text("既存内容\n", encoding="utf-8")
    html_out.hardlink_to(out)

    with pytest.raises(SystemExit) as exc_info:
        build_update_mail_body.main(
            [
                "--report-date",
                "20260930",
                "--result",
                "検証",
                "--changed",
                "false",
                "--out",
                str(out),
                "--html-out",
                str(html_out),
            ]
        )

    assert exc_info.value.code == 2
    assert (
        "--out と --html-out には異なるパスを指定してください。"
        in capsys.readouterr().err
    )
    assert out.read_text(encoding="utf-8") == "既存内容\n"
    assert html_out.read_text(encoding="utf-8") == "既存内容\n"


def test_same_machine_addition_removal_and_changes_share_one_card() -> None:
    old = [
        {"MS名": "Ex-Sガンダム_LV1", "HP": 18000},
        {"MS名": "Ex-Sガンダム_LV2", "HP": 20000},
    ]
    new = [
        {"MS名": "Ex-Sガンダム_LV1", "HP": 19000},
        {"MS名": "Ex-Sガンダム_LV3", "HP": 22000, "コスト": 750},
    ]
    soup = BeautifulSoup(render_update_mail(_body(_report(old, new))), "html.parser")
    assert len(soup.select(".machine")) == 1
    card = soup.select_one(".machine")
    assert card.select_one(".machine-name").get_text() == "Ex-Sガンダム"
    assert {node.get_text() for node in card.select(".kind")} == {
        "レコード追加",
        "レコード削除",
        "変更",
    }
    assert {node.get_text() for node in card.select(".level")} == {"LV1", "LV2", "LV3"}
    assert "22,000" in card.get_text() and "750" in card.get_text()


def test_generated_escaped_cells_and_html_are_displayed_as_text() -> None:
    name = "試作|機\\_LV1"
    old = [{"MS名": name, "備考": "A|<script>alert(1)</script>", "HP": 100}]
    new = [{"MS名": name, "備考": 'B|<img src="x" onerror="bad">', "HP": 90}]
    soup = BeautifulSoup(render_update_mail(_body(_report(old, new))), "html.parser")
    assert soup.select_one(".machine-name").get_text() == "試作|機\\"
    assert "A|<script>alert(1)</script>" in soup.get_text()
    assert 'B|<img src=\\"x\\" onerror=\\"bad\\">' in soup.get_text()
    assert soup.find("script") is None
    assert soup.find("img") is None
    assert "-10" in soup.select_one(".delta").get_text()


def test_fullst_details_preserve_order_points_zero_null_and_missing() -> None:
    old = [
        {
            "MS名": "試作機_LV1",
            "fullst": [
                {"name": "A|装甲", "level": 1, "points": 0},
                {"name": "B", "level": 2},
            ],
        }
    ]
    new = [
        {
            "MS名": "試作機_LV1",
            "fullst": [
                {"name": "A|装甲", "level": 1, "points": 10},
                {"name": "C", "level": 2, "points": None},
            ],
        }
    ]
    soup = BeautifulSoup(render_update_mail(_body(_report(old, new))), "html.parser")
    details = soup.select(".machine .values")
    assert len(details) == 3
    assert "A|装甲" in details[0].get_text()
    assert "C" in details[1].get_text()
    assert "B" in details[2].get_text()
    assert "null" in details[1].get_text()
    assert "未設定" in details[2].get_text()
    point_rows = {
        row.th.get_text(): row.td.get_text() for row in details[0].select("tr")
    }
    assert point_rows["変更前 points"] == "0"
    assert point_rows["変更後 points"] == "10"


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [(60, 63.5, "+3.5"), (10.5, 9.25, "-1.25"), (0, 1000, "+1,000")],
)
def test_numeric_delta_is_exact(before: float, after: float, expected: str) -> None:
    report = _report(
        [{"MS名": "試作機_LV1", "旋回": before}],
        [{"MS名": "試作機_LV1", "旋回": after}],
    )
    soup = BeautifulSoup(render_update_mail(_body(report)), "html.parser")
    assert soup.select_one(".delta").get_text() == expected


def test_added_and_removed_fields_do_not_get_numeric_deltas() -> None:
    report = _report(
        [{"MS名": "試作機_LV1", "必要DP": 0}],
        [{"MS名": "試作機_LV1", "必要階級": "大尉01"}],
    )
    soup = BeautifulSoup(render_update_mail(_body(report)), "html.parser")
    assert soup.select(".delta") == []
    assert "大尉01" in soup.get_text()
    assert "未設定" in soup.get_text()
    assert "0" in soup.get_text()


def test_all_large_diff_levels_and_fields_are_retained() -> None:
    old = [{"MS名": f"試作機_LV{i}", "HP": 10000 + i} for i in range(200)]
    new = [{"MS名": f"試作機_LV{i}", "HP": 11000 + i} for i in range(200)]
    soup = BeautifulSoup(render_update_mail(_body(_report(old, new))), "html.parser")
    assert len(soup.select(".machine")) == 1
    assert len(soup.select(".level")) == 200
    assert len(soup.select(".change")) == 200
    assert soup.select(".level")[-1].get_text() == "LV199"
    assert soup.select(".machine .after")[-1].get_text() == "11,199"


def test_warnings_precede_cards_and_audit_metadata_is_kept() -> None:
    report = _report(
        [{"MS名": "試作機_LV1", "HP": 100}],
        [{"MS名": "試作機_LV1", "HP": 90}],
    )
    body = _body(report) + (
        "\n## 巻き戻りガード\n- protected_rollback: 1\n"
        "- numeric_decrease: 1\n- mixed_level_change: 2\n"
        "\n## official_overrides監査\n- source_changed: 3\n"
        "- review_due: 4\n- remove_due: 5\n- protected_by_override: 0\n"
    )
    html = render_update_mail(body)
    soup = BeautifulSoup(html, "html.parser")
    assert html.index('class="warning"') < html.index('class="machine"')
    assert len(soup.select(".warning li")) == 6
    assert "数値低下の確認候補: 1件" in soup.select_one(".warning").get_text()
    assert "review_due: 4" in soup.select_one(".footer").get_text()
    assert "protected_by_override: 0" in soup.select_one(".footer").get_text()


def test_no_change_mail_is_compact_but_keeps_run_and_audit_context() -> None:
    body = _body("", changed=False) + (
        "- candidate_count: 0\n- run_id: 123\n"
        "\n## 巻き戻りガード\n- protected_rollback: 0\n- numeric_decrease: 0\n"
        "\n## official_overrides監査\n- protected_by_override: 1\n- review_due: 0\n"
    )
    soup = BeautifulSoup(render_update_mail(body), "html.parser")
    assert (
        soup.select_one(".no-change").get_text() == "データの変更はありませんでした。"
    )
    assert soup.select(".machine, .stats, .warning") == []
    assert "run_id: 123" in soup.get_text()
    assert "candidate_count: 0" in soup.get_text()
    assert "protected_by_override: 1" in soup.get_text()


def test_expired_override_warning_is_shown_even_without_data_changes() -> None:
    body = _body("## official_overrides監査\n- review_due: 2\n", changed=False)
    soup = BeautifulSoup(render_update_mail(body), "html.parser")
    assert "確認期限到達: 2件" in soup.select_one(".warning").get_text()


def test_missing_summary_is_not_reported_as_zero_and_malformed_rows_are_kept() -> None:
    body = _body(
        "## 変更レコード一覧\n- 件数: 1\n### 試作機\n"
        "| LV | 項目 | 変更前 | 変更後 |\n| --- | --- | --- | --- |\n"
        "| LV1 | 新形式 | 123 | 456 | 追加列 |\n"
    )
    soup = BeautifulSoup(render_update_mail(body), "html.parser")
    assert [node.get_text() for node in soup.select(".stat-value")] == ["—", "—", "—"]
    assert "LV1 | 新形式 | 123 | 456 | 追加列" in soup.get_text()


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,bad", "http://[bad"]
)
def test_unsafe_or_invalid_links_remain_plain_text(url: str) -> None:
    body = _body("", changed=False) + f"- raw snapshot release: {url}\n詳細: {url}\n"
    soup = BeautifulSoup(render_update_mail(body), "html.parser")
    assert soup.select("a") == []
    assert url in soup.get_text()


def test_detail_and_release_links_are_rendered_once_and_escaped() -> None:
    body = _body("", changed=False) + (
        "- raw snapshot release: https://example.test/release?a=1&b=2\n"
        "\n## 巻き戻りガード\n- protected_rollback: 0\n"
        "詳細: https://example.test/report\n"
    )
    soup = BeautifulSoup(render_update_mail(body), "html.parser")
    links = soup.select("a")
    assert [(link.get_text(), link["href"]) for link in links] == [
        ("取得元・差分レポート", "https://example.test/release?a=1&b=2"),
        ("詳細レポート", "https://example.test/report"),
    ]
