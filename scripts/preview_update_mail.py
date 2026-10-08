"""送信せず、レビュー用の通知HTML・テキストを同じ入力から再生成する。"""

from __future__ import annotations

import argparse
from pathlib import Path

from ms_data.reporting.build_update_mail_body import main as build_mail
from ms_data.reporting.update_mail_html import prepare_update_mail
from ms_data.reporting.update_mail_model import localize_mail_body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mail"
    for source in sorted(fixtures.glob("*.md")):
        body = source.read_text(encoding="utf-8")
        view, html = prepare_update_mail(body)
        (args.out_dir / f"{source.stem}.html").write_text(html, encoding="utf-8")
        (args.out_dir / f"{source.stem}.txt").write_text(
            localize_mail_body(body, view=view), encoding="utf-8"
        )
    root = Path(__file__).resolve().parents[1]
    for name, relative in (
        (
            "large-audit-20260601",
            "tests/fixtures/reports/official_overrides_audit_20260601.md",
        ),
        (
            "large-audit-20260918",
            "reports/2026/09/official_overrides_audit_20260918.md",
        ),
    ):
        build_mail(
            [
                "--report-date",
                "20261008",
                "--result",
                "成功（差分なし）",
                "--changed",
                "false",
                "--official-overrides-audit-path",
                str(root / relative),
                "--detail-url",
                f"https://github.com/murakotaro4/MS_data/blob/de073aa50e13a08dd0a4e648eb33c25e3f80ba23/{relative}",
                "--out",
                str(args.out_dir / f"{name}.txt"),
                "--html-out",
                str(args.out_dir / f"{name}.html"),
            ]
        )


if __name__ == "__main__":
    main()
