"""auto-review の resume / merge コマンド。"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ms_data.gh.argtypes import (
    GITHUB_ACTIONS_BOT,
    ReviewDeps,
    _allowed_trigger_logins,
    _bool_text,
    _positive_int,
)
from ms_data.gh.auto_review_markers import (
    find_latest_bot_comment,
    resume_marker,
    stop_marker,
)
from ms_data.gh.auto_review_pr import (
    _head_ref,
    extract_codex_findings,
    resolve_review_since,
    resolve_source_run_id,
    select_resume_candidates,
)
from ms_data.gh.outputs import append_step_summary, write_github_output

if TYPE_CHECKING:
    from ms_data.gh.auto_review_merge import GitHubClient


def _merge_and_notify(
    *,
    client: GitHubClient,
    pr_number: str,
    head_ref: str,
    evaluated_sha: str,
    source_run_id: str,
    resume_run_id: str,
    deps: ReviewDeps,
) -> str:
    """共通 merge 契約で resume マージと通知を実行する。"""
    # auto_review_merge は本モジュールを再公開するため遅延 import する。
    from ms_data.gh.auto_review_merge import (
        dispatch_post_merge_notify,
        merge_pull_request,
        post_recovered_comment,
    )

    result = merge_pull_request(
        repo=client.repo,
        pr_number=pr_number,
        head_ref=head_ref,
        head_sha=evaluated_sha,
        deps=deps,
    )
    if not result.merged:
        if result.skip_reason == "not_open":
            return ""
        raise RuntimeError(
            f"PR #{pr_number}: resume merge failed "
            f"(reason={result.skip_reason}, state={result.pr_state})."
        )
    dispatch_post_merge_notify(
        repo=client.repo,
        merge_commit_sha=result.merge_commit_sha,
        head_ref=result.head_ref,
        source_run_id=source_run_id,
        deps=deps,
    )
    post_recovered_comment(
        repo=client.repo,
        pr_number=pr_number,
        run_id=resume_run_id,
        merge_commit_sha=result.merge_commit_sha,
        source_run_id=source_run_id,
        deps=deps,
    )
    return result.merge_commit_sha


def _resume_wait_for_merge_ok(
    *,
    client: GitHubClient,
    pr_number: str,
    head_sha: str,
    since: str,
    retry_wait_seconds: int,
    poll_seconds: int,
    deps: ReviewDeps,
) -> dict[str, Any]:
    """resume 投稿後、指定秒数だけポーリングして最終 metrics を返す。"""
    deadline = deps.clock.monotonic() + retry_wait_seconds
    metrics = deps.collect_metrics(
        client=client,
        pr_number=pr_number,
        head_sha=head_sha,
        trigger_comment_ids=[],
        since=since,
    )
    while deps.clock.monotonic() < deadline:
        if metrics.get("merge_ok"):
            return metrics
        sleep_seconds = min(
            poll_seconds, max(0, int(deadline - deps.clock.monotonic()))
        )
        if sleep_seconds <= 0:
            break
        deps.clock.sleep(sleep_seconds)
        metrics = deps.collect_metrics(
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
    deps: ReviewDeps,
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
    findings = extract_codex_findings(
        file_comments,
        head_sha,
        client.resolved_review_comment_ids(pr_number),
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    ) as handle:
        findings_path = Path(handle.name)
        handle.write(json.dumps(findings, ensure_ascii=False, indent=2) + "\n")

    pr_url = f"https://github.com/{client.repo}/pull/{pr_number}"
    rc = deps.notify_stop(
        stop_reason="findings",
        pr_number=int(pr_number),
        pr_url=pr_url,
        report_date=report_date,
        run_url=deps.run_url(),
        findings_json=findings_path,
    )
    if rc != 0:
        raise RuntimeError(
            f"PR #{pr_number}: findings 停止通知メールの送信に失敗しました "
            f"(marker は記録済み)。"
        )


@dataclass(frozen=True)
class ResumeParams:
    """cmd_resume の実行パラメータ（argparse から正規化済み）。"""

    run_id: str
    retry_wait_seconds: int
    poll_seconds: int
    pat_available: bool
    pat_login: str

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> ResumeParams:
        return cls(
            run_id=str(args.run_id),
            retry_wait_seconds=_positive_int(args.retry_wait_seconds, 300),
            poll_seconds=_positive_int(args.poll_seconds, 30),
            pat_available=_bool_text(args.pat_available),
            pat_login=str(args.pat_login or "").strip(),
        )

    @property
    def can_retrigger(self) -> bool:
        return self.pat_available and bool(self.pat_login)


@dataclass(frozen=True)
class ResumeOutcome:
    """候補 1 件の処理結果。summary_line は Step Summary にそのまま載せる。"""

    kind: str  # merged / merge_skipped / stopped_findings / pending
    summary_line: str


def _collect_resume_candidates(
    *, client: GitHubClient, repo: str, max_candidates: int
) -> list[dict[str, Any]]:
    """open な自動更新 PR とそのコメントを集め、resume 候補を選ぶ。"""
    pulls = client.api_json(f"repos/{repo}/pulls?state=open&base=main&per_page=100")
    comments_by_pr: dict[str, list[dict[str, Any]]] = {}
    for pr in pulls:
        pr_number = str(pr.get("number") or "")
        if not pr_number:
            continue
        head_ref = _head_ref(pr)
        if not head_ref.startswith("data/auto-update-"):
            continue
        comments_by_pr[pr_number] = client.issue_comments(pr_number)

    return select_resume_candidates(
        pulls=pulls,
        comments_by_pr=comments_by_pr,
        repo=repo,
        max_candidates=max_candidates,
    )


def _merge_outcome(
    *,
    client: GitHubClient,
    candidate: dict[str, Any],
    source_run_id: str,
    params: ResumeParams,
    deps: ReviewDeps,
    label: str,
) -> ResumeOutcome:
    """merge_ok な候補をマージし、結果を outcome に変換する。"""
    pr_number = candidate["pr_number"]
    merge_sha = _merge_and_notify(
        client=client,
        pr_number=pr_number,
        head_ref=candidate["head_ref"],
        evaluated_sha=candidate["head_sha"],
        source_run_id=source_run_id,
        resume_run_id=params.run_id,
        deps=deps,
    )
    if not merge_sha:
        return ResumeOutcome(
            "merge_skipped", f"- merge_skipped(not_open): #{pr_number}"
        )
    return ResumeOutcome("merged", f"- {label}: #{pr_number} ({merge_sha})")


def _findings_outcome(
    *,
    client: GitHubClient,
    candidate: dict[str, Any],
    params: ResumeParams,
    deps: ReviewDeps,
) -> ResumeOutcome:
    _handle_resume_findings(
        client=client,
        pr_number=candidate["pr_number"],
        head_sha=candidate["head_sha"],
        report_date=candidate["report_date"],
        resume_run_id=params.run_id,
        deps=deps,
    )
    return ResumeOutcome(
        "stopped_findings", f"- stopped_findings: #{candidate['pr_number']}"
    )


def _retrigger_and_wait(
    *,
    client: GitHubClient,
    candidate: dict[str, Any],
    since: str,
    params: ResumeParams,
    deps: ReviewDeps,
) -> dict[str, Any]:
    """PAT 名義で `@codex review` を再投稿し、merge_ok になるまで待つ。"""
    head_sha = candidate["head_sha"]
    deps.ensure_comment(
        client=client,
        pr_number=candidate["pr_number"],
        marker=resume_marker(params.run_id, head_sha),
        allowed_logins=_allowed_trigger_logins(params.pat_login),
        use_trigger_token=True,
    )
    return _resume_wait_for_merge_ok(
        client=client,
        pr_number=candidate["pr_number"],
        head_sha=head_sha,
        since=since,
        retry_wait_seconds=params.retry_wait_seconds,
        poll_seconds=params.poll_seconds,
        deps=deps,
    )


def _process_resume_candidate(
    *,
    client: GitHubClient,
    candidate: dict[str, Any],
    params: ResumeParams,
    deps: ReviewDeps,
) -> ResumeOutcome:
    """候補 1 件を「即マージ → findings → 再トリガー待ち」の順で処理する。"""
    pr_number = candidate["pr_number"]
    head_sha = candidate["head_sha"]
    since = resolve_review_since(
        client=client,
        pr_number=pr_number,
        pr_created_at=candidate["created_at"],
        head_sha=head_sha,
    )
    source_run_id = resolve_source_run_id(candidate["body"])
    print(
        f"Resume candidate PR #{pr_number} "
        f"({candidate['head_ref']} @ {head_sha}) stop={candidate['stop_reason']} "
        f"since={since}"
    )

    metrics = deps.collect_metrics(
        client=client,
        pr_number=pr_number,
        head_sha=head_sha,
        trigger_comment_ids=[],
        since=since,
    )
    if metrics.get("merge_ok"):
        return _merge_outcome(
            client=client,
            candidate=candidate,
            source_run_id=source_run_id,
            params=params,
            deps=deps,
            label="merged",
        )
    if _metrics_has_findings(metrics):
        return _findings_outcome(
            client=client, candidate=candidate, params=params, deps=deps
        )
    if not params.can_retrigger:
        print(f"PR #{pr_number}: review not ready and PAT unavailable.")
        return ResumeOutcome("pending", f"- pending(no_pat): #{pr_number}")

    metrics = _retrigger_and_wait(
        client=client, candidate=candidate, since=since, params=params, deps=deps
    )
    if metrics.get("merge_ok"):
        return _merge_outcome(
            client=client,
            candidate=candidate,
            source_run_id=source_run_id,
            params=params,
            deps=deps,
            label="merged_after_retry",
        )
    if _metrics_has_findings(metrics):
        return _findings_outcome(
            client=client, candidate=candidate, params=params, deps=deps
        )
    print(f"PR #{pr_number}: still no mergeable Codex response after retry.")
    return ResumeOutcome("pending", f"- pending(no_response): #{pr_number}")


def cmd_resume(args: argparse.Namespace, deps: ReviewDeps) -> int:
    """翌朝レスキュー: no_response / disconnected で止まった PR を回収する。"""
    client = deps.client(args.repo)
    params = ResumeParams.from_args(args)

    candidates = _collect_resume_candidates(
        client=client,
        repo=args.repo,
        max_candidates=_positive_int(args.max_candidates, 3),
    )

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

    merged_count = 0
    pending_count = 0
    for candidate in candidates:
        outcome = _process_resume_candidate(
            client=client, candidate=candidate, params=params, deps=deps
        )
        summary_lines.append(outcome.summary_line)
        if outcome.kind == "merged":
            merged_count += 1
        elif outcome.kind == "pending":
            pending_count += 1

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
