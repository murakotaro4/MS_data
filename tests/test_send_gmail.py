from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ms_data.notify import send_gmail
from ms_data.notify.send_gmail import parse_recipients


def test_parse_recipients_empty() -> None:
    assert parse_recipients(None) == []
    assert parse_recipients("") == []


def test_parse_recipients_comma() -> None:
    raw = "a@example.com, b@example.com"
    assert parse_recipients(raw) == ["a@example.com", "b@example.com"]


def test_parse_recipients_semicolon_and_newline() -> None:
    raw = "a@example.com; b@example.com\nc@example.com"
    assert parse_recipients(raw) == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]


@pytest.mark.parametrize("with_html", [True, False])
@pytest.mark.parametrize("with_attachment", [True, False])
def test_send_preserves_plain_html_and_attachments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_html: bool,
    with_attachment: bool,
) -> None:
    monkeypatch.setenv("GMAIL_ADDRESS", "sender@example.test")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-password")
    monkeypatch.setenv("GMAIL_TO", "one@example.test,two@example.test")
    smtp = MagicMock()
    smtp_factory = MagicMock()
    smtp_factory.return_value.__enter__.return_value = smtp
    monkeypatch.setattr(send_gmail.smtplib, "SMTP_SSL", smtp_factory)
    text = tmp_path / "mail.txt"
    text.write_text("日本語の更新通知\n", encoding="utf-8")
    args = ["--subject", "更新通知", "--body", str(text)]
    if with_html:
        html = tmp_path / "mail.html"
        html.write_text("<h1>機体データの更新内容</h1>\n", encoding="utf-8")
        args.extend(["--html-body", str(html)])
    if with_attachment:
        attachment = tmp_path / "msData.json"
        attachment.write_bytes(b"[]")
        args.extend(["--attach", str(attachment)])
    assert send_gmail.main(args) == 0
    sent = smtp.send_message.call_args.args[0]
    message = BytesParser(policy=policy.default).parsebytes(sent.as_bytes())
    assert (
        message.get_body(preferencelist=("plain",)).get_content()
        == "日本語の更新通知\n"
    )
    if with_html:
        assert (
            message.get_body(preferencelist=("html",)).get_content()
            == "<h1>機体データの更新内容</h1>\n"
        )
        alternative = next(
            part
            for part in message.walk()
            if part.get_content_type() == "multipart/alternative"
        )
        assert [part.get_content_type() for part in alternative.iter_parts()] == [
            "text/plain",
            "text/html",
        ]
    else:
        assert message.get_body(preferencelist=("html",)) is None
    attachments = list(message.iter_attachments())
    assert len(attachments) == int(with_attachment)
    if with_attachment:
        assert attachments[0].get_filename() == "msData.json"
        assert attachments[0].get_payload(decode=True) == b"[]"
    assert smtp.send_message.call_args.kwargs["to_addrs"] == [
        "one@example.test",
        "two@example.test",
    ]


def test_missing_html_fails_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GMAIL_ADDRESS", "sender@example.test")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-password")
    text = tmp_path / "mail.txt"
    text.write_text("通知", encoding="utf-8")
    smtp_factory = MagicMock()
    monkeypatch.setattr(send_gmail.smtplib, "SMTP_SSL", smtp_factory)
    with pytest.raises(FileNotFoundError):
        send_gmail.main(
            [
                "--subject",
                "通知",
                "--body",
                str(text),
                "--html-body",
                str(tmp_path / "missing.html"),
            ]
        )
    smtp_factory.assert_not_called()
