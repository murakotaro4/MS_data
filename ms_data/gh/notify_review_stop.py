"""自動レビュー・マージ停止時にメールで通知する。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ms_data.gh.notify_failure import send_failure_mail

MailSender = Callable[[str, str], None]

STOP_REASONS = frozenset({"findings", "no_response", "disconnected"})
REASON_LABELS = {
    "findings": "codex_findings",
    "no_response": "codex_no_response",
    "disconnected": "codex_disconnected",
}
MAX_FINDING_BODY_CHARS = 500
MAX_FINDINGS_IN_MAIL = 20
CONNECTOR_SETTINGS_URL = "https://chatgpt.com/codex/cloud/settings/connectors"
MANUAL_RECOVERY_HINT = (
    "PR に手動で `@codex review` をコメントすれば、"
    "翌朝 09:00 JST の自動レスキューがマージまで回収します。"
)
# 改行(\\n)・タブ以外の制御文字を除去する
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def reason_label(stop_reason: str) -> str:
    """CLI の stop_reason を件名用ラベルへ変換する。"""

    try:
        return REASON_LABELS[stop_reason]
    except KeyError as exc:
        raise ValueError(f"unsupported stop_reason: {stop_reason}") from exc


def build_subject(*, stop_reason: str, pr_number: int) -> str:
    """停止通知メールの件名を組み立てる。"""

    return f"msData 自動マージ停止 ({reason_label(stop_reason)}) PR #{pr_number}"


def sanitize_finding_body(text: str) -> str:
    """指摘本文から制御文字を除き、最大文字数で切り詰める。"""

    cleaned = _CONTROL_CHARS_RE.sub("", text)
    if len(cleaned) <= MAX_FINDING_BODY_CHARS:
        return cleaned
    return cleaned[:MAX_FINDING_BODY_CHARS]


def _format_finding_location(finding: dict[str, Any]) -> str:
    path = str(finding.get("path") or "")
    line = finding.get("line")
    if line is None:
        return path
    return f"{path}:{line}"


def format_findings_section(findings: list[dict[str, Any]]) -> list[str]:
    """findings をメール本文向けの行リストへ整形する。"""

    lines: list[str] = ["指摘一覧:"]
    shown = findings[:MAX_FINDINGS_IN_MAIL]
    for finding in shown:
        location = _format_finding_location(finding)
        body = sanitize_finding_body(str(finding.get("body") or ""))
        lines.append(f"- {location}")
        if body:
            lines.append(f"  {body}")
    remaining = len(findings) - len(shown)
    if remaining > 0:
        lines.append(f"ほか {remaining} 件")
    return lines


def load_findings(path: Path | None) -> list[dict[str, Any]]:
    """findings JSON を読み込む。未指定なら空リストを返す。"""

    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("findings JSON must be a list")
    findings: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("findings JSON items must be objects")
        findings.append(item)
    return findings


def build_mail_body(
    *,
    stop_reason: str,
    pr_url: str,
    report_date: str,
    run_url: str,
    findings: list[dict[str, Any]] | None = None,
) -> str:
    """停止通知メールの本文を組み立てる。"""

    if stop_reason == "findings":
        reason_lines = [
            "Codex レビューでファイル指摘があったため、自動マージを停止しました。",
        ]
    elif stop_reason == "no_response":
        reason_lines = [
            "Codex のレビュー応答が確認できなかったため、自動マージを停止しました。",
            "",
            MANUAL_RECOVERY_HINT,
        ]
    elif stop_reason == "disconnected":
        reason_lines = [
            "Codex のコネクタ連携が切れているため、自動マージを停止しました。",
            f"確認先: {CONNECTOR_SETTINGS_URL}",
            "",
            MANUAL_RECOVERY_HINT,
        ]
    else:
        raise ValueError(f"unsupported stop_reason: {stop_reason}")

    lines = [
        *reason_lines,
        "",
        f"- PR: {pr_url}",
        f"- report_date: {report_date}",
        f"- run_url: {run_url}",
    ]
    if stop_reason == "findings":
        lines.append("")
        lines.extend(format_findings_section(findings or []))
    return "\n".join(lines)


def notify_review_stop(
    *,
    stop_reason: str,
    pr_number: int,
    pr_url: str,
    report_date: str,
    run_url: str,
    findings_json: Path | None = None,
    mail_sender: MailSender = send_failure_mail,
) -> int:
    """停止通知メールを送り、失敗時は 1 を返す。"""

    if stop_reason not in STOP_REASONS:
        raise ValueError(f"unsupported stop_reason: {stop_reason}")

    findings = load_findings(findings_json) if stop_reason == "findings" else []
    subject = build_subject(stop_reason=stop_reason, pr_number=pr_number)
    body = build_mail_body(
        stop_reason=stop_reason,
        pr_url=pr_url,
        report_date=report_date,
        run_url=run_url,
        findings=findings,
    )
    try:
        mail_sender(subject, body)
    except Exception as exc:  # noqa: BLE001 - CLI は非ゼロで失敗を伝える
        print(f"メール送信に失敗しました: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stop-reason",
        required=True,
        choices=sorted(STOP_REASONS),
    )
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--pr-url", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--findings-json", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return notify_review_stop(
        stop_reason=args.stop_reason,
        pr_number=args.pr_number,
        pr_url=args.pr_url,
        report_date=args.report_date,
        run_url=args.run_url,
        findings_json=args.findings_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
