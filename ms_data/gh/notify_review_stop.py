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
from ms_data.notify.notice_html import (
    Notice,
    NoticeCard,
    render_notice_html,
    render_notice_text,
)
from ms_data.notify.subjects import STATUS_ACTION, format_subject

MailSender = Callable[[str, str, str], None]

STOP_REASONS = frozenset({"findings", "no_response", "disconnected"})
REASON_LABELS = {
    "findings": "codex_findings",
    "no_response": "codex_no_response",
    "disconnected": "codex_disconnected",
}
SUBJECT_DETAILS = {
    "findings": "Codex指摘",
    "no_response": "Codex応答なし",
    "disconnected": "Codex連携切れ",
}
MAX_FINDINGS_IN_MAIL = 20
MAX_FINDING_TITLE_CHARS = 120
CONNECTOR_SETTINGS_URL = "https://chatgpt.com/codex/cloud/settings/connectors"
MANUAL_RECOVERY_HINT = (
    "PR に手動で `@codex review` をコメントすれば、"
    "翌朝 09:00 JST の自動レスキューがマージまで回収します。"
)
# 改行(\\n)・タブ以外の制御文字を除去する
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_BADGE_RE = re.compile(r"!\[(P\d)\b[^\]]*\]\([^)]*\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
# バッジ画像・HTML タグ・HTML コメント（閉じていない断片を含む）
_MARKUP_RE = re.compile(
    r"!\[[^\]]*\]\([^)]*\)|<!--.*?(?:-->|$)|</?[A-Za-z][^>]*>", re.S
)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def reason_label(stop_reason: str) -> str:
    """CLI の stop_reason を停止理由ラベル（codex_*）へ変換する。"""

    try:
        return REASON_LABELS[stop_reason]
    except KeyError as exc:
        raise ValueError(f"unsupported stop_reason: {stop_reason}") from exc


def build_subject(*, stop_reason: str, pr_number: int) -> str:
    """停止通知メールの件名を組み立てる。"""

    if stop_reason not in SUBJECT_DETAILS:
        raise ValueError(f"unsupported stop_reason: {stop_reason}")
    return format_subject(
        STATUS_ACTION,
        "自動マージ停止",
        label=f"PR #{pr_number}",
        detail=SUBJECT_DETAILS[stop_reason],
    )


def _plain_markdown(text: str) -> str:
    text = _MARKUP_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return " ".join(text.split())


def summarize_finding(body: str) -> tuple[str, str]:
    """Codex のコメント本文から優先度と1行の要点だけを取り出す。

    バッジ画像・HTML タグ・リアクション案内などの GitHub 向け記法はメールに出さない。
    """

    text = _CONTROL_CHARS_RE.sub("", body)
    badge = _BADGE_RE.search(text)
    priority = badge[1] if badge else ""
    title = ""
    for match in _BOLD_RE.finditer(text):
        title = _plain_markdown(match[1])
        if title:
            break
    if not title:
        title = next(
            (plain for line in text.splitlines() if (plain := _plain_markdown(line))),
            "",
        )
    if len(title) > MAX_FINDING_TITLE_CHARS:
        title = title[: MAX_FINDING_TITLE_CHARS - 1] + "…"
    return priority, title or "（要点を読み取れません。PR で確認してください）"


def _format_finding_location(finding: dict[str, Any]) -> str:
    path = str(finding.get("path") or "")
    line = finding.get("line")
    if line is None:
        return path
    return f"{path}:{line}"


def _finding_url(finding: dict[str, Any]) -> str:
    url = finding.get("url")
    return url if isinstance(url, str) and url.startswith("https://") else ""


def finding_cards(findings: list[dict[str, Any]]) -> list[NoticeCard]:
    """findings を「優先度・要点・ファイル:行・コメントへのリンク」のカードにする。"""

    cards: list[NoticeCard] = []
    for finding in findings[:MAX_FINDINGS_IN_MAIL]:
        priority, title = summarize_finding(str(finding.get("body") or ""))
        location = _format_finding_location(finding)
        url = _finding_url(finding)
        cards.append(
            NoticeCard(
                f"[{priority}] {title}" if priority else title,
                [location] if location else [],
                [("指摘コメント", url)] if url else [],
            )
        )
    remaining = len(findings) - len(cards)
    if remaining > 0:
        cards.append(NoticeCard(f"ほか {remaining} 件", ["PR で確認してください。"]))
    return cards


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


def _date_label(report_date: str) -> str:
    if re.fullmatch(r"\d{8}", report_date):
        return f"{report_date[:4]} / {report_date[4:6]} / {report_date[6:]}"
    return report_date


def build_notice(
    *,
    stop_reason: str,
    pr_number: int | None = None,
    pr_url: str,
    report_date: str,
    run_url: str,
    findings: list[dict[str, Any]] | None = None,
) -> Notice:
    """停止通知のテキスト版・HTML 版で共有する表示モデルを作る。"""

    links = [(f"PR #{pr_number}" if pr_number else "PR", pr_url), ("実行ログ", run_url)]
    if stop_reason == "findings":
        findings = findings or []
        result = (
            f"Codex レビューでファイル指摘が {len(findings)} 件あったため停止しました。"
        )
        action = "PR の指摘を確認し、修正するか返信してください。"
    elif stop_reason == "no_response":
        result = "Codex のレビュー応答が確認できなかったため停止しました。"
        action = MANUAL_RECOVERY_HINT
    elif stop_reason == "disconnected":
        result = "Codex のコネクタ連携が切れているため停止しました。"
        action = f"Codex のコネクタ設定を確認してください。{MANUAL_RECOVERY_HINT}"
        links.append(("Codex のコネクタ設定", CONNECTOR_SETTINGS_URL))
    else:
        raise ValueError(f"unsupported stop_reason: {stop_reason}")

    notice = Notice(
        kicker="MS DATA · 自動マージ停止",
        title="自動マージを停止しました",
        result=result,
        action=action,
        date=_date_label(report_date),
        links=links,
        footer=[f"対象日（report_date）: {report_date}"],
    )
    if stop_reason == "findings":
        notice.cards_heading = f"Codex の指摘（{len(findings)}件）"
        notice.cards = finding_cards(findings)
    return notice


def build_mail_body(**kwargs: Any) -> str:
    """停止通知メールのテキスト本文を組み立てる。"""

    return render_notice_text(build_notice(**kwargs))


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
    notice = build_notice(
        stop_reason=stop_reason,
        pr_number=pr_number,
        pr_url=pr_url,
        report_date=report_date,
        run_url=run_url,
        findings=findings,
    )
    try:
        mail_sender(subject, render_notice_text(notice), render_notice_html(notice))
    except Exception as exc:
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
