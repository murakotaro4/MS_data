"""auto-review コメント marker の生成・解析。"""

from __future__ import annotations

import re
from typing import Any

from ms_data.gh.gh_json import login_of as _login

STOP_MARKER_RE = re.compile(
    r"<!--\s*auto-review-stop\s+reason:(\S+)\s+run_id:(\S+)\s+head_sha:(\S+)\s*-->"
)


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
