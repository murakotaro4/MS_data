"""送信せず、レビュー用の通知HTML・テキストを同じ入力から再生成する。"""

from __future__ import annotations

import argparse
from pathlib import Path

from ms_data.reporting.update_mail_html import render_update_mail
from ms_data.reporting.update_mail_model import localize_mail_body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mail"
    for source in sorted(fixtures.glob("*.md")):
        body = source.read_text(encoding="utf-8")
        (args.out_dir / f"{source.stem}.html").write_text(
            render_update_mail(body), encoding="utf-8"
        )
        (args.out_dir / f"{source.stem}.txt").write_text(
            localize_mail_body(body), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
