from pathlib import Path

from ms_data.reporting import build_update_mail_body

ROOT = Path(__file__).resolve().parents[1]


def test_build_update_mail_body_includes_report_summaries(tmp_path):
    diff = tmp_path / "diff.md"
    rollback = tmp_path / "rollback.md"
    overrides = tmp_path / "overrides.md"
    out = tmp_path / "mail.txt"
    diff.write_text(
        "## サマリ\n- レコード数: 1516 → 1517 | +1 -0 ~2\n", encoding="utf-8"
    )
    rollback.write_text(
        "## サマリ\n- protected_rollback: 0\n- numeric_decrease: 1\n"
        "- mixed_level_change: 2\n",
        encoding="utf-8",
    )
    overrides.write_text(
        "## サマリ\n- protected_by_override: 3\n- upstream_current: 4\n"
        "- source_changed: 2\n- review_due: 1\n- remove_due: 5\n",
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
    assert "結果: マージ済み" in text
    assert "公開データの変更あり" in text
    assert "データ更新元の実行ID（source_run_id）: 26709410162" in text
    assert "- レコード数: 1516 → 1517 | +1 -0 ~2" in text
    assert "protected_rollback" not in text
    assert "数値低下の確認候補: 1項目" in text
    assert "数値低下だけでは誤りと確定できません。" in text
    assert "LV間で増減が混在する候補: 2組" in text
    assert "機体＋項目の組数" in text
    assert "補正値を維持した項目: 3項目" in text
    assert "取得元が補正値と一致した項目: 4項目" in text
    assert "補正の想定と異なる項目: 2項目" in text
    assert "登録補正の再確認期限到達: 1項目" in text
    assert "撤去判断期限の対象を除く" in text
    assert "登録補正の撤去判断期限到達: 5項目" in text
    assert "撤去完了数ではありません。" in text


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


def test_build_update_mail_body_keeps_all_large_diff_details(tmp_path):
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
    assert "| LV199 | HP | 10199 | 11199 |" in text
    assert "変更内容が多いため" not in text


def test_build_update_mail_body_matches_20260601_changed_report_contract(tmp_path):
    out = tmp_path / "mail.txt"

    rc = build_update_mail_body.main(
        [
            "--report-date",
            "20260601",
            "--result",
            "マージ済み",
            "--changed",
            "true",
            "--source-run-id",
            "26750333965",
            "--release-url",
            "https://example.test/release",
            "--diff-path",
            str(ROOT / "tests/fixtures/reports/diff_msdata_20260601.md"),
            "--rollback-guard-path",
            str(ROOT / "tests/fixtures/reports/rollback_guard_20260601.md"),
            "--official-overrides-audit-path",
            str(ROOT / "tests/fixtures/reports/official_overrides_audit_20260601.md"),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "## 差分サマリ" in text
    assert "- レコード数: 1644 → 1645 | +1 -0 ~14" in text
    assert "## 変更内容" in text
    assert "## 追加レコード一覧" in text
    assert "### ネロ" in text
    assert "| LV3 | 汎用 | 550 | 22000 |" in text
    assert "## 削除レコード一覧" not in text
    assert "## 変更レコード一覧" in text
    assert "### ガズアル" in text
    assert "| LV2 | HP | 18000 | 20000 |" in text
    assert "## 補正値の維持と期限" in text


def test_build_update_mail_body_keeps_no_change_mail_operational_context(tmp_path):
    rollback = tmp_path / "rollback.md"
    overrides = tmp_path / "overrides.md"
    out = tmp_path / "mail.txt"
    rollback.write_text(
        "## サマリ\n- protected_rollback: 0\n- numeric_decrease: 0\n- mixed_level_change: 0\n",
        encoding="utf-8",
    )
    overrides.write_text(
        "## サマリ\n- 対象値: 0\n- review_due: 0\n- remove_due: 0\n",
        encoding="utf-8",
    )

    rc = build_update_mail_body.main(
        [
            "--report-date",
            "20260601",
            "--result",
            "成功（差分なし）",
            "--changed",
            "false",
            "--candidate-count",
            "0",
            "--fast-path",
            "true",
            "--age-coverage",
            "1.0",
            "--fallback-reason",
            "none",
            "--run-id",
            "26700000000",
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
    assert "結果: 成功（差分なし）" in text
    assert "公開データの変更なし" in text
    assert "再取得候補: 0ページ" in text
    assert "高速選定: 有効" in text
    assert "一覧の更新経過時間読み取り率: 100%（1.0）" in text
    assert "全件取得" not in text
    assert "今回の実行ID（run_id）: 26700000000" in text
    assert "## 変更内容" not in text
    assert "## 補正値の維持と期限" in text
