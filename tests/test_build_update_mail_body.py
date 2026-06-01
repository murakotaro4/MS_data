from scripts import build_update_mail_body


def test_build_update_mail_body_includes_report_summaries(tmp_path):
    diff = tmp_path / "diff.md"
    rollback = tmp_path / "rollback.md"
    overrides = tmp_path / "overrides.md"
    out = tmp_path / "mail.txt"
    diff.write_text(
        "## サマリ\n- レコード数: 1516 → 1517 | +1 -0 ~2\n", encoding="utf-8"
    )
    rollback.write_text(
        "## サマリ\n- protected_rollback: 0\n- numeric_decrease: 1\n",
        encoding="utf-8",
    )
    overrides.write_text(
        "## サマリ\n- protected_by_override: 3\n- review_due: 1\n",
        encoding="utf-8",
    )

    rc = build_update_mail_body.main(
        [
            "--report-date",
            "20260531",
            "--result",
            "マージ済み",
            "--changed",
            "true",
            "--source-run-id",
            "26709410162",
            "--release-url",
            "https://example.test/release",
            "--diff-path",
            str(diff),
            "--rollback-guard-path",
            str(rollback),
            "--official-overrides-audit-path",
            str(overrides),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "- 結果: マージ済み" in text
    assert "- msData.json変更: true" in text
    assert "- source_run_id: 26709410162" in text
    assert "- レコード数: 1516 → 1517 | +1 -0 ~2" in text
    assert "- protected_rollback: 0" in text
    assert "- review_due: 1" in text


def test_build_update_mail_body_includes_diff_record_details(tmp_path):
    diff = tmp_path / "diff.md"
    out = tmp_path / "mail.txt"
    diff.write_text(
        "\n".join(
            [
                "## サマリ",
                "- レコード数: 1644 → 1645 | +1 -0 ~1",
                "",
                "## 追加レコード一覧",
                "",
                "- 件数: 1",
                "",
                "### ネロ",
                "| LV | 属性 | コスト | HP |",
                "| --- | --- | --- | --- |",
                "| LV3 | 汎用 | 550 | 22000 |",
                "",
                "## 削除レコード一覧",
                "",
                "- 件数: 0",
                "",
                "該当なし",
                "",
                "## 変更レコード一覧",
                "",
                "- 件数: 1",
                "",
                "### ガズアル",
                "| LV | 項目 | 変更前 | 変更後 |",
                "| --- | --- | --- | --- |",
                "| LV2 | HP | 18000 | 20000 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = build_update_mail_body.main(
        [
            "--report-date",
            "20260601",
            "--result",
            "マージ済み",
            "--changed",
            "true",
            "--diff-path",
            str(diff),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "## 変更内容" in text
    assert "## 追加レコード一覧" in text
    assert "### ネロ" in text
    assert "| LV3 | 汎用 | 550 | 22000 |" in text
    assert "## 削除レコード一覧" not in text
    assert "## 変更レコード一覧" in text
    assert "### ガズアル" in text
    assert "| LV2 | HP | 18000 | 20000 |" in text


def test_build_update_mail_body_truncates_large_diff_details(tmp_path):
    diff = tmp_path / "diff.md"
    out = tmp_path / "mail.txt"
    rows = [f"| LV{i} | HP | {10000 + i} | {11000 + i} |" for i in range(200)]
    diff.write_text(
        "\n".join(
            [
                "## サマリ",
                "- レコード数: 100 → 100 | +0 -0 ~200",
                "",
                "## 変更レコード一覧",
                "",
                "- 件数: 200",
                "",
                "### 大量更新",
                "| LV | 項目 | 変更前 | 変更後 |",
                "| --- | --- | --- | --- |",
                *rows,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = build_update_mail_body.main(
        [
            "--report-date",
            "20260601",
            "--result",
            "マージ済み",
            "--changed",
            "true",
            "--diff-path",
            str(diff),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "| LV0 | HP | 10000 | 11000 |" in text
    assert "| LV199 | HP | 10199 | 11199 |" not in text
    assert "変更内容が多いため先頭 160 行のみ表示しています" in text
