#!/usr/bin/env python3
"""
Gmail SMTP でレポート本文を送信する。

- 本文はテキストとして送信
- `--attach` で添付ファイルを追加可能
- 宛先は `GMAIL_TO` のカンマ区切り複数指定に対応

環境変数:
  GMAIL_ADDRESS / GMAIL_APP_PASSWORD / GMAIL_TO
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def parse_recipients(raw: str | None) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace("\n", ",").replace(";", ",")
    recipients = [x.strip() for x in normalized.split(",")]
    return [x for x in recipients if x]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", type=Path, required=True)
    ap.add_argument("--to", default=os.getenv("GMAIL_TO"))
    ap.add_argument(
        "--attach",
        action="append",
        type=Path,
        default=[],
        help="添付ファイルのパス（複数指定可）",
    )
    args = ap.parse_args()

    gmail_address = os.getenv("GMAIL_ADDRESS")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipients = parse_recipients(args.to) or parse_recipients(gmail_address)

    if not gmail_address or not app_password or not recipients:
        raise SystemExit("GMAIL_ADDRESS / GMAIL_APP_PASSWORD / GMAIL_TO が未設定です。")

    body_text = args.body.read_text(encoding="utf-8")

    msg = EmailMessage()
    msg["Subject"] = args.subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text)

    for attach_path in args.attach:
        if not attach_path.exists():
            raise SystemExit(f"添付ファイルが見つかりません: {attach_path}")
        data = attach_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(attach_path))
        if mime:
            maintype, subtype = mime.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=attach_path.name,
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_address, app_password)
        smtp.send_message(msg, to_addrs=recipients)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
