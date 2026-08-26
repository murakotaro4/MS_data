"""auto review merge workflow の CLI facade。

実装は責務別に分割し、本モジュールは後方互換の公開面と CLI 入口を維持する。
テストの monkeypatch 対象（GitHubClient / time / collect_review_metrics 等）もここに残す。
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ms_data.core.dates import JST
from ms_data.gh.auto_review_gate import evaluate
from ms_data.gh.auto_review_markers import (
    find_latest_bot_comment,
    recovered_marker,
    resume_marker,
    retry_marker,
    review_marker,
    stop_marker,
)
from ms_data.gh.auto_review_pr import (
    _head_ref,
    _head_sha,
    cmd_establish_baseline,
    cmd_resolve_target_pr,
    extract_codex_findings,
    fetch_commit_committer_date,
    fetch_resolved_review_comment_ids,
    resolved_comment_ids_from_graphql,
    github_run_url,
    jst_report_date,
    latest_force_push_created_at,
    later_iso8601,
    resolve_review_since,
    resolve_source_run_id,
    resolve_target_pr,
    select_resume_candidates,
)
from ms_data.gh.auto_review_resume import (
    _fetch_current_head_sha,
    _handle_resume_findings,
    _merge_and_notify,
    _metrics_has_findings,
    _resume_wait_for_merge_ok,
    cmd_resume,
)
from ms_data.gh.auto_review_wait import (
    _ensure_attempt_trigger,
    _poll_for_response,
    _write_wait_outputs,
    build_auto_review_report,
    cmd_check_gate,
    cmd_export_findings,
    cmd_record_stop,
    cmd_wait_for_review,
    cmd_write_report,
)
from ms_data.gh.gh_json import gh_api_json, run_gh
from ms_data.gh.notify_review_stop import notify_review_stop

__all__ = [
    "GITHUB_ACTIONS_BOT",
    "GitHubClient",
    "JST",
    "_allowed_trigger_logins",
    "_bool_text",
    "_ensure_attempt_trigger",
    "_fetch_current_head_sha",
    "_handle_resume_findings",
    "_head_ref",
    "_head_sha",
    "_int_or_none",
    "_merge_and_notify",
    "_metrics_has_findings",
    "_poll_for_response",
    "_positive_int",
    "_resume_wait_for_merge_ok",
    "_write_wait_outputs",
    "build_auto_review_report",
    "build_parser",
    "cmd_check_gate",
    "cmd_establish_baseline",
    "cmd_export_findings",
    "cmd_record_stop",
    "cmd_resolve_target_pr",
    "cmd_resume",
    "cmd_wait_for_review",
    "cmd_write_report",
    "collect_review_metrics",
    "ensure_review_comment",
    "extract_codex_findings",
    "fetch_commit_committer_date",
    "fetch_resolved_review_comment_ids",
    "find_latest_bot_comment",
    "github_run_url",
    "jst_report_date",
    "later_iso8601",
    "latest_force_push_created_at",
    "main",
    "notify_review_stop",
    "post_codex_trigger_comment",
    "recovered_marker",
    "resolve_review_since",
    "resolve_source_run_id",
    "resolve_target_pr",
    "resolved_comment_ids_from_graphql",
    "resume_marker",
    "retry_marker",
    "review_marker",
    "run_gh",
    "select_resume_candidates",
    "stop_marker",
    "time",
]

GITHUB_ACTIONS_BOT = "github-actions[bot]"


@dataclass
class GitHubClient:
    repo: str

    def _run(self, args: list[str]) -> str:
        return run_gh(args)

    def api_json(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        fields: dict[str, str] | None = None,
        headers: list[str] | None = None,
        paginate: bool = False,
    ) -> Any:
        return gh_api_json(
            endpoint,
            method=method,
            fields=fields,
            headers=headers,
            paginate=paginate,
            runner=self._run,
        )

    def issue_comments(self, pr_number: str) -> list[dict[str, Any]]:
        return self.api_json(
            f"repos/{self.repo}/issues/{pr_number}/comments", paginate=True
        )

    def post_issue_comment(self, pr_number: str, body: str) -> dict[str, Any]:
        return self.api_json(
            f"repos/{self.repo}/issues/{pr_number}/comments",
            method="POST",
            fields={"body": body},
        )

    def issue_comment(self, comment_id: str) -> dict[str, Any]:
        return self.api_json(f"repos/{self.repo}/issues/comments/{comment_id}")

    def issue_timeline(self, pr_number: str) -> list[dict[str, Any]]:
        return self.api_json(
            f"repos/{self.repo}/issues/{pr_number}/timeline",
            paginate=True,
            headers=["Accept: application/vnd.github+json"],
        )

    def resolved_review_comment_ids(self, pr_number: str) -> set[str]:
        """解決済みレビュースレッドに属するコメント ID を返す。"""
        if "/" not in self.repo:
            raise ValueError(f"invalid repo: {self.repo}")
        if not str(pr_number).isdigit():
            raise ValueError(f"invalid pr_number: {pr_number}")
        owner, name = self.repo.split("/", 1)
        return fetch_resolved_review_comment_ids(
            owner=owner,
            name=name,
            pr_number=int(pr_number),
            graphql=lambda query: self.api_json(
                "graphql", method="POST", fields={"query": query}
            ),
        )


def post_codex_trigger_comment(
    *,
    repo: str,
    pr_number: str,
    body: str,
) -> dict[str, Any]:
    """``@codex review`` 投稿。``CODEX_TRIGGER_TOKEN`` があればそれで投稿する。"""
    token = os.environ.get("CODEX_TRIGGER_TOKEN", "").strip()
    if token:
        return gh_api_json(
            f"repos/{repo}/issues/{pr_number}/comments",
            method="POST",
            fields={"body": body},
            runner=lambda cmd: run_gh(cmd, env_overrides={"GH_TOKEN": token}),
        )
    return gh_api_json(
        f"repos/{repo}/issues/{pr_number}/comments",
        method="POST",
        fields={"body": body},
    )


def ensure_review_comment(
    *,
    client: GitHubClient,
    pr_number: str,
    marker: str,
    allowed_logins: set[str] | None = None,
    use_trigger_token: bool = False,
) -> tuple[str, str, bool]:
    logins = allowed_logins if allowed_logins is not None else {GITHUB_ACTIONS_BOT}
    existing = find_latest_bot_comment(client.issue_comments(pr_number), marker, logins)
    created_new = existing is None
    if existing is None:
        body = f"@codex review\n\n{marker}"
        if use_trigger_token:
            comment = post_codex_trigger_comment(
                repo=client.repo, pr_number=pr_number, body=body
            )
        else:
            comment = client.post_issue_comment(pr_number, body)
    else:
        comment = existing

    comment_id = str(comment.get("id") or "")
    detail = client.issue_comment(comment_id)
    created_at = str(detail.get("created_at") or comment.get("created_at") or "")
    return comment_id, created_at, created_new


def collect_review_metrics(
    *,
    client: GitHubClient,
    pr_number: str,
    head_sha: str,
    trigger_comment_ids: list[str],
    since: str,
) -> dict[str, Any]:
    reviews = client.api_json(
        f"repos/{client.repo}/pulls/{pr_number}/reviews", paginate=True
    )
    file_comments = client.api_json(
        f"repos/{client.repo}/pulls/{pr_number}/comments", paginate=True
    )
    issue_comments = client.issue_comments(pr_number)
    reactions: list[dict[str, Any]] = []
    for comment_id in trigger_comment_ids:
        reactions.extend(
            client.api_json(
                f"repos/{client.repo}/issues/comments/{comment_id}/reactions",
                paginate=True,
                headers=["Accept: application/vnd.github+json"],
            )
        )

    return evaluate(
        reviews=reviews,
        file_comments=file_comments,
        issue_comments=issue_comments,
        reactions=reactions,
        head_sha=head_sha,
        since=since,
        resolved_comment_ids=client.resolved_review_comment_ids(pr_number),
    )


def _positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _bool_text(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_or_none(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _allowed_trigger_logins(pat_login: str) -> set[str]:
    logins = {GITHUB_ACTIONS_BOT}
    login = pat_login.strip()
    if login:
        logins.add(login)
    return logins


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve-target-pr")
    resolve.add_argument("--repo", required=True)
    resolve.add_argument("--run-id", required=True)
    resolve.add_argument("--run-created-at", required=True)
    resolve.add_argument("--github-output", type=Path, required=True)
    resolve.set_defaults(func=cmd_resolve_target_pr)

    baseline = sub.add_parser("establish-baseline")
    baseline.add_argument("--repo", required=True)
    baseline.add_argument("--pr-number", required=True)
    baseline.add_argument("--github-output", type=Path, required=True)
    baseline.set_defaults(func=cmd_establish_baseline)

    wait = sub.add_parser("wait-for-review")
    wait.add_argument("--repo", required=True)
    wait.add_argument("--pr-number", required=True)
    wait.add_argument("--head-sha", required=True)
    wait.add_argument("--baseline-created-at", required=True)
    wait.add_argument("--pat-available", required=True)
    wait.add_argument("--pat-login", default="")
    wait.add_argument("--max-attempts", required=True)
    wait.add_argument("--attempt-timeout-seconds", required=True)
    wait.add_argument("--poll-seconds", required=True)
    wait.add_argument("--settle-seconds", required=True)
    wait.add_argument("--github-output", type=Path, required=True)
    wait.add_argument("--step-summary", type=Path, default=None)
    wait.set_defaults(func=cmd_wait_for_review)

    gate = sub.add_parser("check-gate")
    gate.add_argument("--repo", required=True)
    gate.add_argument("--pr-number", required=True)
    gate.add_argument("--head-sha", required=True)
    gate.add_argument("--trigger-comment-ids", required=True)
    gate.add_argument("--first-trigger-created-at", required=True)
    gate.add_argument("--github-output", type=Path, required=True)
    gate.set_defaults(func=cmd_check_gate)

    record = sub.add_parser("record-stop")
    record.add_argument("--repo", required=True)
    record.add_argument("--pr-number", required=True)
    record.add_argument("--head-sha", required=True)
    record.add_argument("--findings", required=True)
    record.add_argument("--stop-reason", required=True)
    record.add_argument("--run-id", required=True)
    record.add_argument("--attempts-used", required=True)
    record.add_argument("--max-attempts", required=True)
    record.add_argument("--attempt-timeout-seconds", required=True)
    record.add_argument("--step-summary", type=Path, default=None)
    record.set_defaults(func=cmd_record_stop)

    export = sub.add_parser("export-findings")
    export.add_argument("--repo", required=True)
    export.add_argument("--pr-number", required=True)
    export.add_argument("--head-sha", required=True)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--github-output", type=Path, required=True)
    export.set_defaults(func=cmd_export_findings)

    resume = sub.add_parser("resume")
    resume.add_argument("--repo", required=True)
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--pat-available", required=True)
    resume.add_argument("--pat-login", default="")
    resume.add_argument("--max-candidates", default="3")
    resume.add_argument("--retry-wait-seconds", default="300")
    resume.add_argument("--poll-seconds", default="30")
    resume.add_argument("--github-output", type=Path, required=True)
    resume.add_argument("--step-summary", type=Path, default=None)
    resume.set_defaults(func=cmd_resume)

    report = sub.add_parser("write-report")
    report.add_argument("--report-date", required=True)
    report.add_argument("--run-id", required=True)
    report.add_argument("--pr-number", required=True)
    report.add_argument("--head-ref", required=True)
    report.add_argument("--head-sha", required=True)
    report.add_argument("--responded", default="")
    report.add_argument("--attempts-used", default="")
    report.add_argument("--max-attempts", default="")
    report.add_argument("--attempt-timeout-seconds", default="")
    report.add_argument("--poll-seconds", default="")
    report.add_argument("--settle-seconds", default="")
    report.add_argument("--response-attempt", default="")
    report.add_argument("--response-seconds", default="")
    report.add_argument("--trigger-comment-ids", default="")
    report.add_argument("--first-trigger-created-at", default="")
    report.add_argument("--findings", default="")
    report.add_argument("--review-complete", default="")
    report.add_argument("--merge-ok", default="")
    report.add_argument("--merged", default="")
    report.add_argument("--merge-outcome", default="")
    report.add_argument("--stop-reason", default="")
    report.add_argument("--out", type=Path, required=True)
    report.add_argument("--step-summary", type=Path, default=None)
    report.set_defaults(func=cmd_write_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
