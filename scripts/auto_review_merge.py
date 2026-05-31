"""auto review merge workflow の GitHub API 操作をまとめる。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.auto_review_gate import evaluate


JST = timezone(timedelta(hours=9))
GITHUB_ACTIONS_BOT = "github-actions[bot]"


def _flatten_pages(value: Any) -> Any:
    if isinstance(value, list) and all(isinstance(page, list) for page in value):
        return [item for page in value for item in page]
    return value


def parse_json_stream(text: str) -> Any:
    text = text.strip()
    if not text:
        return []

    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    while index < len(text):
        value, index = decoder.raw_decode(text, index)
        values.append(value)
        while index < len(text) and text[index].isspace():
            index += 1
    return _flatten_pages(values[0] if len(values) == 1 else values)


def write_github_output(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={'' if value is None else value}\n")


def append_step_summary(lines: Iterable[str], path: Path | None = None) -> None:
    summary_path = path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    target = Path(summary_path)
    with target.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(f"{line}\n")


def _login(item: dict[str, Any]) -> str:
    user = item.get("user")
    if not isinstance(user, dict):
        return ""
    login = user.get("login")
    return login if isinstance(login, str) else ""


def _head_ref(item: dict[str, Any]) -> str:
    head = item.get("head")
    if not isinstance(head, dict):
        return ""
    value = head.get("ref")
    return value if isinstance(value, str) else ""


def _head_sha(item: dict[str, Any]) -> str:
    head = item.get("head")
    if not isinstance(head, dict):
        return ""
    value = head.get("sha")
    return value if isinstance(value, str) else ""


def jst_report_date(run_created_at: str) -> str:
    value = run_created_at.strip().replace("Z", "+00:00")
    created_at = datetime.fromisoformat(value)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(JST).strftime("%Y%m%d")


def resolve_target_pr(
    *,
    pulls: list[dict[str, Any]],
    run_id: str,
    run_created_at: str,
) -> dict[str, str]:
    report_date = jst_report_date(run_created_at)
    expected_head_ref = f"data/auto-update-{report_date}"
    source_marker = f"source_run_id:{run_id}"

    candidates = [
        item
        for item in pulls
        if _login(item) == GITHUB_ACTIONS_BOT
        and _head_ref(item).startswith("data/auto-update-")
        and source_marker in str(item.get("body") or "")
    ]
    if candidates:
        pr = sorted(candidates, key=lambda item: str(item.get("created_at") or ""))[-1]
        return {
            "report_date": report_date,
            "skip": "false",
            "skip_reason": "",
            "pr": str(pr.get("number") or ""),
            "head_ref": _head_ref(pr),
            "head_sha": _head_sha(pr),
            "resolved_by": "source_run_id_marker",
        }

    legacy = [
        item
        for item in pulls
        if _login(item) == GITHUB_ACTIONS_BOT
        and _head_ref(item) == expected_head_ref
        and "source_run_id:" not in str(item.get("body") or "")
    ]
    if legacy:
        pr = sorted(legacy, key=lambda item: str(item.get("created_at") or ""))[-1]
        return {
            "report_date": report_date,
            "skip": "false",
            "skip_reason": "",
            "pr": str(pr.get("number") or ""),
            "head_ref": _head_ref(pr),
            "head_sha": _head_sha(pr),
            "resolved_by": "exact_branch_legacy_no_marker",
        }

    return {
        "report_date": report_date,
        "skip": "true",
        "skip_reason": "no_target_pr",
        "pr": "",
        "head_ref": "",
        "head_sha": "",
        "resolved_by": "not_found",
    }


def review_marker(head_sha: str) -> str:
    return f"<!-- auto-review head_sha:{head_sha} -->"


def retry_marker(attempt: int, head_sha: str) -> str:
    return f"<!-- auto-review retry:{attempt} head_sha:{head_sha} -->"


def stop_marker(reason_label: str, run_id: str, head_sha: str) -> str:
    return (
        f"<!-- auto-review-stop reason:{reason_label} "
        f"run_id:{run_id} head_sha:{head_sha} -->"
    )


def find_latest_bot_comment(
    comments: list[dict[str, Any]], marker: str
) -> dict[str, Any] | None:
    matches = [
        item
        for item in comments
        if _login(item) == GITHUB_ACTIONS_BOT and marker in str(item.get("body") or "")
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: str(item.get("created_at") or ""))[-1]


@dataclass
class GitHubClient:
    repo: str

    def _run(self, args: list[str]) -> str:
        result = subprocess.run(
            args,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout

    def api_json(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        fields: dict[str, str] | None = None,
        headers: list[str] | None = None,
        paginate: bool = False,
    ) -> Any:
        cmd = ["gh", "api", endpoint]
        if method != "GET":
            cmd.extend(["-X", method])
        if paginate:
            cmd.append("--paginate")
        for header in headers or []:
            cmd.extend(["-H", header])
        for key, value in (fields or {}).items():
            cmd.extend(["-f", f"{key}={value}"])
        return parse_json_stream(self._run(cmd))

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


def ensure_review_comment(
    *,
    client: GitHubClient,
    pr_number: str,
    marker: str,
) -> tuple[str, str, bool]:
    existing = find_latest_bot_comment(client.issue_comments(pr_number), marker)
    created_new = existing is None
    if existing is None:
        comment = client.post_issue_comment(pr_number, f"@codex review\n\n{marker}")
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


def cmd_resolve_target_pr(args: argparse.Namespace) -> int:
    client = GitHubClient(args.repo)
    pulls = client.api_json(
        f"repos/{args.repo}/pulls?state=open&base=main&per_page=100"
    )
    result = resolve_target_pr(
        pulls=pulls,
        run_id=args.run_id,
        run_created_at=args.run_created_at,
    )
    write_github_output(args.github_output, result)

    if result["skip"] == "true":
        print(
            "No matching open PR found. "
            f"report_date={result['report_date']} reason={result['skip_reason']}"
        )
    else:
        print(
            f"Resolved PR #{result['pr']} "
            f"({result['head_ref']} @ {result['head_sha']}) via {result['resolved_by']}."
        )
    return 0


def cmd_trigger_review(args: argparse.Namespace) -> int:
    client = GitHubClient(args.repo)
    comment_id, created_at, created_new = ensure_review_comment(
        client=client,
        pr_number=args.pr_number,
        marker=review_marker(args.head_sha),
    )
    write_github_output(
        args.github_output,
        {
            "trigger_comment_id": comment_id,
            "trigger_created_at": created_at,
            "created_new": str(created_new).lower(),
        },
    )
    return 0


def cmd_wait_for_review(args: argparse.Namespace) -> int:
    client = GitHubClient(args.repo)
    max_attempts = _positive_int(args.max_attempts, 3)
    attempt_timeout_seconds = _positive_int(args.attempt_timeout_seconds, 420)
    poll_seconds = _positive_int(args.poll_seconds, 30)
    settle_seconds = max(0, int(args.settle_seconds))

    responded = False
    response_attempt = ""
    response_seconds = ""
    trigger_comment_ids = [args.trigger_comment_id]
    first_trigger_created_at = args.trigger_comment_created_at
    started_at = time.monotonic()

    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            trigger_comment_id = args.trigger_comment_id
            print(
                f"Codex review attempt {attempt}/{max_attempts}: "
                f"using initial trigger comment {trigger_comment_id}."
            )
        else:
            trigger_comment_id, _, created_new = ensure_review_comment(
                client=client,
                pr_number=args.pr_number,
                marker=retry_marker(attempt, args.head_sha),
            )
            if trigger_comment_id not in trigger_comment_ids:
                trigger_comment_ids.append(trigger_comment_id)
            print(
                f"Codex review attempt {attempt}/{max_attempts}: "
                f"trigger_comment_id={trigger_comment_id}, "
                f"created_new={str(created_new).lower()}."
            )

        attempt_started = time.monotonic()
        deadline = attempt_started + attempt_timeout_seconds
        while time.monotonic() < deadline:
            metrics = collect_review_metrics(
                client=client,
                pr_number=args.pr_number,
                head_sha=args.head_sha,
                trigger_comment_ids=trigger_comment_ids,
                since=first_trigger_created_at,
            )
            total_elapsed = int(time.monotonic() - started_at)
            attempt_elapsed = int(time.monotonic() - attempt_started)
            print(
                "Codex response poll: "
                f"attempt={attempt}/{max_attempts} "
                f"attempt_elapsed={attempt_elapsed}s total_elapsed={total_elapsed}s "
                f"reviews={metrics['review_count']} "
                f"findings={metrics['finding_count']} "
                f"reactions={metrics['reaction_count']} "
                f"issue_comments={metrics['issue_comment_count']} "
                f"no_issue_comments={metrics['no_issue_comment_count']} "
                f"terminal={metrics['terminal_count']} "
                f"review_complete={str(metrics['review_complete']).lower()}"
            )
            if metrics["review_complete"]:
                responded = True
                response_attempt = str(attempt)
                response_seconds = str(total_elapsed)
                if settle_seconds > 0:
                    print(
                        "Codex response detected. "
                        f"Waiting {settle_seconds}s before gate re-check."
                    )
                    time.sleep(settle_seconds)
                break

            sleep_seconds = min(poll_seconds, max(0, int(deadline - time.monotonic())))
            if sleep_seconds <= 0:
                break
            time.sleep(sleep_seconds)

        if responded:
            break

    attempts_used = response_attempt if responded else str(max_attempts)
    outputs = {
        "responded": str(responded).lower(),
        "attempts_used": attempts_used,
        "max_attempts": str(max_attempts),
        "attempt_timeout_seconds": str(attempt_timeout_seconds),
        "poll_seconds": str(poll_seconds),
        "settle_seconds": str(settle_seconds),
        "response_attempt": response_attempt,
        "response_seconds": response_seconds,
        "trigger_comment_ids": ",".join(trigger_comment_ids),
        "first_trigger_created_at": first_trigger_created_at,
    }
    write_github_output(args.github_output, outputs)
    summary = [
        "### Codex Review Response",
        f"- responded: {outputs['responded']}",
        f"- attempts_used: {attempts_used}/{max_attempts}",
        f"- attempt_timeout_seconds: {attempt_timeout_seconds}",
        f"- poll_seconds: {poll_seconds}",
        f"- settle_seconds: {settle_seconds}",
    ]
    if responded:
        summary.extend(
            [
                f"- response_attempt: {response_attempt}",
                f"- response_seconds: {response_seconds}",
            ]
        )
    summary.append(f"- trigger_comment_ids: {outputs['trigger_comment_ids']}")
    append_step_summary(summary, args.step_summary)
    return 0


def cmd_check_gate(args: argparse.Namespace) -> int:
    client = GitHubClient(args.repo)
    metrics = collect_review_metrics(
        client=client,
        pr_number=args.pr_number,
        head_sha=args.head_sha,
        trigger_comment_ids=[
            item for item in args.trigger_comment_ids.split(",") if item.strip()
        ],
        since=args.first_trigger_created_at,
    )
    merge_ok = bool(metrics["merge_ok"])
    write_github_output(
        args.github_output,
        {
            "findings": metrics["finding_count"],
            "review_complete": str(metrics["review_complete"]).lower(),
            "terminal_count": metrics["terminal_count"],
            "merge_ok": str(merge_ok).lower(),
            "stop_reason": "none" if merge_ok else metrics["stop_reason"],
        },
    )
    return 0


def cmd_record_stop(args: argparse.Namespace) -> int:
    client = GitHubClient(args.repo)
    if args.stop_reason == "no_response":
        reason_label = "codex_no_response"
        message = (
            "Codex の応答を "
            f"{args.attempts_used}/{args.max_attempts} 回試行"
            f"（各 {args.attempt_timeout_seconds} 秒）しましたが確認できなかったため、"
            f"自動マージを停止しました。手動で確認してください。 (run_id: {args.run_id})"
        )
    else:
        reason_label = "codex_findings"
        message = (
            f"Codex のファイル指摘が {args.findings} 件あるため、"
            f"自動マージを停止しました。手動で確認してください。 (run_id: {args.run_id})"
        )

    marker = stop_marker(reason_label, args.run_id, args.head_sha)
    existing = find_latest_bot_comment(client.issue_comments(args.pr_number), marker)
    posted = existing is None
    if posted:
        client.post_issue_comment(args.pr_number, f"{message}\n\n{marker}")

    summary = [
        "### Auto Review Merge",
        "- status: stopped",
        f"- reason: {reason_label}",
        f"- pr: #{args.pr_number}",
        f"- head_sha: {args.head_sha}",
    ]
    if args.stop_reason == "findings":
        summary.append(f"- findings: {args.findings}")
    summary.append(f"- comment_posted: {str(posted).lower()}")
    append_step_summary(summary, args.step_summary)
    return 0


def build_auto_review_report(args: argparse.Namespace) -> dict[str, Any]:
    merge_ok = _bool_text(args.merge_ok)
    merged = _bool_text(args.merged)
    merge_outcome = getattr(args, "merge_outcome", "") or ""
    stop_reason = args.stop_reason or "none"
    if merged:
        status = "merged"
        effective_stop_reason = "none"
    elif merge_ok and merge_outcome == "failure":
        status = "merge_failed"
        effective_stop_reason = "merge_failed"
    elif merge_ok:
        status = "merge_ready"
        effective_stop_reason = "none"
    else:
        status = "stopped"
        effective_stop_reason = stop_reason

    return {
        "schema_version": "1",
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "report_date": args.report_date,
        "source_run_id": args.run_id,
        "pr_number": args.pr_number,
        "head_ref": args.head_ref,
        "head_sha": args.head_sha,
        "status": status,
        "stop_reason": effective_stop_reason,
        "merge_ok": merge_ok,
        "merged": merged,
        "merge_outcome": merge_outcome,
        "findings": _int_or_none(args.findings),
        "review_complete": _bool_text(args.review_complete),
        "review": {
            "responded": _bool_text(args.responded),
            "attempts_used": _int_or_none(args.attempts_used),
            "max_attempts": _int_or_none(args.max_attempts),
            "attempt_timeout_seconds": _int_or_none(args.attempt_timeout_seconds),
            "poll_seconds": _int_or_none(args.poll_seconds),
            "settle_seconds": _int_or_none(args.settle_seconds),
            "response_attempt": _int_or_none(args.response_attempt),
            "response_seconds": _int_or_none(args.response_seconds),
            "trigger_comment_ids": [
                item.strip()
                for item in args.trigger_comment_ids.split(",")
                if item.strip()
            ],
            "first_trigger_created_at": args.first_trigger_created_at,
        },
    }


def cmd_write_report(args: argparse.Namespace) -> int:
    report = build_auto_review_report(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    append_step_summary(
        [
            "### Auto Review Report",
            f"- status: {report['status']}",
            f"- stop_reason: {report['stop_reason']}",
            f"- responded: {str(report['review']['responded']).lower()}",
            f"- attempts_used: {report['review']['attempts_used']}",
            f"- report: {args.out}",
        ],
        args.step_summary,
    )
    print(f"auto review report: {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve-target-pr")
    resolve.add_argument("--repo", required=True)
    resolve.add_argument("--run-id", required=True)
    resolve.add_argument("--run-created-at", required=True)
    resolve.add_argument("--github-output", type=Path, required=True)
    resolve.set_defaults(func=cmd_resolve_target_pr)

    trigger = sub.add_parser("trigger-review")
    trigger.add_argument("--repo", required=True)
    trigger.add_argument("--pr-number", required=True)
    trigger.add_argument("--head-sha", required=True)
    trigger.add_argument("--github-output", type=Path, required=True)
    trigger.set_defaults(func=cmd_trigger_review)

    wait = sub.add_parser("wait-for-review")
    wait.add_argument("--repo", required=True)
    wait.add_argument("--pr-number", required=True)
    wait.add_argument("--head-sha", required=True)
    wait.add_argument("--trigger-comment-id", required=True)
    wait.add_argument("--trigger-comment-created-at", required=True)
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
