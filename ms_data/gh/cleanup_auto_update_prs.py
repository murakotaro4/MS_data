"""古い data/auto-update-* PR と残留リモートブランチを整理する。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ms_data.gh.gh_json import run_gh


HEAD_REF_RE = re.compile(r"^data/auto-update-(\d{8})$")
AUTO_UPDATE_BRANCH_RE = re.compile(r"^data/auto-update-.+$")
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class CleanupAction:
    number: int
    head_ref: str
    report_date: str
    age_days: int
    action: str
    reason: str


@dataclass(frozen=True)
class BranchCleanupResult:
    branch: str
    action: str
    reason: str
    current_sha: str = ""


def today_jst() -> str:
    return datetime.now(JST).strftime("%Y%m%d")


def parse_report_date(head_ref: str) -> str | None:
    match = HEAD_REF_RE.match(head_ref)
    return match.group(1) if match else None


def _date_value(yyyymmdd: str) -> datetime:
    return datetime.strptime(yyyymmdd, "%Y%m%d").replace(tzinfo=JST)


def plan_cleanup(
    pulls: list[dict[str, Any]],
    *,
    today: str,
    keep_days: int,
) -> list[CleanupAction]:
    today_dt = _date_value(today)
    actions: list[CleanupAction] = []

    for item in pulls:
        head = item.get("head") if isinstance(item.get("head"), dict) else {}
        head_ref = str(head.get("ref") or "")
        report_date = parse_report_date(head_ref)
        if report_date is None:
            continue

        age_days = (today_dt - _date_value(report_date)).days
        number = int(item.get("number") or 0)
        if report_date == today:
            action = "keep"
            reason = "today"
        elif age_days <= keep_days:
            action = "keep"
            reason = f"within_keep_days:{keep_days}"
        else:
            action = "close"
            reason = f"stale_open_pr:{age_days}d"
        actions.append(
            CleanupAction(
                number=number,
                head_ref=head_ref,
                report_date=report_date,
                age_days=age_days,
                action=action,
                reason=reason,
            )
        )
    return sorted(actions, key=lambda item: (item.report_date, item.number))


def _run(cmd: list[str]) -> str:
    return run_gh(cmd)


def _gh_json(endpoint: str) -> Any:
    text = _run(["gh", "api", endpoint])
    return json.loads(text) if text.strip() else []


def _gh_json_paginated(endpoint: str) -> list[dict[str, Any]]:
    text = _run(["gh", "api", "--paginate", "--slurp", endpoint])
    data = json.loads(text) if text.strip() else []
    if not isinstance(data, list):
        raise ValueError("GitHub paginated response must be a list")
    pages = data if all(isinstance(page, list) for page in data) else [data]
    return [item for page in pages for item in page if isinstance(item, dict)]


def fetch_open_pulls(repo: str) -> list[dict[str, Any]]:
    data = _gh_json(f"repos/{repo}/pulls?state=open&base=main&per_page=100")
    if not isinstance(data, list):
        raise ValueError("GitHub pulls response must be a list")
    return data


def fetch_all_pulls(repo: str) -> list[dict[str, Any]]:
    return _gh_json_paginated(f"repos/{repo}/pulls?state=all&per_page=100")


def fetch_remote_branches(repo: str) -> list[str]:
    branches = _gh_json_paginated(f"repos/{repo}/branches?per_page=100")
    return sorted(
        name
        for item in branches
        if (name := str(item.get("name") or ""))
        and AUTO_UPDATE_BRANCH_RE.fullmatch(name)
    )


def fetch_default_branch(repo: str) -> str:
    data = _gh_json(f"repos/{repo}")
    if not isinstance(data, dict):
        raise ValueError("GitHub repository response must be an object")
    return str(data.get("default_branch") or "main")


def fetch_branch_sha(repo: str, branch: str) -> str:
    data = _gh_json(f"repos/{repo}/git/ref/heads/{branch}")
    if not isinstance(data, dict):
        raise ValueError("GitHub ref response must be an object")
    obj = data.get("object") if isinstance(data.get("object"), dict) else {}
    sha = str(obj.get("sha") or "")
    if not sha:
        raise ValueError(f"GitHub ref response has no SHA: {branch}")
    return sha


def normalize_github_repo_url(url: str) -> str | None:
    value = url.strip()
    scp_match = re.fullmatch(r"(?:[^@/:]+@)?github\.com:(?P<path>[^?#]+)", value)
    if scp_match:
        path = scp_match.group("path")
    else:
        parsed = urlparse(value)
        if (parsed.hostname or "").casefold() != "github.com":
            return None
        path = parsed.path

    path = path.strip("/")
    if path.casefold().endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return f"{parts[0]}/{parts[1]}".casefold()


def fetch_origin_repos() -> tuple[str | None, str | None]:
    fetch_url = _run(["git", "remote", "get-url", "origin"])
    push_url = _run(["git", "remote", "get-url", "--push", "origin"])
    return (
        normalize_github_repo_url(fetch_url),
        normalize_github_repo_url(push_url),
    )


def _pull_state(pull: dict[str, Any]) -> str:
    if pull.get("merged_at") or pull.get("mergedAt"):
        return "MERGED"
    return str(pull.get("state") or "").upper()


def _head_ref(pull: dict[str, Any]) -> str:
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    return str(pull.get("headRefName") or head.get("ref") or "")


def _base_ref(pull: dict[str, Any]) -> str:
    base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
    return str(pull.get("baseRefName") or base.get("ref") or "")


def _head_oid(pull: dict[str, Any]) -> str:
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    return str(pull.get("headRefOid") or head.get("sha") or "")


def _head_belongs_to_repo(pull: dict[str, Any], repo: str) -> bool:
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
    full_name = str(head_repo.get("full_name") or "")
    return not full_name or full_name == repo


def _command_error_text(exc: subprocess.CalledProcessError) -> str:
    output = f"{exc.stdout or ''}\n{exc.stderr or ''}".lower()
    return output


def _is_already_deleted(exc: subprocess.CalledProcessError) -> bool:
    output = _command_error_text(exc)
    return "remote ref does not exist" in output or "remote ref not found" in output


def _is_api_not_found(exc: subprocess.CalledProcessError) -> bool:
    return re.search(r"\b404\b", _command_error_text(exc)) is not None


def _is_lease_failed(exc: subprocess.CalledProcessError) -> bool:
    output = _command_error_text(exc)
    return "stale info" in output or "[rejected]" in output


def delete_remote_branch(branch: str, expected_sha: str) -> str:
    try:
        _run(
            [
                "git",
                "push",
                f"--force-with-lease=refs/heads/{branch}:{expected_sha}",
                "origin",
                f":refs/heads/{branch}",
            ]
        )
    except subprocess.CalledProcessError as exc:
        if _is_already_deleted(exc):
            return "already_deleted"
        if _is_lease_failed(exc):
            return "lease_failed"
        raise
    return "deleted"


def cleanup_merged_branches(
    repo: str,
    *,
    dry_run: bool,
) -> list[BranchCleanupResult]:
    branches = fetch_remote_branches(repo)
    if not branches:
        return []

    expected_repo = repo.strip().removesuffix(".git").casefold()
    fetch_repo, push_repo = fetch_origin_repos()
    if fetch_repo != expected_repo or push_repo != expected_repo:
        return [
            BranchCleanupResult(branch, "skipped", "origin_mismatch")
            for branch in branches
        ]

    default_branch = fetch_default_branch(repo)
    pulls = fetch_all_pulls(repo)
    results: list[BranchCleanupResult] = []

    open_heads = {
        _head_ref(pull)
        for pull in pulls
        if _pull_state(pull) == "OPEN" and _head_belongs_to_repo(pull, repo)
    }
    open_bases = {
        _base_ref(pull) for pull in pulls if _pull_state(pull) == "OPEN"
    }

    for branch in branches:
        if branch == default_branch:
            results.append(BranchCleanupResult(branch, "skipped", "default_branch"))
            continue
        if branch in open_heads:
            results.append(BranchCleanupResult(branch, "skipped", "open_pr_head"))
            continue
        if branch in open_bases:
            results.append(BranchCleanupResult(branch, "skipped", "open_pr_base"))
            continue

        branch_pulls = [
            pull
            for pull in pulls
            if _head_ref(pull) == branch and _head_belongs_to_repo(pull, repo)
        ]
        if not branch_pulls:
            results.append(BranchCleanupResult(branch, "skipped", "no_pr"))
            continue

        states = {_pull_state(pull) for pull in branch_pulls}
        if not states.issubset({"MERGED", "CLOSED"}):
            states_text = ",".join(sorted(states)) or "unknown"
            results.append(
                BranchCleanupResult(
                    branch,
                    "skipped",
                    f"non_terminal_pr:{states_text}",
                )
            )
            continue

        merged_oids = {
            _head_oid(pull)
            for pull in branch_pulls
            if _pull_state(pull) == "MERGED"
        }
        if not merged_oids:
            results.append(
                BranchCleanupResult(branch, "skipped", "closed_only_no_merged")
            )
            continue

        try:
            current_sha = fetch_branch_sha(repo, branch)
        except subprocess.CalledProcessError as exc:
            if _is_api_not_found(exc):
                results.append(
                    BranchCleanupResult(branch, "deleted", "already_deleted")
                )
                continue
            raise
        if current_sha not in merged_oids:
            results.append(
                BranchCleanupResult(
                    branch,
                    "skipped",
                    "merged_head_oid_mismatch",
                    current_sha,
                )
            )
            continue

        if dry_run:
            results.append(
                BranchCleanupResult(branch, "planned", "eligible", current_sha)
            )
            continue

        delete_reason = delete_remote_branch(branch, current_sha)
        if delete_reason == "lease_failed":
            results.append(
                BranchCleanupResult(branch, "skipped", delete_reason, current_sha)
            )
            continue
        results.append(
            BranchCleanupResult(branch, "deleted", delete_reason, current_sha)
        )

    return results


def close_pr(repo: str, action: CleanupAction) -> None:
    message = (
        "古い自動更新PRを整理します。\n\n"
        f"- head_ref: {action.head_ref}\n"
        f"- report_date: {action.report_date}\n"
        f"- reason: {action.reason}\n\n"
        f"<!-- auto-update-cleanup reason:{action.reason} head_ref:{action.head_ref} -->"
    )
    _run(
        [
            "gh",
            "pr",
            "close",
            str(action.number),
            "--repo",
            repo,
            "--comment",
            message,
            "--delete-branch",
        ]
    )


def render_summary(
    actions: list[CleanupAction],
    *,
    dry_run: bool,
    branch_results: list[BranchCleanupResult] | None = None,
) -> str:
    branch_results = branch_results or []
    close_count = sum(1 for item in actions if item.action == "close")
    keep_count = sum(1 for item in actions if item.action == "keep")
    lines = [
        "### Auto Update PR Cleanup",
        f"- dry_run: {str(dry_run).lower()}",
        f"- keep: {keep_count}",
        f"- close: {close_count}",
        "",
        "| PR | head_ref | report_date | age_days | action | reason |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    if not actions:
        lines.append("| なし |  |  |  |  |  |")
    for item in actions:
        lines.append(
            f"| #{item.number} | {item.head_ref} | {item.report_date} | "
            f"{item.age_days} | {item.action} | {item.reason} |"
        )
    deleted_count = sum(1 for item in branch_results if item.action == "deleted")
    planned_count = sum(1 for item in branch_results if item.action == "planned")
    skipped_count = sum(1 for item in branch_results if item.action == "skipped")
    lines.extend(
        [
            "",
            "### Auto Update Branch Cleanup",
            f"- deleted: {deleted_count}",
            f"- planned: {planned_count}",
            f"- skipped: {skipped_count}",
            "",
            "| branch | current_sha | action | reason |",
            "| --- | --- | --- | --- |",
        ]
    )
    if not branch_results:
        lines.append("| なし |  |  |  |")
    for item in branch_results:
        lines.append(
            f"| {item.branch} | {item.current_sha} | {item.action} | {item.reason} |"
        )
    return "\n".join(lines) + "\n"


def write_step_summary(text: str, path: Path | None = None) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--today", default=today_jst())
    parser.add_argument("--keep-days", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--step-summary", type=Path, default=None)
    args = parser.parse_args(argv)

    pulls = fetch_open_pulls(args.repo)
    actions = plan_cleanup(pulls, today=args.today, keep_days=args.keep_days)
    for action in actions:
        if action.action == "close":
            print(
                f"{'[dry-run] ' if args.dry_run else ''}"
                f"close PR #{action.number} {action.head_ref}: {action.reason}"
            )
            if not args.dry_run:
                close_pr(args.repo, action)
        else:
            print(f"keep PR #{action.number} {action.head_ref}: {action.reason}")

    branch_results = cleanup_merged_branches(args.repo, dry_run=args.dry_run)
    for result in branch_results:
        prefix = "[dry-run] " if result.action == "planned" else ""
        print(f"{prefix}{result.action} branch {result.branch}: {result.reason}")

    summary = render_summary(
        actions,
        dry_run=args.dry_run,
        branch_results=branch_results,
    )
    print(summary, end="")
    write_step_summary(summary, args.step_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
