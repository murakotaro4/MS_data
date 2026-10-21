from pathlib import Path

import pytest

from ms_data.gh.notify_review_stop import (
    CONNECTOR_SETTINGS_URL,
    MANUAL_RECOVERY_HINT,
    MAX_FINDING_TITLE_CHARS,
    build_mail_body,
    build_notice,
    build_subject,
    finding_cards,
    notify_review_stop,
    reason_label,
    summarize_finding,
)
from ms_data.notify.notice_html import render_notice_html

# PR #339 の停止メールに生で混入した Codex コメント本文（2026-10-20）
CODEX_BODY_339 = (
    "**<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)"
    "</sub></sub> 中スロット値を取得元の29に戻す**\n\n"
    "この更新を取り込むと、`ガルバルディβ高機動型［T仕様］_LV2` の中スロットが"
    "誤った20として配布されます。レコードの [`wiki_url` にあるパーツスロット表]"
    "(https://w.atwiki.jp/battle-operation2/pages/4397.html) はLV2を29と記載しています。\n\n"
    "AGENTS.md reference: [AGENTS.md:L7-L7](https://github.com/x/y/blob/z/AGENTS.md#L7-L7)\n\n"
    "Useful? React with 👍 / 👎.\n\n<!-- codex-review"
)
GITHUB_MARKUP = ("Badge", "<sub>", "shields.io", "Useful? React", "<!--", "**")


def test_reason_label_mapping():
    assert reason_label("findings") == "codex_findings"
    assert reason_label("no_response") == "codex_no_response"
    assert reason_label("disconnected") == "codex_disconnected"


def test_build_subject_format():
    assert (
        build_subject(stop_reason="findings", pr_number=42)
        == "【要対応】msData 自動マージ停止 PR #42（Codex指摘）"
    )
    assert (
        build_subject(stop_reason="no_response", pr_number=7)
        == "【要対応】msData 自動マージ停止 PR #7（Codex応答なし）"
    )
    assert (
        build_subject(stop_reason="disconnected", pr_number=9)
        == "【要対応】msData 自動マージ停止 PR #9（Codex連携切れ）"
    )


def test_summarize_finding_drops_github_markup():
    assert summarize_finding(CODEX_BODY_339) == ("P1", "中スロット値を取得元の29に戻す")


def test_summarize_finding_falls_back_to_first_plain_line_and_truncates():
    priority, title = summarize_finding("\x00<sub></sub>\n`x` が " + "長" * 200)
    assert priority == ""
    assert title.startswith("x が 長")
    assert len(title) == MAX_FINDING_TITLE_CHARS
    assert title.endswith("…")
    assert summarize_finding("29 < 30 のまま") == ("", "29 < 30 のまま")
    assert summarize_finding("")[1].startswith("（要点を読み取れません")


def test_finding_cards_keep_location_link_and_limit_to_20():
    findings = [
        {"path": f"file_{i}.py", "line": i, "body": f"**finding {i}**"}
        for i in range(25)
    ]
    findings[0]["url"] = "https://github.com/x/y/pull/1#discussion_r1"
    findings[1]["url"] = "javascript:alert(1)"
    cards = finding_cards(findings)

    assert len(cards) == 21
    assert cards[0].title == "finding 0"
    assert cards[0].lines == ["file_0.py:0"]
    assert cards[0].links == [
        ("指摘コメント", "https://github.com/x/y/pull/1#discussion_r1")
    ]
    assert cards[1].links == []
    assert cards[-1].title == "ほか 5 件"
    assert finding_cards([{"path": "x.py", "line": None, "body": "n"}])[0].lines == [
        "x.py"
    ]


def test_build_mail_body_findings_shows_summary_only():
    body = build_mail_body(
        stop_reason="findings",
        pr_number=339,
        pr_url="https://example.invalid/pr/1",
        report_date="20260724",
        run_url="https://example.invalid/run/9",
        findings=[{"path": "msData.json", "line": 3, "body": CODEX_BODY_339}],
    )

    assert "ファイル指摘が 1 件" in body
    assert "次の対応: PR の指摘を確認" in body
    assert "- PR #339: https://example.invalid/pr/1" in body
    assert "20260724" in body
    assert "https://example.invalid/run/9" in body
    assert "- [P1] 中スロット値を取得元の29に戻す" in body
    assert "  msData.json:3" in body
    assert "誤った20として配布" not in body
    for markup in GITHUB_MARKUP:
        assert markup not in body
    assert MANUAL_RECOVERY_HINT not in body


def test_build_mail_body_no_response_puts_recovery_first():
    body = build_mail_body(
        stop_reason="no_response",
        pr_url="https://example.invalid/pr/2",
        report_date="20260724",
        run_url="https://example.invalid/run/10",
    )

    lines = body.splitlines()
    assert "レビュー応答が確認できなかった" in lines[1]
    assert lines[2] == f"次の対応: {MANUAL_RECOVERY_HINT}"
    assert "@codex review" in body
    assert "09:00 JST" in body
    assert "指摘" not in body
    assert CONNECTOR_SETTINGS_URL not in body


def test_build_mail_body_disconnected_links_connector_settings():
    body = build_mail_body(
        stop_reason="disconnected",
        pr_url="https://example.invalid/pr/3",
        report_date="20260724",
        run_url="https://example.invalid/run/11",
    )

    assert "コネクタ連携が切れている" in body
    assert body.splitlines()[2].startswith("次の対応: Codex のコネクタ設定を確認")
    assert CONNECTOR_SETTINGS_URL in body
    assert MANUAL_RECOVERY_HINT in body


def test_stop_notice_html_uses_card_and_omits_github_markup():
    html = render_notice_html(
        build_notice(
            stop_reason="findings",
            pr_number=339,
            pr_url="https://github.com/x/y/pull/339",
            report_date="20261020",
            run_url="https://github.com/x/y/actions/runs/1",
            findings=[
                {
                    "path": "msData.json",
                    "line": 55564,
                    "url": "https://github.com/x/y/pull/339#discussion_r1",
                    "body": CODEX_BODY_339,
                }
            ],
        )
    )
    body = html.split("<body", 1)[1]
    assert "2026 / 10 / 20" in body
    assert "[P1] 中スロット値を取得元の29に戻す" in body
    assert 'href="https://github.com/x/y/pull/339#discussion_r1"' in body
    assert 'class="audit-card"' in body
    assert "style=" in body
    for markup in GITHUB_MARKUP:
        assert markup not in body


def test_notify_review_stop_sends_text_and_html(tmp_path: Path):
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(
        '[{"path": "x.py", "line": 1, "body": "bad"}]',
        encoding="utf-8",
    )
    captured: list[tuple[str, str, str]] = []

    rc = notify_review_stop(
        stop_reason="findings",
        pr_number=15,
        pr_url="https://example.invalid/pr/15",
        report_date="20260724",
        run_url="https://example.invalid/run/15",
        findings_json=findings_path,
        mail_sender=lambda *args: captured.append(args),
    )

    assert rc == 0
    assert len(captured) == 1
    subject, body, html = captured[0]
    assert subject == "【要対応】msData 自動マージ停止 PR #15（Codex指摘）"
    assert "- bad" in body
    assert "  x.py:1" in body
    assert "<html" in html and "bad" in html


@pytest.mark.parametrize("stop_reason", ["no_response", "disconnected"])
def test_notify_review_stop_works_without_findings_json(stop_reason: str):
    captured: list[tuple[str, str, str]] = []

    rc = notify_review_stop(
        stop_reason=stop_reason,
        pr_number=3,
        pr_url="https://example.invalid/pr/3",
        report_date="20260724",
        run_url="https://example.invalid/run/3",
        mail_sender=lambda *args: captured.append(args),
    )

    assert rc == 0
    assert len(captured) == 1
    subject, body, _ = captured[0]
    assert subject.startswith("【要対応】msData 自動マージ停止 PR #3（Codex")
    assert "https://example.invalid/pr/3" in body
    assert MANUAL_RECOVERY_HINT in body


def test_notify_review_stop_returns_nonzero_on_mail_failure():
    def failing_sender(*_: str) -> None:
        raise RuntimeError("smtp failed")

    rc = notify_review_stop(
        stop_reason="no_response",
        pr_number=1,
        pr_url="https://example.invalid/pr/1",
        report_date="20260724",
        run_url="https://example.invalid/run/1",
        mail_sender=failing_sender,
    )

    assert rc == 1
