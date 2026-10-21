from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ms_data.gh.notify_failure import notify_failure
from ms_data.notify import send_gmail
from ms_data.notify.subjects import MAX_DETAIL_CHARS, format_subject
from ms_data.reporting import build_update_mail_body
from ms_data.reporting.update_mail_model import build_mail_view, mail_subject

from workflow_contract import step_block, workflow_text

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mail"


def test_format_subject_uses_status_tag_and_full_width_parentheses():
    assert (
        format_subject("変更なし", "定期チェック", label="20261021")
        == "【変更なし】msData 定期チェック 20261021"
    )
    assert (
        format_subject("失敗", "パイプライン", detail="auto review merge")
        == "【失敗】msData パイプライン（auto review merge）"
    )


def test_format_subject_rejects_unknown_status_and_shortens_detail():
    with pytest.raises(ValueError):
        format_subject("注意", "定期チェック")
    subject = format_subject("要対応", "定期チェック", detail="あ" * 100)
    detail = subject[subject.index("（") + 1 : -1]
    assert len(detail) == MAX_DETAIL_CHARS
    assert detail.endswith("…")


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("no-change", "【変更なし】msData 定期チェック 20261008"),
        ("changed", "【変更あり】msData 更新反映 20261008（変更1）"),
        ("actual-20261009", "【変更あり】msData 更新反映 20261009（追加1・変更6）"),
        (
            "partial-hold",
            "【要対応】msData 部分保留 20261008（LV単位の部分保留 1レコード）",
        ),
        (
            "audit-due",
            "【要対応】msData 定期チェック 20261008"
            "（登録補正の撤去判断期限到達 1項目 ほか1種）",
        ),
        (
            "audit-missing",
            "【要対応】msData 定期チェック 20261008（巻き戻りガード 監査情報が不足）",
        ),
    ],
)
def test_mail_subject_follows_body_action(fixture: str, expected: str):
    view = build_mail_view((FIXTURES / f"{fixture}.md").read_text(encoding="utf-8"))
    assert mail_subject(view) == expected
    # 件名の要対応と本文冒頭の対応要否は同じ判定から作る。
    assert expected.startswith("【要対応】") == view.action.startswith("対応が必要")


def test_build_update_mail_body_writes_subject_file(tmp_path: Path):
    subject_path = tmp_path / "subject.txt"
    assert (
        build_update_mail_body.main(
            [
                "--report-date",
                "20261021",
                "--result",
                "成功（差分なし）",
                "--changed",
                "false",
                "--out",
                str(tmp_path / "mail.txt"),
                "--subject-out",
                str(subject_path),
            ]
        )
        == 0
    )
    # 監査未添付は対応要否を判定できないため、本文と同じく要対応にする。
    assert subject_path.read_text(encoding="utf-8").startswith(
        "【要対応】msData 定期チェック 20261021"
    )


def test_send_gmail_reads_subject_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "sender@example.test")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-password")
    monkeypatch.setenv("GMAIL_TO", "one@example.test")
    smtp_factory = MagicMock()
    smtp = smtp_factory.return_value.__enter__.return_value
    monkeypatch.setattr(send_gmail.smtplib, "SMTP_SSL", smtp_factory)
    body = tmp_path / "mail.txt"
    body.write_text("本文\n", encoding="utf-8")
    subject = tmp_path / "subject.txt"
    subject.write_text("【変更なし】msData 定期チェック 20261021\n", encoding="utf-8")

    assert send_gmail.main(["--subject-file", str(subject), "--body", str(body)]) == 0
    sent = smtp.send_message.call_args.args[0]
    assert sent["Subject"] == "【変更なし】msData 定期チェック 20261021"

    subject.write_text("\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        send_gmail.main(["--subject-file", str(subject), "--body", str(body)])


def test_failure_mail_subject_uses_failed_tag():
    captured: list[str] = []
    notify_failure(
        repo="owner/repo",
        workflow_name="auto review merge",
        conclusion="failure",
        run_url="https://example.invalid/run",
        run_id="123",
        created_at="2026-10-15T13:54:38Z",
        runner=MagicMock(side_effect=RuntimeError("skip issue")),
        mail_sender=lambda subject, body: captured.append(subject),
    )
    assert captured == ["【失敗】msData パイプライン（auto review merge）"]


@pytest.mark.parametrize(
    ("workflow", "build_start", "send_start", "send_end"),
    [
        (
            "data_update.yml",
            "- id: no_change_mail",
            "- name: Send no-change mail",
            "- name: Ensure pull request labels",
        ),
        (
            "data_update.yml",
            "- id: partial_hold_body",
            "- id: partial_hold_mail",
            "- name: Report partial hold notification failure",
        ),
        (
            "post_merge_notify.yml",
            "- id: mail_body",
            "- name: Send merged msData mail",
            "\n\n",
        ),
    ],
)
def test_workflows_send_subject_built_with_body(
    workflow: str, build_start: str, send_start: str, send_end: str
):
    text = workflow_text(workflow)
    build = step_block(text, start=build_start, end=send_start)
    send = text[text.index(send_start) :]
    send = send[: send.index(send_end)] if send_end in send else send
    assert "--subject-out" in build
    assert "--subject-file" in send
    assert "--subject " not in send
