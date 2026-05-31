from scripts.auto_review_merge import (
    build_auto_review_report,
    find_latest_bot_comment,
    jst_report_date,
    resolve_target_pr,
    retry_marker,
    review_marker,
    stop_marker,
)


def test_jst_report_date_uses_workflow_run_created_at():
    assert jst_report_date("2026-05-31T09:05:00Z") == "20260531"


def test_resolve_target_pr_prefers_source_run_id_marker():
    result = resolve_target_pr(
        pulls=[
            {
                "number": 97,
                "created_at": "2026-05-31T09:10:00Z",
                "user": {"login": "github-actions[bot]"},
                "head": {"ref": "data/auto-update-20260531", "sha": "abc"},
                "body": "source_run_id:26709410162",
            },
            {
                "number": 96,
                "created_at": "2026-05-31T09:00:00Z",
                "user": {"login": "github-actions[bot]"},
                "head": {"ref": "data/auto-update-20260531", "sha": "old"},
                "body": "",
            },
        ],
        run_id="26709410162",
        run_created_at="2026-05-31T09:00:25Z",
    )

    assert result["skip"] == "false"
    assert result["pr"] == "97"
    assert result["resolved_by"] == "source_run_id_marker"


def test_resolve_target_pr_uses_legacy_exact_branch_only_without_marker():
    result = resolve_target_pr(
        pulls=[
            {
                "number": 98,
                "created_at": "2026-05-31T09:10:00Z",
                "user": {"login": "github-actions[bot]"},
                "head": {"ref": "data/auto-update-20260531", "sha": "abc"},
                "body": "",
            }
        ],
        run_id="1",
        run_created_at="2026-05-31T09:00:25Z",
    )

    assert result["skip"] == "false"
    assert result["pr"] == "98"
    assert result["resolved_by"] == "exact_branch_legacy_no_marker"


def test_resolve_target_pr_skips_when_no_match():
    result = resolve_target_pr(
        pulls=[],
        run_id="1",
        run_created_at="2026-05-31T09:00:25Z",
    )

    assert result["skip"] == "true"
    assert result["skip_reason"] == "no_target_pr"


def test_comment_markers_and_latest_bot_comment():
    marker = review_marker("abc123")
    comments = [
        {
            "id": 1,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "github-actions[bot]"},
            "body": marker,
        },
        {
            "id": 2,
            "created_at": "2026-05-31T09:01:00Z",
            "user": {"login": "github-actions[bot]"},
            "body": marker,
        },
    ]

    assert retry_marker(2, "abc123") == "<!-- auto-review retry:2 head_sha:abc123 -->"
    assert (
        stop_marker("codex_no_response", "123", "abc123")
        == "<!-- auto-review-stop reason:codex_no_response run_id:123 head_sha:abc123 -->"
    )
    assert find_latest_bot_comment(comments, marker)["id"] == 2


def test_build_auto_review_report_records_no_response_stop():
    args = type(
        "Args",
        (),
        {
            "report_date": "20260531",
            "run_id": "26709621743",
            "pr_number": "97",
            "head_ref": "data/auto-update-20260531",
            "head_sha": "abc123",
            "merge_ok": "false",
            "merged": "",
            "merge_outcome": "skipped",
            "stop_reason": "no_response",
            "findings": "0",
            "review_complete": "false",
            "responded": "false",
            "attempts_used": "3",
            "max_attempts": "3",
            "attempt_timeout_seconds": "420",
            "poll_seconds": "30",
            "settle_seconds": "60",
            "response_attempt": "",
            "response_seconds": "",
            "trigger_comment_ids": "10,11,12",
            "first_trigger_created_at": "2026-05-31T10:00:00Z",
        },
    )()

    report = build_auto_review_report(args)

    assert report["schema_version"] == "1"
    assert report["status"] == "stopped"
    assert report["stop_reason"] == "no_response"
    assert report["review"]["responded"] is False
    assert report["review"]["attempts_used"] == 3
    assert report["review"]["trigger_comment_ids"] == ["10", "11", "12"]


def test_build_auto_review_report_records_merge_failure():
    args = type(
        "Args",
        (),
        {
            "report_date": "20260531",
            "run_id": "26709621743",
            "pr_number": "97",
            "head_ref": "data/auto-update-20260531",
            "head_sha": "abc123",
            "merge_ok": "true",
            "merged": "",
            "merge_outcome": "failure",
            "stop_reason": "none",
            "findings": "0",
            "review_complete": "true",
            "responded": "true",
            "attempts_used": "1",
            "max_attempts": "3",
            "attempt_timeout_seconds": "420",
            "poll_seconds": "30",
            "settle_seconds": "60",
            "response_attempt": "1",
            "response_seconds": "90",
            "trigger_comment_ids": "10",
            "first_trigger_created_at": "2026-05-31T10:00:00Z",
        },
    )()

    report = build_auto_review_report(args)

    assert report["status"] == "merge_failed"
    assert report["stop_reason"] == "merge_failed"
    assert report["merge_ok"] is True
    assert report["merged"] is False
    assert report["merge_outcome"] == "failure"
