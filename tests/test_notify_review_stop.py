from pathlib import Path

import pytest

from ms_data.gh.notify_review_stop import (
    CONNECTOR_SETTINGS_URL,
    MANUAL_RECOVERY_HINT,
    MAX_FINDING_BODY_CHARS,
    build_mail_body,
    build_subject,
    format_findings_section,
    notify_review_stop,
    reason_label,
    sanitize_finding_body,
)


def test_reason_label_mapping():
    assert reason_label("findings") == "codex_findings"
    assert reason_label("no_response") == "codex_no_response"
    assert reason_label("disconnected") == "codex_disconnected"


def test_build_subject_format():
    assert (
        build_subject(stop_reason="findings", pr_number=42)
        == "msData 自動マージ停止 (codex_findings) PR #42"
    )
    assert (
        build_subject(stop_reason="no_response", pr_number=7)
        == "msData 自動マージ停止 (codex_no_response) PR #7"
    )
    assert (
        build_subject(stop_reason="disconnected", pr_number=9)
        == "msData 自動マージ停止 (codex_disconnected) PR #9"
    )


def test_sanitize_finding_body_truncates_and_strips_control_chars():
    raw = "a" * (MAX_FINDING_BODY_CHARS + 10)
    assert len(sanitize_finding_body(raw)) == MAX_FINDING_BODY_CHARS

    with_controls = "ok\nkeep\there\x00\x01\x07gone\r"
    cleaned = sanitize_finding_body(with_controls)
    assert "\n" in cleaned
    assert "\t" in cleaned
    assert "\x00" not in cleaned
    assert "\x01" not in cleaned
    assert "\x07" not in cleaned
    assert "\r" not in cleaned
    assert "ok" in cleaned
    assert "gone" in cleaned


def test_format_findings_section_limits_to_20_and_reports_remainder():
    findings = [
        {"path": f"file_{i}.py", "line": i, "body": f"finding {i}"}
        for i in range(25)
    ]
    lines = format_findings_section(findings)

    assert lines[0] == "指摘一覧:"
    assert sum(1 for line in lines if line.startswith("- ")) == 20
    assert "ほか 5 件" in lines
    assert "- file_0.py:0" in lines
    assert "- file_19.py:19" in lines
    assert "- file_20.py:20" not in lines


def test_format_findings_section_omits_null_line():
    lines = format_findings_section(
        [{"path": "ms_data/gh/x.py", "line": None, "body": "note"}]
    )
    assert "- ms_data/gh/x.py" in lines
    assert "  note" in lines


def test_build_mail_body_findings_includes_common_and_list():
    body = build_mail_body(
        stop_reason="findings",
        pr_url="https://example.invalid/pr/1",
        report_date="20260724",
        run_url="https://example.invalid/run/9",
        findings=[
            {"path": "a.py", "line": 3, "body": "問題あり"},
        ],
    )

    assert "ファイル指摘" in body
    assert "https://example.invalid/pr/1" in body
    assert "20260724" in body
    assert "https://example.invalid/run/9" in body
    assert "- a.py:3" in body
    assert "問題あり" in body
    assert MANUAL_RECOVERY_HINT not in body


def test_build_mail_body_no_response_without_findings_json():
    body = build_mail_body(
        stop_reason="no_response",
        pr_url="https://example.invalid/pr/2",
        report_date="20260724",
        run_url="https://example.invalid/run/10",
    )

    assert "レビュー応答が確認できなかった" in body
    assert MANUAL_RECOVERY_HINT in body
    assert "@codex review" in body
    assert "09:00 JST" in body
    assert "指摘一覧:" not in body
    assert CONNECTOR_SETTINGS_URL not in body


def test_build_mail_body_disconnected_without_findings_json():
    body = build_mail_body(
        stop_reason="disconnected",
        pr_url="https://example.invalid/pr/3",
        report_date="20260724",
        run_url="https://example.invalid/run/11",
    )

    assert "コネクタ連携が切れている" in body
    assert CONNECTOR_SETTINGS_URL in body
    assert MANUAL_RECOVERY_HINT in body
    assert "指摘一覧:" not in body


def test_notify_review_stop_calls_mail_sender_with_subject_and_body(tmp_path: Path):
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(
        '[{"path": "x.py", "line": 1, "body": "bad"}]',
        encoding="utf-8",
    )
    captured: list[tuple[str, str]] = []

    def mail_sender(subject: str, body: str) -> None:
        captured.append((subject, body))

    rc = notify_review_stop(
        stop_reason="findings",
        pr_number=15,
        pr_url="https://example.invalid/pr/15",
        report_date="20260724",
        run_url="https://example.invalid/run/15",
        findings_json=findings_path,
        mail_sender=mail_sender,
    )

    assert rc == 0
    assert len(captured) == 1
    subject, body = captured[0]
    assert subject == "msData 自動マージ停止 (codex_findings) PR #15"
    assert "- x.py:1" in body
    assert "bad" in body


@pytest.mark.parametrize("stop_reason", ["no_response", "disconnected"])
def test_notify_review_stop_works_without_findings_json(stop_reason: str):
    captured: list[tuple[str, str]] = []

    rc = notify_review_stop(
        stop_reason=stop_reason,
        pr_number=3,
        pr_url="https://example.invalid/pr/3",
        report_date="20260724",
        run_url="https://example.invalid/run/3",
        mail_sender=lambda subject, body: captured.append((subject, body)),
    )

    assert rc == 0
    assert len(captured) == 1
    subject, body = captured[0]
    assert f"({reason_label(stop_reason)})" in subject
    assert "https://example.invalid/pr/3" in body
    assert MANUAL_RECOVERY_HINT in body


def test_notify_review_stop_returns_nonzero_on_mail_failure():
    def failing_sender(subject: str, body: str) -> None:
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
