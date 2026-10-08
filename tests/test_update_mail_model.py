from collections import Counter
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ms_data.audit.audit_official_overrides import render_markdown
from ms_data.audit.detect_msdata_rollbacks import render_report
from ms_data.audit.source_slots import empty_audit
from ms_data.audit.source_slots import render_markdown as render_source
from ms_data.reporting.build_update_mail_body import main
from ms_data.reporting.update_mail_html import render_update_mail
from ms_data.reporting.update_mail_model import build_mail_view, localize_mail_body


def _body(
    audit: str = "", *, changed: str = "false", result: str = "成功（差分なし）"
) -> str:
    return (
        f"- 実行日: 20261008\n- 結果: {result}\n- msData.json変更: {changed}\n\n{audit}"
    )


def _override_row(**values: str | int) -> dict:
    return {
        "MS名": "表示確認機_LV2",
        "field": "中スロット",
        "status": "protected_by_override",
        "before": 22,
        "raw": 12,
        "current": 22,
        "override": 22,
        "stale": 12,
        "lifecycle": "active",
        "review_after": "2026-10-19",
        "remove_after": "2026-10-26",
        "evidence_status": "mismatch",
        "url": "https://example.test/wiki",
        "attempted_at": "2026-10-08T09:00:00+00:00",
        "fetched_at": "2026-10-08T09:00:01+00:00",
        "http_status": 200,
        **values,
    }


def _build(
    tmp_path: Path,
    *,
    row: dict | None = None,
    extra: list[str] | None = None,
    report: str | None = None,
) -> tuple[str, BeautifulSoup]:
    row = row or _override_row()
    audit = tmp_path / "override.md"
    audit.write_text(
        (
            report
            if report is not None
            else render_markdown(
                [row], Counter({row["status"]: 1}), Counter({row["lifecycle"]: 1})
            )
        ),
        encoding="utf-8",
    )
    plain, html = tmp_path / "body.txt", tmp_path / "body.html"
    main(
        [
            "--report-date",
            "20261008",
            "--result",
            "成功（差分なし）",
            "--changed",
            "false",
            "--official-overrides-audit-path",
            str(audit),
            "--out",
            str(plain),
            "--html-out",
            str(html),
            *(extra or []),
        ]
    )
    return plain.read_text(encoding="utf-8"), BeautifulSoup(
        html.read_text(encoding="utf-8"), "html.parser"
    )


def test_audit_producer_details_reach_both_formats_and_inline_styles(
    tmp_path: Path,
) -> None:
    plain, soup = _build(tmp_path)
    assert soup.select(".warning") == []
    assert "補正値を維持した項目: 1項目" in soup.get_text()
    assert "表示確認機_LV2 / 中スロット" in plain
    pairs = {
        row.th.get_text(): row.td.get_text() for row in soup.select(".maintenance tr")
    }
    assert pairs["取得値"] == "12"
    assert pairs["採用値"] == pairs["登録補正値"] == "22"
    for key, value in pairs.items():
        assert f"- {key}: {value}" in plain
    assert "新たな更新停止の件数ではありません。" in plain
    assert (
        plain.index("公開データの変更なし")
        < plain.index("補正値を維持した項目")
        < plain.index("## 技術情報")
    )
    assert soup.select_one(".maintenance h3")["style"]
    assert "font-size:14px" in soup.select_one(".note")["style"]
    assert soup.select("script, img, link") == []


@pytest.mark.parametrize("lifecycle", ["review_due", "remove_due"])
def test_due_targets_show_dates_evidence_and_next_action(
    tmp_path: Path, lifecycle: str
) -> None:
    plain, soup = _build(
        tmp_path,
        row=_override_row(
            lifecycle=lifecycle,
            evidence_status="not_fetched",
            raw="",
            status="already_protected",
        ),
    )
    warning = soup.select_one(".warning").get_text()
    assert "表示確認機_LV2 / 中スロット" in warning
    assert "今回未取得" in warning
    assert "次の対応" in warning
    assert "2026-10-19" in warning and "2026-10-26" in warning
    assert (
        "確認完了数ではありません。" in warning
        if lifecycle == "review_due"
        else "撤去完了数ではありません。" in warning
    )
    assert "要確認の項目なし" not in plain


def test_planned_not_fetched_is_not_an_error_or_new_verified_maintenance(
    tmp_path: Path,
) -> None:
    plain, soup = _build(
        tmp_path,
        row=_override_row(
            status="already_protected", evidence_status="not_fetched", raw=""
        ),
    )
    assert soup.select(".warning") == []
    assert "今回の取得証拠なし・既存の補正値を維持: 1項目" in plain
    assert "補正値を維持した項目: 1項目" not in plain
    assert "取得状態: not_fetched" in plain


def test_cached_value_is_not_described_as_current_fetch(tmp_path: Path) -> None:
    plain, soup = _build(
        tmp_path,
        row=_override_row(
            status="already_protected",
            lifecycle="remove_due",
            evidence_status="cached_only",
        ),
    )
    assert (
        "監査記録の値（今回の取得値として未確認）"
        in soup.select_one(".warning").get_text()
    )
    assert "取得証拠: キャッシュのみ" in plain
    assert "取得証拠不足" in plain


@pytest.mark.parametrize("state", ["not_fetched", "cached_only"])
def test_source_changed_without_live_evidence_does_not_assert_upstream_changed(
    tmp_path: Path, state: str
) -> None:
    plain, soup = _build(
        tmp_path,
        row=_override_row(
            status="source_changed", evidence_status=state, current=23, raw=""
        ),
    )
    warning = soup.select_one(".warning").get_text()
    assert "採用値または取得値が登録補正の想定と異なります。" in warning
    assert "取得元が補正の想定と異なります。" not in plain
    assert "採用値: 23" in plain
    assert "次の対応" in warning


@pytest.mark.parametrize(
    "state",
    ["fetch_failed", "parse_failed", "value_missing", "not_parsed", "future_state"],
)
def test_bad_or_unknown_evidence_shows_target_and_action(
    tmp_path: Path, state: str
) -> None:
    plain, soup = _build(tmp_path, row=_override_row(evidence_status=state))
    assert "表示確認機_LV2" in soup.select_one(".warning").get_text()
    assert "再取得・解析結果を確認してください。" in plain
    assert "要確認の項目なし" not in plain


@pytest.mark.parametrize(
    "extra",
    [
        "- future_status: 0",
        "- source_changed: -1",
        "- source_changed: ?",
        "- review_due: 0\n- review_due: 1",
    ],
)
def test_unknown_malformed_or_duplicate_summaries_are_not_clean(extra: str) -> None:
    body = _body(
        "## official_overrides監査\n- review_due: 0\n- remove_due: 0\n" + extra
    )
    plain = localize_mail_body(body)
    assert "要確認の項目なし" not in plain
    assert extra.split(":")[0][2:] in plain


def test_inconsistent_counts_and_duplicate_evidence_do_not_infer_zero() -> None:
    row = _override_row()
    report = render_markdown(
        [row, row], Counter({"protected_by_override": 1}), Counter({"active": 1})
    )
    body = _body(
        report.replace("## サマリ", "## official_overrides監査").replace(
            "## 取得証拠", "## 登録補正 / 取得証拠"
        )
    )
    view = build_mail_view(body)
    assert "整合していません" in localize_mail_body(body)
    assert view.attention


@pytest.mark.parametrize(
    "action",
    [
        "retained_previous",
        "retained_previous_with_approved_correction",
        "previous_unverified_retained",
        "skipped_new_record",
    ],
)
def test_partial_hold_actions_preserve_reason_and_never_invent_a_missing_value(
    tmp_path: Path, action: str
) -> None:
    audit = empty_audit()
    audit.update(status="partial_hold", held_record_count=1)
    audit["fallback_corrected_record_count"] = int(
        action == "retained_previous_with_approved_correction"
    )
    audit["previous_unverified_count"] = int(action == "previous_unverified_retained")
    audit["findings"] = [
        {
            "MS名": "表示確認機_LV2",
            "level": 2,
            "field": "中スロット",
            "observed": 12,
            "comparison": {"表示確認機_LV1": 20, "表示確認機_LV3": 24},
            "previous": None if action == "skipped_new_record" else 22,
            "adopted": None if action == "skipped_new_record" else 22,
            "action": action,
            "wiki_url": "https://example.test/wiki",
            "reason": "LV内点のスロット谷かつ下位LVより合計低下",
        }
    ]
    path, plain, html = (
        tmp_path / "source.md",
        tmp_path / "body.txt",
        tmp_path / "body.html",
    )
    path.write_text(render_source(audit), encoding="utf-8")
    main(
        [
            "--report-date",
            "20261008",
            "--result",
            "部分保留エラー（対応要）",
            "--changed",
            "false",
            "--source-slot-audit-path",
            str(path),
            "--out",
            str(plain),
            "--html-out",
            str(html),
        ]
    )
    text = plain.read_text(encoding="utf-8")
    soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
    warning = soup.select_one(".warning").get_text()
    assert "表示確認機_LV2 / 中スロット" in warning
    assert "機体＋LV全体" in warning and "次の対応" in warning
    assert audit["findings"][0]["reason"] in text
    if action == "skipped_new_record":
        assert "新規レコードの追加を保留" in text
        assert "- 前値: 監査記録なし" in text
        assert "- 採用値: 監査記録なし" in text
    assert "official_overrides監査: 件数" not in text


def test_explicit_missing_audit_is_unknown_but_optional_omission_is_not_failure(
    tmp_path: Path,
) -> None:
    plain, html = tmp_path / "body.txt", tmp_path / "body.html"
    args = [
        "--report-date",
        "20261008",
        "--result",
        "成功（差分なし）",
        "--changed",
        "false",
        "--out",
        str(plain),
        "--html-out",
        str(html),
    ]
    main(args)
    assert (
        BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser").select(
            ".warning"
        )
        == []
    )
    main([*args, "--rollback-guard-path", str(tmp_path / "missing.md")])
    for text in (
        plain.read_text(encoding="utf-8"),
        BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser").get_text(),
    ):
        assert "未取得" in text
        assert "要確認の項目なし" not in text
        assert "0項目" not in text


def test_malformed_audit_row_and_unknown_global_stop_are_preserved() -> None:
    body = _body(
        "## ガード / ブロック対象\n| MS名 | 項目 |\n| --- | --- |\n| 表示確認機_LV2 | HP | 余分な値 |\n\n## 既存の全体安全停止\n公開レコードのスキーマ不正\n"
    )
    assert "表示確認機_LV2 | HP | 余分な値" in localize_mail_body(body)
    assert (
        "公開レコードのスキーマ不正"
        in BeautifulSoup(render_update_mail(body), "html.parser").get_text()
    )


def test_pending_partial_update_has_same_title_in_both_formats() -> None:
    body = _body(changed="true", result="部分保留エラー（対応要）")
    assert "更新候補に差分あり" in localize_mail_body(body)
    assert (
        BeautifulSoup(render_update_mail(body), "html.parser").h1.get_text()
        == "更新候補に差分あり"
    )


@pytest.mark.parametrize(
    "case",
    [
        "partial_hold_without_count",
        "approved_without_count",
        "missing_status",
        "missing_count",
        "missing_targets",
    ],
)
def test_source_summary_missing_or_inconsistent_is_not_clean(case: str) -> None:
    audit = empty_audit()
    if case == "partial_hold_without_count":
        audit["status"] = "partial_hold"
    elif case == "approved_without_count":
        audit["status"] = "approved_correction"
    elif case == "missing_targets":
        audit.update(status="partial_hold", held_record_count=1)
    report = render_source(audit)
    if case == "missing_status":
        report = report.replace("- status: ok\n", "")
    elif case == "missing_count":
        report = report.replace("- fallback_corrected_record_count: 0\n", "")
    body = _body(report)
    plain = localize_mail_body(body)
    warning = BeautifulSoup(render_update_mail(body), "html.parser").select_one(
        ".warning"
    )
    assert warning is not None
    assert "監査レポートを確認してください。" in warning.get_text()
    assert "要確認の項目なし" not in plain


@pytest.mark.parametrize("action", [None, "approved_override", "retained_previous"])
def test_source_summary_matches_unique_machine_levels(action: str | None) -> None:
    audit = empty_audit()
    if action:
        approved = action == "approved_override"
        audit.update(
            status="approved_correction" if approved else "partial_hold",
            held_record_count=int(not approved),
            approved_record_count=int(approved),
        )
        audit["findings"] = [
            {
                "MS名": "表示確認機_LV2",
                "level": 2,
                "field": field,
                "observed": 12,
                "comparison": 20,
                "previous": 22,
                "adopted": 22,
                "action": action,
                "wiki_url": "https://example.test/wiki",
                "reason": "表示確認用の異常候補",
            }
            for field in ("中スロット", "遠スロット")
        ]
    body = _body(render_source(audit))
    plain = localize_mail_body(body)
    assert "整合していません" not in plain
    assert "件数を確認できません" not in plain
    if action != "retained_previous":
        assert not build_mail_view(body).attention
    if action:
        # 同じ機体＋LVの複数項目をレコード2件として数えない。
        audit["approved_record_count" if approved else "held_record_count"] = 2
        assert "整合していません" in localize_mail_body(_body(render_source(audit)))


def test_global_safety_stop_is_not_described_as_partial_hold() -> None:
    audit = empty_audit()
    audit.update(status="global_validation_error", global_errors=["スキーマ不正"])
    audit["findings"] = [
        {
            "MS名": "表示確認機_LV2",
            "level": 2,
            "field": "中スロット",
            "observed": 12,
            "comparison": 20,
            "action": "global_safety_stop_not_quarantined",
            "wiki_url": "https://example.test/wiki",
            "reason": "全体停止の確認用",
        }
    ]
    body = _body(render_source(audit))
    plain = localize_mail_body(body)
    assert "既存の全体安全停止（部分保留処理なし）" in plain
    assert "他の正常候補は通常レビューを継続" not in plain
    assert "要確認の項目なし" not in plain


@pytest.mark.parametrize(
    "status,lifecycle,heading,mutation",
    [
        ("protected_by_override", "active", "適用中", "missing"),
        ("protected_by_override", "active", "適用中", "duplicate"),
        ("protected_by_override", "active", "適用中", "wrong_status"),
        ("upstream_current", "active", "撤去候補", "missing"),
        ("source_changed", "active", "要確認", "missing"),
        ("protected_by_override", "review_due", "期限確認", "missing"),
        ("protected_by_override", "remove_due", "期限確認", "missing"),
    ],
)
def test_state_specific_missing_duplicate_or_mislabeled_details_warn(
    tmp_path: Path, status: str, lifecycle: str, heading: str, mutation: str
) -> None:
    rows = [
        _override_row(status=status, lifecycle=lifecycle),
        _override_row(MS名="表示確認機_LV3", status=status, lifecycle=lifecycle),
    ]
    report = render_markdown(rows, Counter({status: 2}), Counter({lifecycle: 2}))
    section = report.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    if mutation == "missing":
        altered = "\n".join(
            line for line in section.splitlines() if "表示確認機_LV3" not in line
        )
    elif mutation == "duplicate":
        altered = section.replace("表示確認機_LV3", "表示確認機_LV2")
    else:
        altered = section.replace("protected_by_override", "unknown_status", 1)
    plain, soup = _build(tmp_path, report=report.replace(section, altered, 1))
    warning = soup.select_one(".warning").get_text()
    assert f"登録補正 / {heading}: 明細を確認" in warning
    assert "状態別の件数・対象明細が整合していません。" in plain
    assert "要確認の項目なし" not in plain


@pytest.mark.parametrize("kind", ["mixed", "truncated", "missing"])
def test_guard_detail_counts_use_groups_and_preserve_documented_truncation(
    tmp_path: Path, kind: str
) -> None:
    rows = [
        {
            "MS名": f"表示確認機_LV{level}",
            "field": "HP",
            "type": "numeric_decrease",
            "old": 20000,
            "new": 18000,
        }
        for level in range(1, 102 if kind == "truncated" else 3)
    ]
    report = render_report(
        protected_rollbacks=[],
        numeric_decreases=[] if kind == "mixed" else rows,
        mixed_level_changes=(
            [{"base": "表示確認機", "field": "HP", "rows": rows}]
            if kind == "mixed"
            else []
        ),
    )
    if kind == "missing":
        report = "\n".join(
            line for line in report.splitlines() if "表示確認機_LV2" not in line
        )
    path = tmp_path / "guard.md"
    path.write_text(report, encoding="utf-8")
    plain, _ = _build(tmp_path, extra=["--rollback-guard-path", str(path)])
    if kind == "missing":
        assert "状態別の件数・対象明細が整合していません。" in plain
    else:
        assert "状態別の件数・対象明細が整合していません。" not in plain
    if kind == "mixed":
        assert "LV間で増減が混在する候補: 1組" in plain
    elif kind == "truncated":
        assert "- 省略: 1 件" in plain


def test_unknown_source_action_is_not_inferred_as_partial_hold() -> None:
    audit = empty_audit()
    audit["findings"] = [
        {
            "MS名": "表示確認機_LV2",
            "level": 2,
            "field": "中スロット",
            "observed": 12,
            "comparison": 20,
            "action": "unknown_action",
            "wiki_url": "https://example.test/wiki",
            "reason": "未知処置の確認用",
        }
    ]
    plain = localize_mail_body(_body(render_source(audit)))
    assert "対象名または処置が読み取れない明細があります。" in plain
    assert "unknown_action" in plain
    assert "他の正常候補は通常レビューを継続" not in plain
    assert "要確認の項目なし" not in plain
