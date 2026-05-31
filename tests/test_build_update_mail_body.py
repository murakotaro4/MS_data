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
