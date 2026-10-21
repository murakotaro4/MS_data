"""Codex GitHub review signals for auto-review merge workflow."""

from __future__ import annotations

import re
from typing import Any

from ms_data.gh.gh_json import login_of as _login

CODEX_LOGINS = {"chatgpt-codex-connector[bot]", "chatgpt-codex-connector"}
NO_ISSUES_PREFIX = "Codex Review: Didn't find any major issues."
DISCONNECT_PREFIX = "To use Codex here"
# Codex は本文先頭に `<!-- codex-review-receipt:v1 -->` 等のマーカーを付けることがある。
_LEADING_HTML_COMMENTS = re.compile(r"\A(?:\s*<!--.*?-->)*\s*", re.DOTALL)


def _is_codex(item: dict[str, Any]) -> bool:
    return _login(item) in CODEX_LOGINS


def _created_at(item: dict[str, Any]) -> str:
    value = item.get("created_at") or item.get("submitted_at")
    return value if isinstance(value, str) else ""


def _comment_id(item: dict[str, Any]) -> str:
    value = item.get("id")
    return str(value) if value is not None else ""


def _body_text(item: dict[str, Any]) -> str:
    """先頭の HTML コメントと空白を除いた本文を返す。"""
    body = item.get("body")
    if not isinstance(body, str):
        return ""
    return _LEADING_HTML_COMMENTS.sub("", body, count=1)


def is_active_finding(
    item: dict[str, Any],
    *,
    head_sha: str,
    resolved_comment_ids: set[str],
) -> bool:
    """HEAD 上の未解決 Codex ファイル指摘なら True（持ち越し指摘を含む）。"""
    if not _is_codex(item) or item.get("commit_id") != head_sha:
        return False
    comment_id = _comment_id(item)
    return not (comment_id and comment_id in resolved_comment_ids)


def is_carried_finding(item: dict[str, Any], *, head_sha: str) -> bool:
    """旧 HEAD で投稿され、現 HEAD へ持ち越された指摘なら True。

    GitHub は指摘行が変わらない限り、コメントの ``commit_id`` を新しい HEAD へ
    付け替える（``original_commit_id`` は投稿時のまま）。``original_commit_id``
    が無い場合は現 HEAD の指摘として扱う。
    """
    original = item.get("original_commit_id")
    return isinstance(original, str) and bool(original) and original != head_sha


def evaluate(
    *,
    reviews: list[dict[str, Any]],
    file_comments: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    reactions: list[dict[str, Any]],
    head_sha: str,
    since: str,
    resolved_comment_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return merge-gate metrics for Codex review signals.

    ``review_complete`` means Codex has emitted a terminal no-issue signal or a
    file finding on the current HEAD. Generic issue comments and reactions only
    prove activity; they do not make the PR mergeable. Resolved review threads are
    not findings. Findings carried over from an older HEAD do not complete the
    review by themselves and are ignored once the current HEAD gets a terminal
    signal.
    """

    resolved_ids = resolved_comment_ids or set()
    review_count = sum(
        1 for item in reviews if _is_codex(item) and item.get("commit_id") == head_sha
    )
    active_findings = [
        item
        for item in file_comments
        if is_active_finding(item, head_sha=head_sha, resolved_comment_ids=resolved_ids)
    ]
    carried_finding_count = sum(
        1 for item in active_findings if is_carried_finding(item, head_sha=head_sha)
    )
    current_finding_count = len(active_findings) - carried_finding_count
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
        if _body_text(item).startswith(NO_ISSUES_PREFIX)
    )
    disconnect_count = sum(
        1
        for item in codex_issue_comments
        if _body_text(item).startswith(DISCONNECT_PREFIX)
    )

    terminal_count = review_count + no_issue_comment_count
    # 持ち越し指摘は現 HEAD の Codex 結果を待つ。現 HEAD で終端シグナルが
    # 出れば無視し、出なければ従来どおり findings として停止する。
    finding_count = current_finding_count + (
        carried_finding_count if terminal_count == 0 else 0
    )
    review_complete = terminal_count > 0 or current_finding_count > 0
    merge_ok = terminal_count > 0 and current_finding_count == 0
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
        "carried_finding_count": carried_finding_count,
        "reaction_count": reaction_count,
        "issue_comment_count": len(codex_issue_comments),
        "no_issue_comment_count": no_issue_comment_count,
        "disconnect_count": disconnect_count,
        "terminal_count": terminal_count,
        "review_complete": review_complete,
        "merge_ok": merge_ok,
        "stop_reason": stop_reason,
    }
