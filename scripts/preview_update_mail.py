"""送信せず、レビュー用の通知HTML・テキストを同じ入力から再生成する。"""

from __future__ import annotations

import argparse
from pathlib import Path

from ms_data.gh.notify_failure import build_failure_mail_body, build_failure_notice
from ms_data.gh.notify_review_stop import build_notice
from ms_data.notify.notice_html import Notice, render_notice_html, render_notice_text
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
    # 詳細リンクは公開時点の固定 SHA 上のパスを指し、本文は prune されない fixture から読む。
    for name, relative, linked in (
        (
            "large-audit-20260601",
            "tests/fixtures/reports/official_overrides_audit_20260601.md",
            "tests/fixtures/reports/official_overrides_audit_20260601.md",
        ),
        (
            "large-audit-20260918",
            "tests/fixtures/reports/official_overrides_audit_20260918.md",
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
                f"https://github.com/murakotaro4/MS_data/blob/de073aa50e13a08dd0a4e648eb33c25e3f80ba23/{linked}",
                "--out",
                str(args.out_dir / f"{name}.txt"),
                "--html-out",
                str(args.out_dir / f"{name}.html"),
            ]
        )

    write_operation_notices(args.out_dir)


# PR #339 の停止メール（2026-10-20）に生で混入した Codex コメント本文の再現。
CODEX_FINDING_339 = (
    "**<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)"
    "</sub></sub> 中スロット値を取得元の29に戻す**\n\n"
    "この更新を取り込むと、`ガルバルディβ高機動型［T仕様］_LV2` の中スロットが"
    "誤った20として配布されます。\n\nUseful? React with 👍 / 👎.\n\n<!-- codex"
)


def write_operation_notices(out_dir: Path) -> None:
    """自動マージ停止・パイプライン失敗の通知例を書き出す。"""
    pr_url = "https://github.com/murakotaro4/MS_data/pull/339"
    run_url = "https://github.com/murakotaro4/MS_data/actions/runs/39436005101"
    notices: dict[str, tuple[Notice, str | None]] = {
        f"stop-{reason.replace('_', '-')}": (
            build_notice(
                stop_reason=reason,
                pr_number=339,
                pr_url=pr_url,
                report_date="20261020",
                run_url=run_url,
                findings=[
                    {
                        "path": "msData.json",
                        "line": 55564,
                        "url": f"{pr_url}#discussion_r0000000000",
                        "body": CODEX_FINDING_339,
                    }
                ],
            ),
            None,
        )
        for reason in ("findings", "no_response", "disconnected")
    }
    failure = {
        "workflow_name": "auto review merge",
        "conclusion": "failure",
        "run_url": "https://github.com/murakotaro4/MS_data/actions/runs/38746738277",
        "run_id": "38746738277",
        "created_at": "2026-10-15T13:54:38Z",
    }
    notices["pipeline-failure"] = (
        build_failure_notice(**failure),
        build_failure_mail_body(**failure),
    )
    for name, (notice, text) in notices.items():
        (out_dir / f"{name}.html").write_text(
            render_notice_html(notice), encoding="utf-8"
        )
        (out_dir / f"{name}.txt").write_text(
            text if text is not None else render_notice_text(notice), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
