"""自動更新パイプラインの失敗をメールと GitHub Issue で通知する。"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ms_data.gh import issue_upsert
from ms_data.gh.gh_json import GhRunner, run_gh
from ms_data.gh.issue_upsert import DuplicateIssue, IssueRaceResolution
from ms_data.gh.repo_labels import LABEL_SPECS
from ms_data.notify import send_gmail

NOTIFY_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "startup_failure", "action_required"}
)
ISSUE_LABEL = "pipeline-failure"
ISSUE_LABEL_SPEC = LABEL_SPECS[ISSUE_LABEL]
ISSUE_LABEL_COLOR = ISSUE_LABEL_SPEC.color
AGGREGATION_SUBJECT = "失敗情報"
MailSender = Callable[[str, str], None]

__all__ = [
    "AGGREGATION_SUBJECT",
    "ISSUE_LABEL",
    "ISSUE_LABEL_COLOR",
    "ISSUE_LABEL_SPEC",
    "NOTIFY_CONCLUSIONS",
    "DuplicateIssue",
    "IssueRaceResolution",
    "MailSender",
    "build_failure_details",
    "build_failure_mail_body",
    "build_issue_aggregation_comment",
    "converge_duplicate_issues",
    "ensure_failure_issue",
    "find_open_issue",
    "issue_title",
    "main",
    "notify_failure",
    "parse_args",
    "resolve_issue_creation_race",
    "send_failure_mail",
    "should_notify",
]


def should_notify(conclusion: str) -> bool:
    """通知対象の workflow conclusion なら True を返す。"""

    return conclusion in NOTIFY_CONCLUSIONS


def issue_title(workflow_name: str) -> str:
    return f"[pipeline-failure] {workflow_name}"


def build_failure_details(
    *,
    workflow_name: str,
    conclusion: str,
    run_url: str,
    run_id: str,
    created_at: str,
) -> str:
    """メールと Issue で共有する失敗 run の詳細を組み立てる。"""

    return "\n".join(
        [
            "自動更新パイプラインで失敗を検知しました。",
            "",
            f"- workflow: {workflow_name}",
            f"- conclusion: {conclusion}",
            f"- run_id: {run_id}",
            f"- created_at: {created_at}",
            f"- run_url: {run_url}",
            "",
            "run のログを確認し、必要な対応を行ってください。",
        ]
    )


def build_failure_mail_body(
    *,
    workflow_name: str,
    conclusion: str,
    run_url: str,
    run_id: str,
    created_at: str,
) -> str:
    """失敗通知メールの本文を組み立てる。"""

    return build_failure_details(
        workflow_name=workflow_name,
        conclusion=conclusion,
        run_url=run_url,
        run_id=run_id,
        created_at=created_at,
    )


def find_open_issue(
    issues: list[dict[str, Any]],
    *,
    title: str,
    label: str = ISSUE_LABEL,
) -> dict[str, Any] | None:
    """同タイトル・同ラベルの open Issue を返す。closed と PR は除外する。"""

    return issue_upsert.find_open_issue(issues, title=title, label=label)


def resolve_issue_creation_race(
    issues: list[dict[str, Any]],
    *,
    title: str,
    created_number: int,
    label: str = ISSUE_LABEL,
) -> IssueRaceResolution | None:
    """競合する open Issue の正本と、閉じる全非正本を返す。"""

    return issue_upsert.resolve_issue_creation_race(
        issues, title=title, created_number=created_number, label=label
    )


def build_issue_aggregation_comment(duplicate: DuplicateIssue) -> str:
    """非正本 Issue の失敗情報を正本へ集約するコメントを組み立てる。"""

    return issue_upsert.build_issue_aggregation_comment(
        duplicate, subject=AGGREGATION_SUBJECT
    )


def converge_duplicate_issues(
    *,
    repo: str,
    resolution: IssueRaceResolution,
    runner: GhRunner,
) -> int:
    """非正本の失敗情報を正本へ集約し、理由コメント後に全件閉じる。"""

    return issue_upsert.converge_duplicate_issues(
        repo=repo, resolution=resolution, subject=AGGREGATION_SUBJECT, runner=runner
    )


def ensure_failure_issue(
    *,
    repo: str,
    workflow_name: str,
    conclusion: str,
    run_url: str,
    run_id: str,
    created_at: str,
    runner: GhRunner = run_gh,
) -> tuple[str, int]:
    """失敗 Issue を新規作成するか、既存 open Issue にコメントする。"""

    issue_upsert.ensure_labels(repo, [ISSUE_LABEL_SPEC], runner=runner)
    body = build_failure_details(
        workflow_name=workflow_name,
        conclusion=conclusion,
        run_url=run_url,
        run_id=run_id,
        created_at=created_at,
    )
    return issue_upsert.upsert_issue(
        repo=repo,
        title=issue_title(workflow_name),
        body=body,
        label=ISSUE_LABEL,
        subject=AGGREGATION_SUBJECT,
        runner=runner,
    )


def send_failure_mail(subject: str, body: str) -> None:
    """既存 send_gmail CLI を使って失敗通知メールを送る。"""

    with tempfile.TemporaryDirectory(prefix="msdata-failure-mail-") as tmp_dir:
        body_path = Path(tmp_dir) / "body.txt"
        body_path.write_text(body, encoding="utf-8")
        original_argv = sys.argv
        try:
            sys.argv = [
                "ms_data.notify.send_gmail",
                "--subject",
                subject,
                "--body",
                str(body_path),
            ]
            result = send_gmail.main()
        except SystemExit as exc:
            raise RuntimeError(f"send_gmail failed: {exc.code}") from exc
        finally:
            sys.argv = original_argv
        if result != 0:
            raise RuntimeError(f"send_gmail failed: {result}")


def notify_failure(
    *,
    repo: str,
    workflow_name: str,
    conclusion: str,
    run_url: str,
    run_id: str,
    created_at: str,
    runner: GhRunner = run_gh,
    mail_sender: MailSender = send_failure_mail,
) -> int:
    """両通知を独立試行し、両方失敗した場合だけ 1 を返す。"""

    if not should_notify(conclusion):
        return 0

    body = build_failure_mail_body(
        workflow_name=workflow_name,
        conclusion=conclusion,
        run_url=run_url,
        run_id=run_id,
        created_at=created_at,
    )
    subject = f"msData パイプライン失敗通知 ({workflow_name})"
    failures = 0

    try:
        mail_sender(subject, body)
    except Exception as exc:
        failures += 1
        print(f"メール送信に失敗しました: {exc}", file=sys.stderr)

    try:
        action, number = ensure_failure_issue(
            repo=repo,
            workflow_name=workflow_name,
            conclusion=conclusion,
            run_url=run_url,
            run_id=run_id,
            created_at=created_at,
            runner=runner,
        )
        print(f"GitHub Issue: {action} #{number}")
    except Exception as exc:
        failures += 1
        print(f"GitHub Issue 通知に失敗しました: {exc}", file=sys.stderr)

    return 1 if failures == 2 else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--conclusion", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument(
        "--repo", default=os.getenv("GITHUB_REPOSITORY"), required=False
    )
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo または GITHUB_REPOSITORY が必要です")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return notify_failure(
        repo=args.repo,
        workflow_name=args.workflow_name,
        conclusion=args.conclusion,
        run_url=args.run_url,
        run_id=args.run_id,
        created_at=args.created_at,
    )


if __name__ == "__main__":
    raise SystemExit(main())
