"""official_overrides の期限到達（review_due / remove_due）を GitHub Issue で通知する。

`audit_official_overrides` の outputs を受け取り、`official_overrides 期限確認`
Issue を 1 本に集約する。既存 Issue の直前の通知と件数（review_due / remove_due）
が同じなら追記せず skipped とし、日次の同文コメントを抑止する。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ms_data.gh import issue_upsert
from ms_data.gh.gh_json import GhRunner, run_gh
from ms_data.gh.outputs import append_step_summary
from ms_data.gh.repo_labels import LABEL_SPECS

ISSUE_TITLE = "official_overrides 期限確認"
PRIMARY_LABEL = "override-due"
EXTRA_LABELS: tuple[str, ...] = ("official-overrides",)
AGGREGATION_SUBJECT = "期限情報"

_MARKER_RE = re.compile(
    r"<!--\s*override-due\s+report_date=(?P<report_date>\d{8})"
    r"\s+review_due=(?P<review_due>\d+)\s+remove_due=(?P<remove_due>\d+)\s*-->"
)
# マーカー導入前のコメント（箇条書きのみ）からも件数を読む
_LEGACY_REVIEW_RE = re.compile(r"^- review_due:\s*(\d+)\s*$", re.MULTILINE)
_LEGACY_REMOVE_RE = re.compile(r"^- remove_due:\s*(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class DueCounts:
    review_due: int
    remove_due: int


def build_marker(report_date: str, counts: DueCounts) -> str:
    return (
        f"<!-- override-due report_date={report_date} "
        f"review_due={counts.review_due} remove_due={counts.remove_due} -->"
    )


def build_due_body(
    *,
    report_date: str,
    counts: DueCounts,
    audit_report: str,
    run_url: str,
) -> str:
    """Issue 本文・追記コメントの本文を組み立てる（末尾にマーカー）。"""

    return "\n".join(
        [
            "official_overrides の期限確認が必要です。",
            "",
            f"- report_date: {report_date}",
            f"- review_due: {counts.review_due}",
            f"- remove_due: {counts.remove_due}",
            f"- audit_report: {audit_report}",
            f"- workflow_run: {run_url}",
            "",
            "remove_due が 1 件以上ある場合は、該当 override を撤去できるか確認してください。",
            "",
            build_marker(report_date, counts),
        ]
    )


def parse_due_counts(text: str) -> DueCounts | None:
    """本文からマーカー（優先）または箇条書きの件数を読む。無ければ None。"""

    match = _MARKER_RE.search(text)
    if match:
        return DueCounts(
            review_due=int(match.group("review_due")),
            remove_due=int(match.group("remove_due")),
        )
    review = _LEGACY_REVIEW_RE.search(text)
    remove = _LEGACY_REMOVE_RE.search(text)
    if review and remove:
        return DueCounts(
            review_due=int(review.group(1)), remove_due=int(remove.group(1))
        )
    return None


def latest_notified_counts(
    issue: dict[str, Any], comments: list[dict[str, Any]]
) -> DueCounts | None:
    """Issue の最新通知（最後のコメント、無ければ本文）の件数を返す。"""

    for comment in reversed(comments):
        counts = parse_due_counts(str(comment.get("body") or ""))
        if counts is not None:
            return counts
    return parse_due_counts(str(issue.get("body") or ""))


def should_comment(previous: DueCounts | None, current: DueCounts) -> bool:
    """件数が前回通知と異なるときだけ追記する（前回が読めなければ追記）。"""

    return previous is None or previous != current


def ensure_override_due_issue(
    *,
    repo: str,
    report_date: str,
    counts: DueCounts,
    audit_report: str,
    run_url: str,
    runner: GhRunner = run_gh,
) -> tuple[str, int]:
    """期限確認 Issue を作成・追記・スキップする。戻り値は (action, number)。"""

    issue_upsert.ensure_labels(
        repo,
        [LABEL_SPECS[PRIMARY_LABEL], *(LABEL_SPECS[name] for name in EXTRA_LABELS)],
        runner=runner,
    )
    body = build_due_body(
        report_date=report_date,
        counts=counts,
        audit_report=audit_report,
        run_url=run_url,
    )

    def _should_comment(existing: dict[str, Any]) -> bool:
        comments = issue_upsert.fetch_issue_comments(
            repo=repo, number=int(existing["number"]), runner=runner
        )
        return should_comment(latest_notified_counts(existing, comments), counts)

    return issue_upsert.upsert_issue(
        repo=repo,
        title=ISSUE_TITLE,
        body=body,
        label=PRIMARY_LABEL,
        extra_labels=EXTRA_LABELS,
        subject=AGGREGATION_SUBJECT,
        runner=runner,
        should_comment=_should_comment,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--report-date", required=True, help="YYYYMMDD")
    parser.add_argument("--review-due", type=int, required=True)
    parser.add_argument("--remove-due", type=int, required=True)
    parser.add_argument("--audit-report", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--step-summary", default=None)
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo または GITHUB_REPOSITORY が必要です")
    if args.review_due < 0 or args.remove_due < 0:
        parser.error("--review-due / --remove-due は 0 以上で指定してください")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    counts = DueCounts(review_due=args.review_due, remove_due=args.remove_due)
    if counts.review_due == 0 and counts.remove_due == 0:
        print("official_overrides due: 0 件のため Issue 通知をスキップします")
        return 0
    try:
        action, number = ensure_override_due_issue(
            repo=args.repo,
            report_date=args.report_date,
            counts=counts,
            audit_report=args.audit_report,
            run_url=args.run_url,
        )
    except Exception as exc:
        print(
            f"official_overrides 期限確認 Issue の通知に失敗しました: {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"official_overrides due issue: {action} #{number}")
    append_step_summary(
        [
            "### official_overrides 期限確認 Issue",
            f"- action: {action}",
            f"- issue: #{number}",
            f"- review_due: {counts.review_due} / remove_due: {counts.remove_due}",
        ],
        Path(args.step_summary) if args.step_summary else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
