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
