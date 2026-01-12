#!/usr/bin/env python3
"""
Gmail SMTP で Markdown レポートを送信する。

環境変数:
  GMAIL_ADDRESS / GMAIL_APP_PASSWORD / GMAIL_TO
"""
from __future__ import annotations

import argparse
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", type=Path, required=True)
    ap.add_argument("--to", default=os.getenv("GMAIL_TO"))
    args = ap.parse_args()

    gmail_address = os.getenv("GMAIL_ADDRESS")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    to_addr = args.to or gmail_address

    if not gmail_address or not app_password or not to_addr:
        raise SystemExit("GMAIL_ADDRESS / GMAIL_APP_PASSWORD / GMAIL_TO が未設定です。")

    body_text = args.body.read_text(encoding="utf-8")

    msg = EmailMessage()
    msg["Subject"] = args.subject
    msg["From"] = gmail_address
    msg["To"] = to_addr
    msg.set_content(body_text)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_address, app_password)
        smtp.send_message(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
