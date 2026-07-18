"""自動更新パイプラインの失敗をメールと GitHub Issue で通知する。"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ms_data.gh.gh_json import GhRunner, gh_api_json, run_gh
from ms_data.notify import send_gmail


NOTIFY_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "startup_failure", "action_required"}
)
ISSUE_LABEL = "pipeline-failure"
ISSUE_LABEL_COLOR = "B60205"
MailSender = Callable[[str, str], None]


@dataclass(frozen=True)
class DuplicateIssue:
    number: int
    body: str


@dataclass(frozen=True)
class IssueRaceResolution:
    canonical_number: int
    duplicates: tuple[DuplicateIssue, ...]


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


def _label_names(issue: dict[str, Any]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    names: set[str] = set()
    for label in labels:
        if isinstance(label, str):
            names.add(label)
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            names.add(label["name"])
    return names


def _matching_open_issues(
    issues: list[dict[str, Any]],
    *,
    title: str,
    label: str = ISSUE_LABEL,
) -> list[dict[str, Any]]:
    return [
        issue
        for issue in issues
        if (
            issue.get("state") == "open"
            and issue.get("title") == title
            and label in _label_names(issue)
            and "pull_request" not in issue
            and int(issue.get("number") or 0) > 0
        )
    ]


def find_open_issue(
    issues: list[dict[str, Any]],
    *,
    title: str,
    label: str = ISSUE_LABEL,
) -> dict[str, Any] | None:
    """同タイトル・同ラベルの open Issue を返す。closed と PR は除外する。"""

    matches = _matching_open_issues(issues, title=title, label=label)
    return min(matches, key=lambda issue: int(issue["number"])) if matches else None


def resolve_issue_creation_race(
    issues: list[dict[str, Any]],
    *,
    title: str,
    created_number: int,
    label: str = ISSUE_LABEL,
) -> IssueRaceResolution | None:
    """競合する open Issue の正本と、閉じる全非正本を返す。"""

    matches = sorted(
        _matching_open_issues(issues, title=title, label=label),
        key=lambda issue: int(issue["number"]),
    )
    numbers = [int(issue["number"]) for issue in matches]
    if len(numbers) <= 1 or created_number not in numbers:
        return None
    canonical_number = numbers[0]
    duplicates = tuple(
        DuplicateIssue(
            number=int(issue["number"]),
            body=str(issue.get("body") or ""),
        )
        for issue in matches
        if int(issue["number"]) != canonical_number
    )
    return IssueRaceResolution(
        canonical_number=canonical_number,
        duplicates=duplicates,
    )


def build_issue_aggregation_comment(duplicate: DuplicateIssue) -> str:
    """非正本 Issue の失敗情報を正本へ集約するコメントを組み立てる。"""

    details = duplicate.body.strip() or "（重複 Issue の本文は空です）"
    return f"Issue #{duplicate.number} から失敗情報を集約します。\n\n{details}"


def converge_duplicate_issues(
    *,
    repo: str,
    resolution: IssueRaceResolution,
    runner: GhRunner,
) -> int:
    """非正本の失敗情報を正本へ集約し、理由コメント後に全件閉じる。"""

    for duplicate in resolution.duplicates:
        gh_api_json(
            f"repos/{repo}/issues/{resolution.canonical_number}/comments",
            method="POST",
            fields={"body": build_issue_aggregation_comment(duplicate)},
            runner=runner,
        )
        duplicate_reason = (
            f"Issue #{resolution.canonical_number} を正本として失敗情報を集約したため、"
            f"重複した Issue #{duplicate.number} を閉じます。"
        )
        gh_api_json(
            f"repos/{repo}/issues/{duplicate.number}/comments",
            method="POST",
            fields={"body": duplicate_reason},
            runner=runner,
        )
        gh_api_json(
            f"repos/{repo}/issues/{duplicate.number}",
            method="PATCH",
            fields={"state": "closed", "state_reason": "not_planned"},
            runner=runner,
        )
    return len(resolution.duplicates)


def _fetch_open_failure_issues(
    *,
    repo: str,
    runner: GhRunner,
) -> list[dict[str, Any]]:
    issues = gh_api_json(
        f"repos/{repo}/issues?state=open&labels={ISSUE_LABEL}&per_page=100",
        paginate=True,
        runner=runner,
    )
    if not isinstance(issues, list):
        raise ValueError("GitHub issues response must be a list")
    return issues


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

    runner(
        [
            "gh",
            "label",
            "create",
            ISSUE_LABEL,
            "--repo",
            repo,
            "--description",
            "Automatic pipeline failure notification",
            "--color",
            ISSUE_LABEL_COLOR,
            "--force",
        ]
    )

    title = issue_title(workflow_name)
    issues = _fetch_open_failure_issues(repo=repo, runner=runner)

    body = build_failure_details(
        workflow_name=workflow_name,
        conclusion=conclusion,
        run_url=run_url,
        run_id=run_id,
        created_at=created_at,
    )
    existing = find_open_issue(issues, title=title)
    if existing is not None:
        number = int(existing.get("number") or 0)
        if number <= 0:
            raise ValueError("Existing GitHub Issue has no valid number")
        gh_api_json(
            f"repos/{repo}/issues/{number}/comments",
            method="POST",
            fields={"body": body},
            runner=runner,
        )
        resolution = resolve_issue_creation_race(
            issues,
            title=title,
            created_number=number,
        )
        if resolution is not None:
            converge_duplicate_issues(
                repo=repo,
                resolution=resolution,
                runner=runner,
            )
            return "deduplicated", resolution.canonical_number
        return "commented", number

    created = gh_api_json(
        f"repos/{repo}/issues",
        method="POST",
        fields={"title": title, "body": body, "labels[]": ISSUE_LABEL},
        runner=runner,
    )
    if not isinstance(created, dict):
        raise ValueError("GitHub create Issue response must be an object")
    number = int(created.get("number") or 0)
    if number <= 0:
        raise ValueError("Created GitHub Issue has no valid number")

    issues_after_create = _fetch_open_failure_issues(repo=repo, runner=runner)
    race_resolution = resolve_issue_creation_race(
        issues_after_create,
        title=title,
        created_number=number,
    )
    if race_resolution is not None:
        converge_duplicate_issues(
            repo=repo,
            resolution=race_resolution,
            runner=runner,
        )
        return "deduplicated", race_resolution.canonical_number
    return "created", number


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
    except Exception as exc:  # noqa: BLE001 - Issue 通知は継続する
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
    except Exception as exc:  # noqa: BLE001 - メール結果とは独立して扱う
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
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"), required=False)
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
