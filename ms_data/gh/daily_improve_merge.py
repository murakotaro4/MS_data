"""「毎日の改善」PR をラベル起動でゲート再確認のうえマージする。

ルーティン（Claude）はマージ前ゲートを満たした PR にラベルを付けるだけにし、
マージは Actions の ``github.token`` で行う。Codex 判定は auto review と同じ
``evaluate`` 基準、CI 判定とマージは共通 merge 経路（``merge_pull_request``）を使う。
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ms_data.gh import pr_payload
from ms_data.gh.argtypes import ReviewDeps
from ms_data.gh.auto_review_merge import merge_pull_request
from ms_data.gh.auto_review_pr import resolve_review_since
from ms_data.gh.gh_json import login_of
from ms_data.gh.outputs import append_step_summary, write_github_output

MERGE_LABEL = "daily-improve-merge"
HEAD_REF_PREFIX = "claude/"
BASE_REF = "main"


def _label_names(pull: dict[str, Any]) -> set[str]:
    labels = pull.get("labels")
    if not isinstance(labels, list):
        return set()
    return {
        str(label.get("name"))
        for label in labels
        if isinstance(label, dict) and label.get("name")
    }


def eligibility_skip_reason(pull: dict[str, Any], *, repo: str) -> str:
    """マージ対象の PR なら空文字、対象外なら停止理由を返す。"""
    if pull.get("state") != "open":
        return "not_open"
    if pull.get("draft") is True:
        return "draft"
    if MERGE_LABEL not in _label_names(pull):
        return "label_missing"
    if pr_payload.base_ref(pull) != BASE_REF:
        return "base_mismatch"
    if pr_payload.head_repo_full_name(pull) != repo:
        return "head_repo_mismatch"
    if not pr_payload.head_ref(pull).startswith(HEAD_REF_PREFIX):
        return "head_ref_mismatch"
    if login_of(pull) != repo.split("/", 1)[0]:
        return "author_mismatch"
    if not pr_payload.head_sha(pull):
        return "head_sha_missing"
    return ""


def codex_skip_reason(metrics: dict[str, Any]) -> str:
    """現 HEAD の Codex 判定が合格なら空文字を返す。"""
    if metrics.get("finding_count"):
        return "codex_findings"
    if not metrics.get("merge_ok"):
        return f"codex_{metrics.get('stop_reason') or 'not_ok'}"
    return ""


def stop_comment_body(*, reason: str, head_sha: str, run_url: str) -> str:
    lines = [
        f"自動マージを停止しました（理由: `{reason}`、HEAD: `{head_sha or '-'}`）。",
        "",
        f"ゲートを満たしたあと、ラベル `{MERGE_LABEL}` を付け直すと再判定します。",
    ]
    if run_url:
        lines.extend(["", f"実行ログ: {run_url}"])
    return "\n".join(lines)


def _stop(
    args: argparse.Namespace,
    deps: ReviewDeps,
    client: Any,
    *,
    reason: str,
    head_sha: str,
) -> int:
    print(f"Merge stopped: reason={reason}")
    write_github_output(args.github_output, {"merged": "false", "skip_reason": reason})
    summary = ["### Daily improve merge stopped", f"- reason: {reason}"]
    if reason not in {"not_open", "label_missing"}:
        try:
            client.post_issue_comment(
                args.pr_number,
                stop_comment_body(
                    reason=reason, head_sha=head_sha, run_url=deps.run_url()
                ),
            )
            client.api_json(
                f"repos/{args.repo}/issues/{args.pr_number}/labels/"
                f"{quote(MERGE_LABEL, safe='')}",
                method="DELETE",
            )
        except Exception as error:
            summary.append(f"- stop_comment: failed ({error})")
    append_step_summary(summary, args.step_summary)
    return 1


def _gate_and_merge(
    args: argparse.Namespace, deps: ReviewDeps, client: Any, pull: dict[str, Any]
) -> tuple[str, str]:
    """ゲートを判定してマージし、(停止理由, merge commit SHA) を返す。"""
    head_sha = pr_payload.head_sha(pull)
    reason = eligibility_skip_reason(pull, repo=args.repo)
    if reason:
        return reason, ""

    since = resolve_review_since(
        client=client,
        pr_number=args.pr_number,
        pr_created_at=str(pull.get("created_at") or ""),
        head_sha=head_sha,
    )
    metrics = deps.collect_metrics(
        client=client,
        pr_number=args.pr_number,
        head_sha=head_sha,
        trigger_comment_ids=[],
        since=since,
    )
    print(
        f"Codex gate: merge_ok={metrics.get('merge_ok')} "
        f"finding_count={metrics.get('finding_count')} "
        f"stop_reason={metrics.get('stop_reason')}"
    )
    reason = codex_skip_reason(metrics)
    if reason:
        return reason, ""

    result = merge_pull_request(
        repo=args.repo,
        pr_number=args.pr_number,
        head_ref=pr_payload.head_ref(pull),
        head_sha=head_sha,
        deps=deps,
    )
    if not result.merged:
        return result.skip_reason, ""
    return "", result.merge_commit_sha


def cmd_merge(args: argparse.Namespace, deps: ReviewDeps) -> int:
    client = deps.client(args.repo)
    head_sha = ""
    try:
        pull = client.api_json(f"repos/{args.repo}/pulls/{args.pr_number}")
        if not isinstance(pull, dict):
            reason, merge_commit_sha = "pr_unavailable", ""
        else:
            head_sha = pr_payload.head_sha(pull)
            reason, merge_commit_sha = _gate_and_merge(args, deps, client, pull)
    except Exception as error:
        # API・マージの例外でも停止コメントとラベル削除へ進め、付け直しで再判定できるようにする。
        print(f"Gate or merge error: {error!r}")
        reason, merge_commit_sha = f"error_{type(error).__name__}", ""
    if reason:
        return _stop(args, deps, client, reason=reason, head_sha=head_sha)

    write_github_output(
        args.github_output,
        {
            "merged": "true",
            "merge_commit_sha": merge_commit_sha,
            "skip_reason": "",
        },
    )
    append_step_summary(
        [
            "### Daily improve merge",
            f"- merged: `{head_sha}` -> `{merge_commit_sha}`",
        ],
        args.step_summary,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=os.getenv("GITHUB_REPOSITORY"), required=False
    )
    parser.add_argument("--pr-number", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--step-summary", type=Path, default=None)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    deps_factory: Callable[[], ReviewDeps] = ReviewDeps.default,
) -> int:
    args = build_parser().parse_args(argv)
    if not args.repo or "/" not in args.repo:
        raise SystemExit("--repo (owner/name) is required")
    if not str(args.pr_number).isdigit():
        raise SystemExit(f"invalid --pr-number: {args.pr_number}")
    return cmd_merge(args, deps_factory())


if __name__ == "__main__":
    raise SystemExit(main())
