"""auto-review の wait / gate / stop / report コマンド。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ms_data.gh.auto_review_pr import format_github_datetime
from ms_data.gh.outputs import append_step_summary, write_github_output

if TYPE_CHECKING:
    from ms_data.gh.auto_review_merge import GitHubClient


def _facade():
    """monkeypatch 互換のため facade モジュールを遅延参照する。"""
    from ms_data.gh import auto_review_merge as arm

    return arm


def _non_negative_int(value: str, default: int) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return default


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

    attempt 1 から ``@codex review`` を投稿する。
    初回は ``_facade().review_marker``、attempt 2 以降は ``_facade().retry_marker`` を付ける。
    PAT が使える場合は人間名義（``allowed_logins`` に PAT login を含む）を優先し、
    使えない場合は bot 名義（``_facade().GITHUB_ACTIONS_BOT`` 既定）で投稿する。
    """
    marker = (
        _facade().review_marker(args.head_sha)
        if attempt == 1
        else _facade().retry_marker(attempt, args.head_sha)
    )
    use_pat = pat_available and bool(str(args.pat_login or "").strip())
    if use_pat:
        trigger_comment_id, _, created_new = _facade().ensure_review_comment(
            client=client,
            pr_number=args.pr_number,
            marker=marker,
            allowed_logins=allowed_logins,
        )
        identity = "PAT"
    else:
        # use_trigger_token は付けず、allowed_logins も既定（_facade().GITHUB_ACTIONS_BOT）
        trigger_comment_id, _, created_new = _facade().ensure_review_comment(
            client=client,
            pr_number=args.pr_number,
            marker=marker,
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
    attempt_started = _facade().time.monotonic()
    deadline = attempt_started + attempt_timeout_seconds
    while _facade().time.monotonic() < deadline:
        metrics = _facade().collect_review_metrics(
            client=client,
            pr_number=args.pr_number,
            head_sha=args.head_sha,
            trigger_comment_ids=trigger_comment_ids,
            since=since,
        )
        total_elapsed = int(_facade().time.monotonic() - started_at)
        attempt_elapsed = int(_facade().time.monotonic() - attempt_started)
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
                _facade().time.sleep(settle_seconds)
            return True, str(total_elapsed), False

        sleep_seconds = min(
            poll_seconds, max(0, int(deadline - _facade().time.monotonic()))
        )
        if sleep_seconds <= 0:
            break
        _facade().time.sleep(sleep_seconds)
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
    """Codex のレビュー応答を待つ（attempt 1 から ``@codex review`` を投稿）。"""
    client = _facade().GitHubClient(args.repo)
    max_attempts = _facade()._positive_int(args.max_attempts, 3)
    attempt_timeout_seconds = _facade()._positive_int(args.attempt_timeout_seconds, 420)
    poll_seconds = _facade()._positive_int(args.poll_seconds, 30)
    settle_seconds = _non_negative_int(args.settle_seconds, 60)
    pat_available = _facade()._bool_text(args.pat_available)
    allowed_logins = _facade()._allowed_trigger_logins(args.pat_login)

    responded = False
    disconnected = False
    response_attempt = ""
    response_seconds = ""
    trigger_comment_ids: list[str] = []
    first_trigger_created_at = args.baseline_created_at
    started_at = _facade().time.monotonic()
    attempts_used = "0"

    for attempt in range(1, max_attempts + 1):
        attempts_used = str(attempt)
        _facade()._ensure_attempt_trigger(
            client,
            args,
            attempt,
            max_attempts,
            trigger_comment_ids,
            pat_available=pat_available,
            allowed_logins=allowed_logins,
        )
        responded, response_seconds, disconnected = _facade()._poll_for_response(
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

    _facade()._write_wait_outputs(
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
    client = _facade().GitHubClient(args.repo)
    metrics = _facade().collect_review_metrics(
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
    client = _facade().GitHubClient(args.repo)
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

    marker = _facade().stop_marker(reason_label, args.run_id, args.head_sha)
    existing = _facade().find_latest_bot_comment(
        client.issue_comments(args.pr_number), marker, {_facade().GITHUB_ACTIONS_BOT}
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
    client = _facade().GitHubClient(args.repo)
    file_comments = client.api_json(
        f"repos/{client.repo}/pulls/{args.pr_number}/comments", paginate=True
    )
    findings = _facade().extract_codex_findings(
        file_comments,
        args.head_sha,
        client.resolved_review_comment_ids(args.pr_number),
    )

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
    merge_ok = _facade()._bool_text(args.merge_ok)
    merged = _facade()._bool_text(args.merged)
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
        "generated_at": format_github_datetime(datetime.now(timezone.utc)),
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
        "findings": _facade()._int_or_none(args.findings),
        "review_complete": _facade()._bool_text(args.review_complete),
        "review": {
            "responded": _facade()._bool_text(args.responded),
            "attempts_used": _facade()._int_or_none(args.attempts_used),
            "max_attempts": _facade()._int_or_none(args.max_attempts),
            "attempt_timeout_seconds": _facade()._int_or_none(
                args.attempt_timeout_seconds
            ),
            "poll_seconds": _facade()._int_or_none(args.poll_seconds),
            "settle_seconds": _facade()._int_or_none(args.settle_seconds),
            "response_attempt": _facade()._int_or_none(args.response_attempt),
            "response_seconds": _facade()._int_or_none(args.response_seconds),
            "trigger_comment_ids": [
                item.strip()
                for item in args.trigger_comment_ids.split(",")
                if item.strip()
            ],
            "first_trigger_created_at": args.first_trigger_created_at,
        },
    }


def cmd_write_report(args: argparse.Namespace) -> int:
    report = _facade().build_auto_review_report(args)
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
