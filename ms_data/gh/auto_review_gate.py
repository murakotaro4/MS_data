"""Codex GitHub review signals for auto-review merge workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ms_data.gh.gh_json import load_json_stream as _load_json
from ms_data.gh.gh_json import login_of as _login


CODEX_LOGINS = {"chatgpt-codex-connector[bot]", "chatgpt-codex-connector"}
NO_ISSUES_PREFIX = "Codex Review: Didn't find any major issues."
DISCONNECT_PREFIX = "To use Codex here"


def finding_commit_sha(item: dict[str, Any]) -> str:
    """ファイルコメントが投稿されたコミット SHA。

    GitHub は指摘対応後もコメントを新 HEAD へ再配置し ``commit_id`` を
    更新する。自動マージ判定では投稿元の ``original_commit_id`` を使う。
    """
    value = item.get("original_commit_id") or item.get("commit_id")
    return value if isinstance(value, str) else ""


def _is_codex(item: dict[str, Any]) -> bool:
    return _login(item) in CODEX_LOGINS


def _created_at(item: dict[str, Any]) -> str:
    value = item.get("created_at") or item.get("submitted_at")
    return value if isinstance(value, str) else ""


def evaluate(
    *,
    reviews: list[dict[str, Any]],
    file_comments: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    reactions: list[dict[str, Any]],
    head_sha: str,
    since: str,
) -> dict[str, Any]:
    """Return merge-gate metrics for Codex review signals.

    ``review_complete`` means Codex has emitted a terminal no-issue signal or a
    file finding. Generic issue comments and reactions only prove activity; they
    do not make the PR mergeable.
    """

    review_count = sum(
        1 for item in reviews if _is_codex(item) and item.get("commit_id") == head_sha
    )
    finding_count = sum(
        1
        for item in file_comments
        if _is_codex(item) and finding_commit_sha(item) == head_sha
    )
    reaction_count = sum(
        1 for item in reactions if _is_codex(item) and item.get("content") == "+1"
    )
    codex_issue_comments = [
        item
        for item in issue_comments
        if _is_codex(item) and _created_at(item) >= since
    ]
    no_issue_comment_count = sum(
        1
        for item in codex_issue_comments
        if isinstance(item.get("body"), str)
        and item["body"].startswith(NO_ISSUES_PREFIX)
    )
    disconnect_count = sum(
        1
        for item in codex_issue_comments
        if isinstance(item.get("body"), str)
        and item["body"].startswith(DISCONNECT_PREFIX)
    )

    terminal_count = review_count + no_issue_comment_count
    review_complete = terminal_count > 0 or finding_count > 0
    merge_ok = terminal_count > 0 and finding_count == 0
    if finding_count > 0:
        stop_reason = "findings"
    elif merge_ok:
        stop_reason = "none"
    elif disconnect_count > 0:
        stop_reason = "disconnected"
    else:
        stop_reason = "no_response"

    return {
        "review_count": review_count,
        "finding_count": finding_count,
        "reaction_count": reaction_count,
        "issue_comment_count": len(codex_issue_comments),
        "no_issue_comment_count": no_issue_comment_count,
        "disconnect_count": disconnect_count,
        "terminal_count": terminal_count,
        "review_complete": review_complete,
        "merge_ok": merge_ok,
        "stop_reason": stop_reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--file-comments", type=Path, required=True)
    parser.add_argument("--issue-comments", type=Path, required=True)
    parser.add_argument("--reactions", type=Path, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    result = evaluate(
        reviews=_load_json(args.reviews),
        file_comments=_load_json(args.file_comments),
        issue_comments=_load_json(args.issue_comments),
        reactions=_load_json(args.reactions),
        head_sha=args.head_sha,
        since=args.since,
    )
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
