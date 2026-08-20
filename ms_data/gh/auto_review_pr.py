"""auto-review の PR / baseline / since 解決。"""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ms_data.core.dates import JST
from ms_data.gh.auto_review_gate import CODEX_LOGINS, finding_commit_sha
from ms_data.gh.auto_review_markers import parse_stop_marker
from ms_data.gh.gh_json import login_of as _login
from ms_data.gh.outputs import write_github_output

if TYPE_CHECKING:
    from ms_data.gh.auto_review_merge import GitHubClient

GITHUB_ACTIONS_BOT = "github-actions[bot]"
RESUME_STOP_REASONS = frozenset({"codex_no_response", "codex_disconnected"})
SOURCE_RUN_ID_RE = re.compile(r"source_run_id:(\d+)")
HEAD_REF_DATE_RE = re.compile(r"^data/auto-update-(\d{8})$")


def _facade():
    """monkeypatch 互換のため facade モジュールを遅延参照する。"""
    from ms_data.gh import auto_review_merge as arm

    return arm


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
    parsed = [
        dt for value in values if (dt := parse_github_datetime(value)) is not None
    ]
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
        commit_date = _facade().fetch_commit_committer_date(client, head_sha)
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
        force_push_at = _facade().latest_force_push_created_at(timeline)
    return _facade().later_iso8601(pr_created_at, commit_date, force_push_at)


def extract_codex_findings(
    file_comments: list[dict[str, Any]], head_sha: str
) -> list[dict[str, Any]]:
    """Codex ファイルコメントを export-findings と同形式へ整形する。"""
    findings: list[dict[str, Any]] = []
    for item in file_comments:
        if _login(item) not in CODEX_LOGINS:
            continue
        if finding_commit_sha(item) != head_sha:
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


def cmd_resolve_target_pr(args: argparse.Namespace) -> int:
    client = _facade().GitHubClient(args.repo)
    pulls = client.api_json(
        f"repos/{args.repo}/pulls?state=open&base=main&per_page=100"
    )
    result = _facade().resolve_target_pr(
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
    client = _facade().GitHubClient(args.repo)
    pr = client.api_json(f"repos/{args.repo}/pulls/{args.pr_number}")
    pr_created_at = str(pr.get("created_at") or "")
    head_sha = _facade()._head_sha(pr) if isinstance(pr, dict) else ""
    baseline = _facade().resolve_review_since(
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
