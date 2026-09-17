"""GitHub Issue の「検索 → 作成 or 追記」と重複 Issue 収束の共通処理。

notify_failure（失敗通知）と notify_override_due（期限確認）が共有する。
同タイトル・同ラベルの open Issue を 1 本に集約し、同時実行で複数作成された
場合は最小番号を正本として残りを閉じる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ms_data.gh.gh_json import GhRunner, gh_api_json, run_gh


@dataclass(frozen=True)
class LabelSpec:
    name: str
    description: str
    color: str


@dataclass(frozen=True)
class DuplicateIssue:
    number: int
    body: str


@dataclass(frozen=True)
class IssueRaceResolution:
    canonical_number: int
    duplicates: tuple[DuplicateIssue, ...]


def ensure_labels(
    repo: str, specs: Iterable[LabelSpec], *, runner: GhRunner = run_gh
) -> None:
    """ラベルを冪等に作成（存在すれば説明・色を更新）する。"""

    for spec in specs:
        runner(
            [
                "gh",
                "label",
                "create",
                spec.name,
                "--repo",
                repo,
                "--description",
                spec.description,
                "--color",
                spec.color,
                "--force",
            ]
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
    label: str,
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
    label: str,
) -> dict[str, Any] | None:
    """同タイトル・同ラベルの open Issue を返す。closed と PR は除外する。"""

    matches = _matching_open_issues(issues, title=title, label=label)
    return min(matches, key=lambda issue: int(issue["number"])) if matches else None


def resolve_issue_creation_race(
    issues: list[dict[str, Any]],
    *,
    title: str,
    created_number: int,
    label: str,
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


def build_issue_aggregation_comment(duplicate: DuplicateIssue, *, subject: str) -> str:
    """非正本 Issue の情報を正本へ集約するコメントを組み立てる。"""

    details = duplicate.body.strip() or "（重複 Issue の本文は空です）"
    return f"Issue #{duplicate.number} から{subject}を集約します。\n\n{details}"


def converge_duplicate_issues(
    *,
    repo: str,
    resolution: IssueRaceResolution,
    subject: str,
    runner: GhRunner,
) -> int:
    """非正本の情報を正本へ集約し、理由コメント後に全件閉じる。"""

    for duplicate in resolution.duplicates:
        gh_api_json(
            f"repos/{repo}/issues/{resolution.canonical_number}/comments",
            method="POST",
            fields={
                "body": build_issue_aggregation_comment(duplicate, subject=subject)
            },
            runner=runner,
        )
        duplicate_reason = (
            f"Issue #{resolution.canonical_number} を正本として{subject}を集約したため、"
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


def fetch_open_issues(
    *,
    repo: str,
    label: str,
    runner: GhRunner,
) -> list[dict[str, Any]]:
    issues = gh_api_json(
        f"repos/{repo}/issues?state=open&labels={label}&per_page=100",
        paginate=True,
        runner=runner,
    )
    if not isinstance(issues, list):
        raise ValueError("GitHub issues response must be a list")
    return issues


def fetch_issue_comments(
    *,
    repo: str,
    number: int,
    runner: GhRunner,
) -> list[dict[str, Any]]:
    comments = gh_api_json(
        f"repos/{repo}/issues/{number}/comments?per_page=100",
        paginate=True,
        runner=runner,
    )
    if not isinstance(comments, list):
        raise ValueError("GitHub issue comments response must be a list")
    return comments


ShouldComment = Callable[[dict[str, Any]], bool]


def upsert_issue(
    *,
    repo: str,
    title: str,
    body: str,
    label: str,
    extra_labels: Iterable[str] = (),
    subject: str,
    runner: GhRunner = run_gh,
    should_comment: ShouldComment | None = None,
) -> tuple[str, int]:
    """Issue を新規作成するか、既存 open Issue にコメントする。

    戻り値の action は created / commented / skipped / deduplicated のいずれか。
    `should_comment` が与えられ False を返した場合、既存 Issue へは追記しない
    （skipped）。重複 Issue の収束はどちらの経路でも行う。
    """

    issues = fetch_open_issues(repo=repo, label=label, runner=runner)

    existing = find_open_issue(issues, title=title, label=label)
    if existing is not None:
        number = int(existing.get("number") or 0)
        if number <= 0:
            raise ValueError("Existing GitHub Issue has no valid number")
        commented = should_comment is None or should_comment(existing)
        if commented:
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
            label=label,
        )
        if resolution is not None:
            converge_duplicate_issues(
                repo=repo,
                resolution=resolution,
                subject=subject,
                runner=runner,
            )
            return "deduplicated", resolution.canonical_number
        return ("commented" if commented else "skipped"), number

    created = gh_api_json(
        f"repos/{repo}/issues",
        method="POST",
        fields={
            "title": title,
            "body": body,
            "labels[]": [label, *extra_labels],
        },
        runner=runner,
    )
    if not isinstance(created, dict):
        raise ValueError("GitHub create Issue response must be an object")
    number = int(created.get("number") or 0)
    if number <= 0:
        raise ValueError("Created GitHub Issue has no valid number")

    issues_after_create = fetch_open_issues(repo=repo, label=label, runner=runner)
    race_resolution = resolve_issue_creation_race(
        issues_after_create,
        title=title,
        created_number=number,
        label=label,
    )
    if race_resolution is not None:
        converge_duplicate_issues(
            repo=repo,
            resolution=race_resolution,
            subject=subject,
            runner=runner,
        )
        return "deduplicated", race_resolution.canonical_number
    return "created", number
