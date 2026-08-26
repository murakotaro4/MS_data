from argparse import Namespace
from datetime import datetime, timedelta, timezone

from ms_data.gh import auto_review_markers, auto_review_pr, auto_review_wait


CODEX_BOT = "chatgpt-codex-connector[bot]"
HEAD_SHA = "abc123"


def test_stop_and_resume_markers_are_parsed_directly():
    body = (
        "停止しました\n"
        "<!--   auto-review-stop reason:codex_no_response "
        "run_id:123 head_sha:abc123   -->"
    )

    assert auto_review_markers.STOP_MARKER_RE.search(body)
    assert auto_review_markers.parse_stop_marker(body) == {
        "reason": "codex_no_response",
        "run_id": "123",
        "head_sha": HEAD_SHA,
    }
    assert auto_review_markers.parse_stop_marker("marker なし") is None
    assert (
        auto_review_markers.resume_marker("456", HEAD_SHA)
        == "<!-- auto-review resume run_id:456 head_sha:abc123 -->"
    )


def test_extract_codex_findings_excludes_resolved_and_non_head_comments():
    comments = [
        {
            "id": 10,
            "user": {"login": CODEX_BOT},
            "commit_id": HEAD_SHA,
            "path": "ms_data/gh/example.py",
            "line": 12,
            "body": "active",
        },
        {
            "id": 11,
            "user": {"login": CODEX_BOT},
            "commit_id": HEAD_SHA,
            "path": "resolved.py",
            "line": 20,
            "body": "resolved",
        },
        {
            "id": 12,
            "user": {"login": CODEX_BOT},
            "commit_id": "old-sha",
            "path": "old.py",
            "line": 30,
            "body": "old head",
        },
        {
            "id": 13,
            "user": {"login": "someone-else"},
            "commit_id": HEAD_SHA,
            "path": "other.py",
            "line": 40,
            "body": "other user",
        },
        {
            "id": 14,
            "user": {"login": CODEX_BOT},
            "commit_id": HEAD_SHA,
            "path": None,
            "line": "not-an-int",
            "body": None,
        },
    ]

    assert auto_review_pr.extract_codex_findings(
        comments, HEAD_SHA, resolved_comment_ids={"11"}
    ) == [
        {"path": "ms_data/gh/example.py", "line": 12, "body": "active"},
        {"path": "", "line": None, "body": ""},
    ]


def test_github_datetime_helpers_and_jst_boundary():
    offset = timezone(timedelta(hours=9))
    value = datetime(2026, 6, 1, 1, 2, 3, tzinfo=offset)

    assert auto_review_pr.format_github_datetime(value) == "2026-05-31T16:02:03Z"
    assert auto_review_pr.parse_github_datetime("2026-05-31T16:02:03Z") == datetime(
        2026, 5, 31, 16, 2, 3, tzinfo=timezone.utc
    )
    assert auto_review_pr.parse_github_datetime("2026-05-31T16:02:03") == datetime(
        2026, 5, 31, 16, 2, 3, tzinfo=timezone.utc
    )
    assert auto_review_pr.parse_github_datetime("") is None
    assert auto_review_pr.parse_github_datetime("invalid") is None
    assert auto_review_pr.jst_report_date("2026-05-31T14:59:59Z") == "20260531"
    assert auto_review_pr.jst_report_date("2026-05-31T15:00:00Z") == "20260601"


def test_poll_for_response_breaks_when_poll_interval_is_zero(
    fake_gh, fake_time, monkeypatch
):
    metrics = {
        "review_count": 0,
        "finding_count": 0,
        "reaction_count": 0,
        "issue_comment_count": 0,
        "no_issue_comment_count": 0,
        "disconnect_count": 0,
        "terminal_count": 0,
        "review_complete": False,
    }
    from ms_data.gh import auto_review_merge

    monkeypatch.setattr(
        auto_review_merge, "collect_review_metrics", lambda **_: metrics
    )
    args = Namespace(pr_number="97", head_sha=HEAD_SHA)

    assert auto_review_wait._poll_for_response(
        fake_gh,
        args,
        attempt=1,
        max_attempts=1,
        attempt_timeout_seconds=60,
        poll_seconds=0,
        settle_seconds=0,
        trigger_comment_ids=[],
        since="2026-05-31T00:00:00Z",
        started_at=0.0,
    ) == (False, "", False)
    assert fake_time.sleeps == []
