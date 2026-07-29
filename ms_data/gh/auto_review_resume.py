"""auto-review の resume / merge コマンド。"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ms_data.gh.outputs import append_step_summary, write_github_output

if TYPE_CHECKING:
    from ms_data.gh.auto_review_merge import GitHubClient


def _facade():
    """monkeypatch 互換のため facade モジュールを遅延参照する。"""
    from ms_data.gh import auto_review_merge as arm

    return arm


def _fetch_current_head_sha(client: GitHubClient, pr_number: str) -> str:
    pr = client.api_json(f"repos/{client.repo}/pulls/{pr_number}")
    return _facade()._head_sha(pr)


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
    current_sha = _facade()._fetch_current_head_sha(client, pr_number)
    if current_sha != evaluated_sha:
        raise RuntimeError(
            f"PR #{pr_number}: head SHA changed "
            f"({evaluated_sha} -> {current_sha}); abort resume merge."
        )

    _facade().run_gh(
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
        _facade().run_gh(
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
        raise RuntimeError(f"PR #{pr_number}: merge_commit_sha missing after merge.")

    _facade().run_gh(
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
    marker = _facade().recovered_marker(resume_run_id, merge_sha, source_run_id)
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
    deadline = _facade().time.monotonic() + retry_wait_seconds
    metrics = _facade().collect_review_metrics(
        client=client,
        pr_number=pr_number,
        head_sha=head_sha,
        trigger_comment_ids=[],
        since=since,
    )
    while _facade().time.monotonic() < deadline:
        if metrics.get("merge_ok"):
            return metrics
        sleep_seconds = min(
            poll_seconds, max(0, int(deadline - _facade().time.monotonic()))
        )
        if sleep_seconds <= 0:
            break
        _facade().time.sleep(sleep_seconds)
        metrics = _facade().collect_review_metrics(
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
    marker = _facade().stop_marker("codex_findings", resume_run_id, head_sha)
    message = (
        f"Codex のファイル指摘があるため、翌朝レスキューでの自動マージを停止しました。"
        f"手動で確認してください。 (run_id: {resume_run_id})"
    )
    existing = _facade().find_latest_bot_comment(
        client.issue_comments(pr_number), marker, {_facade().GITHUB_ACTIONS_BOT}
    )
    if existing is None:
        client.post_issue_comment(pr_number, f"{message}\n\n{marker}")

    file_comments = client.api_json(
        f"repos/{client.repo}/pulls/{pr_number}/comments", paginate=True
    )
    findings = _facade().extract_codex_findings(file_comments, head_sha)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    ) as handle:
        findings_path = Path(handle.name)
        handle.write(json.dumps(findings, ensure_ascii=False, indent=2) + "\n")

    pr_url = f"https://github.com/{client.repo}/pull/{pr_number}"
    rc = _facade().notify_review_stop(
        stop_reason="findings",
        pr_number=int(pr_number),
        pr_url=pr_url,
        report_date=report_date,
        run_url=_facade().github_run_url(),
        findings_json=findings_path,
    )
    if rc != 0:
        raise RuntimeError(
            f"PR #{pr_number}: findings 停止通知メールの送信に失敗しました "
            f"(marker は記録済み)。"
        )


def cmd_resume(args: argparse.Namespace) -> int:
    """翌朝レスキュー: no_response / disconnected で止まった PR を回収する。"""
    client = _facade().GitHubClient(args.repo)
    max_candidates = _facade()._positive_int(args.max_candidates, 3)
    retry_wait_seconds = _facade()._positive_int(args.retry_wait_seconds, 300)
    poll_seconds = _facade()._positive_int(args.poll_seconds, 30)
    pat_available = _facade()._bool_text(args.pat_available)
    pat_login = str(args.pat_login or "").strip()

    pulls = client.api_json(
        f"repos/{args.repo}/pulls?state=open&base=main&per_page=100"
    )
    comments_by_pr: dict[str, list[dict[str, Any]]] = {}
    for pr in pulls:
        pr_number = str(pr.get("number") or "")
        if not pr_number:
            continue
        head_ref = _facade()._head_ref(pr)
        if not head_ref.startswith("data/auto-update-"):
            continue
        comments_by_pr[pr_number] = client.issue_comments(pr_number)

    candidates = _facade().select_resume_candidates(
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
        since = _facade().resolve_review_since(
            client=client,
            pr_number=pr_number,
            pr_created_at=candidate["created_at"],
            head_sha=head_sha,
        )
        source_run_id = _facade().resolve_source_run_id(candidate["body"])
        print(
            f"Resume candidate PR #{pr_number} "
            f"({head_ref} @ {head_sha}) stop={candidate['stop_reason']} "
            f"since={since}"
        )

        metrics = _facade().collect_review_metrics(
            client=client,
            pr_number=pr_number,
            head_sha=head_sha,
            trigger_comment_ids=[],
            since=since,
        )
        if metrics.get("merge_ok"):
            merge_sha = _facade()._merge_and_notify(
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

        if _facade()._metrics_has_findings(metrics):
            _facade()._handle_resume_findings(
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

        marker = _facade().resume_marker(args.run_id, head_sha)
        _facade().ensure_review_comment(
            client=client,
            pr_number=pr_number,
            marker=marker,
            allowed_logins=_facade()._allowed_trigger_logins(pat_login),
            use_trigger_token=True,
        )
        metrics = _facade()._resume_wait_for_merge_ok(
            client=client,
            pr_number=pr_number,
            head_sha=head_sha,
            since=since,
            retry_wait_seconds=retry_wait_seconds,
            poll_seconds=poll_seconds,
        )
        if metrics.get("merge_ok"):
            merge_sha = _facade()._merge_and_notify(
                client=client,
                pr_number=pr_number,
                head_ref=head_ref,
                evaluated_sha=head_sha,
                source_run_id=source_run_id,
                resume_run_id=args.run_id,
            )
            merged_count += 1
            summary_lines.append(f"- merged_after_retry: #{pr_number} ({merge_sha})")
        elif _facade()._metrics_has_findings(metrics):
            _facade()._handle_resume_findings(
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
