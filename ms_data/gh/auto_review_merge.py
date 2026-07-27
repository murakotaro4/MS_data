"""auto review merge workflow の GitHub API 操作をまとめる。"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ms_data.gh.auto_review_gate import CODEX_LOGINS, evaluate
from ms_data.gh.gh_json import gh_api_json, run_gh
from ms_data.gh.gh_json import login_of as _login
from ms_data.gh.notify_review_stop import notify_review_stop
from ms_data.gh.outputs import append_step_summary, write_github_output


JST = timezone(timedelta(hours=9))
GITHUB_ACTIONS_BOT = "github-actions[bot]"
RESUME_STOP_REASONS = frozenset({"codex_no_response", "codex_disconnected"})
STOP_MARKER_RE = re.compile(
    r"<!--\s*auto-review-stop\s+reason:(\S+)\s+run_id:(\S+)\s+head_sha:(\S+)\s*-->"
)
SOURCE_RUN_ID_RE = re.compile(r"source_run_id:(\d+)")
HEAD_REF_DATE_RE = re.compile(r"^data/auto-update-(\d{8})$")


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


def _base_ref(item: dict[str, Any]) -> str:
    base = item.get("base")
    if not isinstance(base, dict):
        return ""
    value = base.get("ref")
    return value if isinstance(value, str) else ""


def _head_repo_full_name(item: dict[str, Any]) -> str:
    head = item.get("head")
    if not isinstance(head, dict):
        return ""
    repo = head.get("repo")
    if not isinstance(repo, dict):
        return ""
    value = repo.get("full_name")
    return value if isinstance(value, str) else ""


def jst_report_date(run_created_at: str) -> str:
    value = run_created_at.strip().replace("Z", "+00:00")
    created_at = datetime.fromisoformat(value)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(JST).strftime("%Y%m%d")


def report_date_from_head_ref(head_ref: str) -> str:
    match = HEAD_REF_DATE_RE.match(head_ref)
    return match.group(1) if match else ""


def parse_github_datetime(value: str) -> datetime | None:
    """GitHub API の ISO8601 日時を UTC aware datetime へ変換する。"""
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_github_datetime(value: datetime) -> str:
    """UTC datetime を ISO8601(Z) 文字列にする。"""
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def later_iso8601(*values: str) -> str:
    """複数の ISO8601 日時のうち最も遅いものを返す。"""
    parsed = [dt for value in values if (dt := parse_github_datetime(value)) is not None]
    if not parsed:
        for value in values:
            text = value.strip()
            if text:
                return text
        return ""
    return format_github_datetime(max(parsed))


def extract_commit_committer_date(commit_payload: dict[str, Any]) -> str:
    """``repos/.../commits/{sha}`` 応答から committer.date を取り出す。"""
    commit = commit_payload.get("commit")
    if not isinstance(commit, dict):
        return ""
    committer = commit.get("committer")
    if not isinstance(committer, dict):
        return ""
    value = committer.get("date")
    return value if isinstance(value, str) else ""


def fetch_commit_committer_date(client: GitHubClient, head_sha: str) -> str:
    payload = client.api_json(f"repos/{client.repo}/commits/{head_sha}")
    if not isinstance(payload, dict):
        return ""
    return extract_commit_committer_date(payload)


def latest_force_push_created_at(timeline: list[dict[str, Any]]) -> str:
    """timeline の ``head_ref_force_pushed`` イベントから最新 created_at を返す。"""
    dates = [
        str(item.get("created_at") or "")
        for item in timeline
        if item.get("event") == "head_ref_force_pushed"
        and isinstance(item.get("created_at"), str)
        and str(item.get("created_at") or "").strip()
    ]
    if not dates:
        return ""
    return later_iso8601(*dates)


def resolve_review_since(
    *,
    client: "GitHubClient",
    pr_number: str,
    pr_created_at: str,
    head_sha: str,
) -> str:
    """レビュー since を PR / HEAD committer / 最終 force-push の最遅にする。

    force-push 後に旧 HEAD 宛の no-issue コメントが新 HEAD の合格シグナルに
    ならないよう、HEAD より古い issue comment を除外するため。
    committer 日時は author 制御下のため、timeline の force-push 時刻も候補に含める。
    timeline API の失敗は握りつぶさず伝播させる。
    """
    commit_date = ""
    if head_sha:
        commit_date = fetch_commit_committer_date(client, head_sha)
    force_push_at = ""
    if pr_number:
        timeline = client.api_json(
            f"repos/{client.repo}/issues/{pr_number}/timeline",
            paginate=True,
            headers=["Accept: application/vnd.github+json"],
        )
        if not isinstance(timeline, list):
            raise RuntimeError(
                f"PR #{pr_number}: timeline API が list 以外を返しました "
                f"({type(timeline).__name__})."
            )
        force_push_at = latest_force_push_created_at(timeline)
    return later_iso8601(pr_created_at, commit_date, force_push_at)


def extract_codex_findings(
    file_comments: list[dict[str, Any]], head_sha: str
) -> list[dict[str, Any]]:
    """Codex ファイルコメントを export-findings と同形式へ整形する。"""
    findings: list[dict[str, Any]] = []
    for item in file_comments:
        if _login(item) not in CODEX_LOGINS:
            continue
        if item.get("commit_id") != head_sha:
            continue
        line = item.get("line")
        findings.append(
            {
                "path": str(item.get("path") or ""),
                "line": line if isinstance(line, int) else None,
                "body": str(item.get("body") or ""),
            }
        )
    return findings


def github_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}"


def resolve_source_run_id(body: str) -> str:
    """PR body の ``source_run_id:N`` マーカーから run id を取り出す。"""
    match = SOURCE_RUN_ID_RE.search(body or "")
    return match.group(1) if match else ""


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


def resume_marker(run_id: str, head_sha: str) -> str:
    return f"<!-- auto-review resume run_id:{run_id} head_sha:{head_sha} -->"


def recovered_marker(run_id: str, merge_sha: str, source_run_id: str) -> str:
    return (
        f"<!-- auto-review-recovered run_id:{run_id} "
        f"merge_sha:{merge_sha} source_run_id:{source_run_id} -->"
    )


def parse_stop_marker(body: str) -> dict[str, str] | None:
    """停止コメント body から reason / run_id / head_sha を取り出す。"""
    match = STOP_MARKER_RE.search(body or "")
    if not match:
        return None
    return {
        "reason": match.group(1),
        "run_id": match.group(2),
        "head_sha": match.group(3),
    }


def find_latest_bot_comment(
    comments: list[dict[str, Any]],
    marker: str,
    allowed_logins: set[str],
) -> dict[str, Any] | None:
    matches = [
        item
        for item in comments
        if _login(item) in allowed_logins and marker in str(item.get("body") or "")
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: str(item.get("created_at") or ""))[-1]


def select_resume_candidates(
    *,
    pulls: list[dict[str, Any]],
    comments_by_pr: dict[str, list[dict[str, Any]]],
    repo: str,
    max_candidates: int = 3,
) -> list[dict[str, Any]]:
    """翌朝レスキュー対象 PR を選定する（純関数）。

    - open / github-actions[bot] / ``data/auto-update-*`` / base=main / 同一 repo
    - stop マーカーは github-actions[bot] 投稿のみ受理
    - 同一 head_sha の停止マーカーのうち created_at が最新の 1 件で判定
    - 最新マーカー reason が ``codex_no_response`` / ``codex_disconnected`` のみ候補
    - report_date 降順で最大 ``max_candidates`` 件
    """
    eligible: list[dict[str, Any]] = []
    for pr in pulls:
        if _login(pr) != GITHUB_ACTIONS_BOT:
            continue
        head_ref = _head_ref(pr)
        if not head_ref.startswith("data/auto-update-"):
            continue
        if _base_ref(pr) and _base_ref(pr) != "main":
            continue
        if _head_repo_full_name(pr) and _head_repo_full_name(pr) != repo:
            continue
        head_sha = _head_sha(pr)
        pr_number = str(pr.get("number") or "")
        if not pr_number or not head_sha:
            continue
        comments = comments_by_pr.get(pr_number, [])
        matching_stops: list[tuple[str, dict[str, str]]] = []
        for comment in comments:
            if _login(comment) != GITHUB_ACTIONS_BOT:
                continue
            parsed = parse_stop_marker(str(comment.get("body") or ""))
            if parsed is None:
                continue
            if parsed["head_sha"] != head_sha:
                continue
            matching_stops.append((str(comment.get("created_at") or ""), parsed))
        if not matching_stops:
            continue
        matched = sorted(matching_stops, key=lambda item: item[0])[-1][1]
        if matched["reason"] not in RESUME_STOP_REASONS:
            continue
        report_date = report_date_from_head_ref(head_ref)
        if not report_date:
            continue
        eligible.append(
            {
                "pr_number": pr_number,
                "head_ref": head_ref,
                "head_sha": head_sha,
                "created_at": str(pr.get("created_at") or ""),
                "report_date": report_date,
                "stop_reason": matched["reason"],
                "body": str(pr.get("body") or ""),
            }
        )

    eligible.sort(key=lambda item: item["report_date"], reverse=True)
    return eligible[: max(0, max_candidates)]


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


def _run_gh_with_token(args: list[str], token: str) -> str:
    """指定 token を ``GH_TOKEN`` に差し替えて gh を実行する。"""
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    result = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return result.stdout


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
            runner=lambda cmd: _run_gh_with_token(cmd, token),
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


def cmd_establish_baseline(args: argparse.Namespace) -> int:
    """レビュー since baseline を Outputs に書き出す（コメントは投稿しない）。

    PR created_at / HEAD committer 日時 / 最終 force-push 時刻の最遅を採用する。
    HEAD より古い issue comment（force-push 前の旧 no-issue など）を除外するため。
    """
    client = GitHubClient(args.repo)
    pr = client.api_json(f"repos/{args.repo}/pulls/{args.pr_number}")
    pr_created_at = str(pr.get("created_at") or "")
    head_sha = _head_sha(pr) if isinstance(pr, dict) else ""
    baseline = resolve_review_since(
        client=client,
        pr_number=args.pr_number,
        pr_created_at=pr_created_at,
        head_sha=head_sha,
    )
    write_github_output(
        args.github_output,
        {"baseline_created_at": baseline},
    )
    print(
        f"Baseline established: baseline_created_at={baseline} "
        f"(PR #{args.pr_number}, pr_created_at={pr_created_at}, "
        f"head_sha={head_sha or '-'}; "
        "HEAD より古いコメントを除外するため committer / force-push 日時と比較)"
    )
    return 0


def _ensure_attempt_trigger(
    client: GitHubClient,
    args: argparse.Namespace,
    attempt: int,
    max_attempts: int,
    trigger_comment_ids: list[str],
    *,
    pat_available: bool,
    allowed_logins: set[str],
) -> None:
    """試行回ごとのトリガーを確保する。

    attempt 1 は Automatic review 待ちのためコメント投稿なし。
    attempt 2 以降は retry マーカー付き ``@codex review`` を投稿する。
    PAT が使える場合は人間名義（``allowed_logins`` に PAT login を含む）を優先し、
    使えない場合は bot 名義（``GITHUB_ACTIONS_BOT`` 既定）で投稿する。
    """
    if attempt == 1:
        print(
            f"Codex review attempt {attempt}/{max_attempts}: "
            "polling for Automatic review (no comment)."
        )
        return

    use_pat = pat_available and bool(str(args.pat_login or "").strip())
    if use_pat:
        trigger_comment_id, _, created_new = ensure_review_comment(
            client=client,
            pr_number=args.pr_number,
            marker=retry_marker(attempt, args.head_sha),
            allowed_logins=allowed_logins,
        )
        identity = "PAT"
    else:
        # use_trigger_token は付けず、allowed_logins も既定（GITHUB_ACTIONS_BOT）
        trigger_comment_id, _, created_new = ensure_review_comment(
            client=client,
            pr_number=args.pr_number,
            marker=retry_marker(attempt, args.head_sha),
        )
        identity = "bot"

    if trigger_comment_id not in trigger_comment_ids:
        trigger_comment_ids.append(trigger_comment_id)
    print(
        f"Codex review attempt {attempt}/{max_attempts}: "
        f"trigger_comment_id={trigger_comment_id}, "
        f"created_new={str(created_new).lower()} ({identity})."
    )


def _poll_for_response(
    client: GitHubClient,
    args: argparse.Namespace,
    *,
    attempt: int,
    max_attempts: int,
    attempt_timeout_seconds: int,
    poll_seconds: int,
    settle_seconds: int,
    trigger_comment_ids: list[str],
    since: str,
    started_at: float,
) -> tuple[bool, str, bool]:
    """1試行分のポーリングループ。

    戻り値: ``(responded, response_seconds, disconnected)``。
    応答検知時は settle_seconds だけ待ってから返る。
    ``disconnect_count > 0`` を検知したら早期打ち切り。
    """
    attempt_started = time.monotonic()
    deadline = attempt_started + attempt_timeout_seconds
    while time.monotonic() < deadline:
        metrics = collect_review_metrics(
            client=client,
            pr_number=args.pr_number,
            head_sha=args.head_sha,
            trigger_comment_ids=trigger_comment_ids,
            since=since,
        )
        total_elapsed = int(time.monotonic() - started_at)
        attempt_elapsed = int(time.monotonic() - attempt_started)
        disconnect_count = int(metrics.get("disconnect_count") or 0)
        print(
            "Codex response poll: "
            f"attempt={attempt}/{max_attempts} "
            f"attempt_elapsed={attempt_elapsed}s total_elapsed={total_elapsed}s "
            f"reviews={metrics['review_count']} "
            f"findings={metrics['finding_count']} "
            f"reactions={metrics['reaction_count']} "
            f"issue_comments={metrics['issue_comment_count']} "
            f"no_issue_comments={metrics['no_issue_comment_count']} "
            f"disconnect={disconnect_count} "
            f"terminal={metrics['terminal_count']} "
            f"review_complete={str(metrics['review_complete']).lower()}"
        )
        if disconnect_count > 0:
            print("Codex disconnect response detected; aborting wait early.")
            return False, "", True
        if metrics["review_complete"]:
            if settle_seconds > 0:
                print(
                    "Codex response detected. "
                    f"Waiting {settle_seconds}s before gate re-check."
                )
                time.sleep(settle_seconds)
            return True, str(total_elapsed), False

        sleep_seconds = min(poll_seconds, max(0, int(deadline - time.monotonic())))
        if sleep_seconds <= 0:
            break
        time.sleep(sleep_seconds)
    return False, "", False


def _write_wait_outputs(
    args: argparse.Namespace,
    *,
    responded: bool,
    disconnected: bool,
    response_attempt: str,
    response_seconds: str,
    max_attempts: int,
    attempt_timeout_seconds: int,
    poll_seconds: int,
    settle_seconds: int,
    trigger_comment_ids: list[str],
    first_trigger_created_at: str,
    attempts_used: str,
) -> None:
    """待機結果を GitHub Outputs と Step Summary に書き出す。"""
    outputs = {
        "responded": str(responded).lower(),
        "disconnected": str(disconnected).lower(),
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
        f"- disconnected: {outputs['disconnected']}",
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


def cmd_wait_for_review(args: argparse.Namespace) -> int:
    """Codex のレビュー応答を待つ（Automatic review 優先、PAT フォールバック）。"""
    client = GitHubClient(args.repo)
    max_attempts = _positive_int(args.max_attempts, 3)
    attempt_timeout_seconds = _positive_int(args.attempt_timeout_seconds, 420)
    poll_seconds = _positive_int(args.poll_seconds, 30)
    settle_seconds = max(0, int(args.settle_seconds))
    pat_available = _bool_text(args.pat_available)
    allowed_logins = _allowed_trigger_logins(args.pat_login)

    responded = False
    disconnected = False
    response_attempt = ""
    response_seconds = ""
    trigger_comment_ids: list[str] = []
    first_trigger_created_at = args.baseline_created_at
    started_at = time.monotonic()
    attempts_used = "0"

    for attempt in range(1, max_attempts + 1):
        attempts_used = str(attempt)
        _ensure_attempt_trigger(
            client,
            args,
            attempt,
            max_attempts,
            trigger_comment_ids,
            pat_available=pat_available,
            allowed_logins=allowed_logins,
        )
        responded, response_seconds, disconnected = _poll_for_response(
            client,
            args,
            attempt=attempt,
            max_attempts=max_attempts,
            attempt_timeout_seconds=attempt_timeout_seconds,
            poll_seconds=poll_seconds,
            settle_seconds=settle_seconds,
            trigger_comment_ids=trigger_comment_ids,
            since=first_trigger_created_at,
            started_at=started_at,
        )
        if disconnected:
            break
        if responded:
            response_attempt = str(attempt)
            break

    _write_wait_outputs(
        args,
        responded=responded,
        disconnected=disconnected,
        response_attempt=response_attempt,
        response_seconds=response_seconds,
        max_attempts=max_attempts,
        attempt_timeout_seconds=attempt_timeout_seconds,
        poll_seconds=poll_seconds,
        settle_seconds=settle_seconds,
        trigger_comment_ids=trigger_comment_ids,
        first_trigger_created_at=first_trigger_created_at,
        attempts_used=attempts_used,
    )
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
    elif args.stop_reason == "disconnected":
        reason_label = "codex_disconnected"
        message = (
            "Codex の連携切れ応答を検知したため、自動マージを停止しました。"
            "ChatGPT 側の GitHub コネクタが bot 投稿を認識できない状態です。"
            "https://chatgpt.com/codex/cloud/settings/connectors "
            "で接続を確認してください。"
            "この PR に手動で `@codex review` をコメントすれば、"
            "翌朝 09:00 JST の自動レスキューがマージまで回収します。"
            f" (run_id: {args.run_id})"
        )
    else:
        reason_label = "codex_findings"
        message = (
            f"Codex のファイル指摘が {args.findings} 件あるため、"
            f"自動マージを停止しました。手動で確認してください。 (run_id: {args.run_id})"
        )

    marker = stop_marker(reason_label, args.run_id, args.head_sha)
    existing = find_latest_bot_comment(
        client.issue_comments(args.pr_number), marker, {GITHUB_ACTIONS_BOT}
    )
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


def cmd_export_findings(args: argparse.Namespace) -> int:
    """Codex ファイル指摘を JSON へ書き出し、パスと件数のみ Outputs に出す。"""
    client = GitHubClient(args.repo)
    file_comments = client.api_json(
        f"repos/{client.repo}/pulls/{args.pr_number}/comments", paginate=True
    )
    findings = extract_codex_findings(file_comments, args.head_sha)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_github_output(
        args.github_output,
        {
            "findings_path": str(args.out),
            "findings_count": str(len(findings)),
        },
    )
    print(f"Exported findings: count={len(findings)} path={args.out}")
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


def _fetch_current_head_sha(client: GitHubClient, pr_number: str) -> str:
    pr = client.api_json(f"repos/{client.repo}/pulls/{pr_number}")
    return _head_sha(pr)


def _merge_and_notify(
    *,
    client: GitHubClient,
    pr_number: str,
    head_ref: str,
    evaluated_sha: str,
    source_run_id: str,
    resume_run_id: str,
) -> str:
    """評価済み SHA と一致する場合のみ merge し、notify を dispatch する。

    成功時は merge_commit_sha を返す。
    HEAD 変更・未 MERGED・merge_commit_sha 欠落は RuntimeError を送出し、
    cmd_resume を非ゼロ終了させて notify_failure に拾わせる。
    """
    current_sha = _fetch_current_head_sha(client, pr_number)
    if current_sha != evaluated_sha:
        raise RuntimeError(
            f"PR #{pr_number}: head SHA changed "
            f"({evaluated_sha} -> {current_sha}); abort resume merge."
        )

    run_gh(
        [
            "gh",
            "pr",
            "merge",
            pr_number,
            "--repo",
            client.repo,
            "--merge",
            "--delete-branch",
            "--match-head-commit",
            evaluated_sha,
        ]
    )
    view = json.loads(
        run_gh(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                client.repo,
                "--json",
                "state,mergeCommit",
            ]
        )
    )
    if str(view.get("state") or "").upper() != "MERGED":
        raise RuntimeError(
            f"PR #{pr_number}: merge did not reach MERGED state "
            f"(state={view.get('state')!r})."
        )
    merge_commit = view.get("mergeCommit")
    if isinstance(merge_commit, dict):
        merge_sha = str(merge_commit.get("oid") or "")
    else:
        merge_sha = ""
    if not merge_sha:
        raise RuntimeError(
            f"PR #{pr_number}: merge_commit_sha missing after merge."
        )

    run_gh(
        [
            "gh",
            "workflow",
            "run",
            "post_merge_notify.yml",
            "--repo",
            client.repo,
            "-f",
            f"merge_commit_sha={merge_sha}",
            "-f",
            f"head_ref={head_ref}",
            "-f",
            f"source_run_id={source_run_id}",
        ]
    )
    marker = recovered_marker(resume_run_id, merge_sha, source_run_id)
    client.post_issue_comment(
        pr_number,
        f"翌朝レスキューで自動マージしました。\n\n{marker}",
    )
    return merge_sha


def _resume_wait_for_merge_ok(
    *,
    client: GitHubClient,
    pr_number: str,
    head_sha: str,
    since: str,
    retry_wait_seconds: int,
    poll_seconds: int,
) -> dict[str, Any]:
    """resume 投稿後、指定秒数だけポーリングして最終 metrics を返す。"""
    deadline = time.monotonic() + retry_wait_seconds
    metrics = collect_review_metrics(
        client=client,
        pr_number=pr_number,
        head_sha=head_sha,
        trigger_comment_ids=[],
        since=since,
    )
    while time.monotonic() < deadline:
        if metrics.get("merge_ok"):
            return metrics
        sleep_seconds = min(poll_seconds, max(0, int(deadline - time.monotonic())))
        if sleep_seconds <= 0:
            break
        time.sleep(sleep_seconds)
        metrics = collect_review_metrics(
            client=client,
            pr_number=pr_number,
            head_sha=head_sha,
            trigger_comment_ids=[],
            since=since,
        )
    return metrics


def _metrics_has_findings(metrics: dict[str, Any]) -> bool:
    if metrics.get("stop_reason") == "findings":
        return True
    try:
        return int(metrics.get("finding_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def _handle_resume_findings(
    *,
    client: GitHubClient,
    pr_number: str,
    head_sha: str,
    report_date: str,
    resume_run_id: str,
) -> None:
    """resume 中に findings を検知したとき停止マーカー投稿とメール通知を行う。"""
    marker = stop_marker("codex_findings", resume_run_id, head_sha)
    message = (
        f"Codex のファイル指摘があるため、翌朝レスキューでの自動マージを停止しました。"
        f"手動で確認してください。 (run_id: {resume_run_id})"
    )
    existing = find_latest_bot_comment(
        client.issue_comments(pr_number), marker, {GITHUB_ACTIONS_BOT}
    )
    if existing is None:
        client.post_issue_comment(pr_number, f"{message}\n\n{marker}")

    file_comments = client.api_json(
        f"repos/{client.repo}/pulls/{pr_number}/comments", paginate=True
    )
    findings = extract_codex_findings(file_comments, head_sha)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    ) as handle:
        findings_path = Path(handle.name)
        handle.write(json.dumps(findings, ensure_ascii=False, indent=2) + "\n")

    pr_url = f"https://github.com/{client.repo}/pull/{pr_number}"
    rc = notify_review_stop(
        stop_reason="findings",
        pr_number=int(pr_number),
        pr_url=pr_url,
        report_date=report_date,
        run_url=github_run_url(),
        findings_json=findings_path,
    )
    if rc != 0:
        raise RuntimeError(
            f"PR #{pr_number}: findings 停止通知メールの送信に失敗しました "
            f"(marker は記録済み)。"
        )


def cmd_resume(args: argparse.Namespace) -> int:
    """翌朝レスキュー: no_response / disconnected で止まった PR を回収する。"""
    client = GitHubClient(args.repo)
    max_candidates = _positive_int(args.max_candidates, 3)
    retry_wait_seconds = _positive_int(args.retry_wait_seconds, 300)
    poll_seconds = _positive_int(args.poll_seconds, 30)
    pat_available = _bool_text(args.pat_available)
    pat_login = str(args.pat_login or "").strip()

    pulls = client.api_json(
        f"repos/{args.repo}/pulls?state=open&base=main&per_page=100"
    )
    comments_by_pr: dict[str, list[dict[str, Any]]] = {}
    for pr in pulls:
        pr_number = str(pr.get("number") or "")
        if not pr_number:
            continue
        head_ref = _head_ref(pr)
        if not head_ref.startswith("data/auto-update-"):
            continue
        comments_by_pr[pr_number] = client.issue_comments(pr_number)

    candidates = select_resume_candidates(
        pulls=pulls,
        comments_by_pr=comments_by_pr,
        repo=args.repo,
        max_candidates=max_candidates,
    )

    merged_count = 0
    pending_count = 0
    summary_lines = [
        "### Auto Review Resume",
        f"- candidates: {len(candidates)}",
    ]

    # 各 PR は main 基点の全量スナップショットのため、旧日 PR を後からマージすると
    # データが巻き戻る。マージ対象は最新日の 1 件だけとし、旧日分は superseded
    # として既存 cleanup のクローズに任せる。
    superseded = candidates[1:]
    candidates = candidates[:1]
    for item in superseded:
        summary_lines.append(f"- superseded(skip): #{item['pr_number']}")
        print(
            f"Resume superseded PR #{item['pr_number']} "
            f"({item['head_ref']}): newer candidate exists; leave to cleanup."
        )

    for candidate in candidates:
        pr_number = candidate["pr_number"]
        head_sha = candidate["head_sha"]
        head_ref = candidate["head_ref"]
        report_date = candidate["report_date"]
        since = resolve_review_since(
            client=client,
            pr_number=pr_number,
            pr_created_at=candidate["created_at"],
            head_sha=head_sha,
        )
        source_run_id = resolve_source_run_id(candidate["body"])
        print(
            f"Resume candidate PR #{pr_number} "
            f"({head_ref} @ {head_sha}) stop={candidate['stop_reason']} "
            f"since={since}"
        )

        metrics = collect_review_metrics(
            client=client,
            pr_number=pr_number,
            head_sha=head_sha,
            trigger_comment_ids=[],
            since=since,
        )
        if metrics.get("merge_ok"):
            merge_sha = _merge_and_notify(
                client=client,
                pr_number=pr_number,
                head_ref=head_ref,
                evaluated_sha=head_sha,
                source_run_id=source_run_id,
                resume_run_id=args.run_id,
            )
            merged_count += 1
            summary_lines.append(f"- merged: #{pr_number} ({merge_sha})")
            continue

        if _metrics_has_findings(metrics):
            _handle_resume_findings(
                client=client,
                pr_number=pr_number,
                head_sha=head_sha,
                report_date=report_date,
                resume_run_id=args.run_id,
            )
            summary_lines.append(f"- stopped_findings: #{pr_number}")
            continue

        if not (pat_available and pat_login):
            pending_count += 1
            summary_lines.append(f"- pending(no_pat): #{pr_number}")
            print(f"PR #{pr_number}: review not ready and PAT unavailable.")
            continue

        marker = resume_marker(args.run_id, head_sha)
        ensure_review_comment(
            client=client,
            pr_number=pr_number,
            marker=marker,
            allowed_logins=_allowed_trigger_logins(pat_login),
            use_trigger_token=True,
        )
        metrics = _resume_wait_for_merge_ok(
            client=client,
            pr_number=pr_number,
            head_sha=head_sha,
            since=since,
            retry_wait_seconds=retry_wait_seconds,
            poll_seconds=poll_seconds,
        )
        if metrics.get("merge_ok"):
            merge_sha = _merge_and_notify(
                client=client,
                pr_number=pr_number,
                head_ref=head_ref,
                evaluated_sha=head_sha,
                source_run_id=source_run_id,
                resume_run_id=args.run_id,
            )
            merged_count += 1
            summary_lines.append(f"- merged_after_retry: #{pr_number} ({merge_sha})")
        elif _metrics_has_findings(metrics):
            _handle_resume_findings(
                client=client,
                pr_number=pr_number,
                head_sha=head_sha,
                report_date=report_date,
                resume_run_id=args.run_id,
            )
            summary_lines.append(f"- stopped_findings: #{pr_number}")
        else:
            pending_count += 1
            summary_lines.append(f"- pending(no_response): #{pr_number}")
            print(f"PR #{pr_number}: still no mergeable Codex response after retry.")

    write_github_output(
        args.github_output,
        {
            "processed": str(len(candidates)),
            "merged_count": str(merged_count),
            "pending_count": str(pending_count),
        },
    )
    summary_lines.extend(
        [
            f"- processed: {len(candidates)}",
            f"- merged_count: {merged_count}",
            f"- pending_count: {pending_count}",
        ]
    )
    append_step_summary(summary_lines, args.step_summary)
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
