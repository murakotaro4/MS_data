from ms_data.gh.auto_review_merge import (
    _bool_text,
    _head_ref,
    _head_sha,
    _int_or_none,
    _positive_int,
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


def test_jst_report_date_naive_datetime_treated_as_utc():
    # tzinfo なしは UTC とみなす（09:05 UTC -> 18:05 JST で同日）
    assert jst_report_date("2026-05-31T09:05:00") == "20260531"
    # 16:00 UTC -> 翌日 01:00 JST
    assert jst_report_date("2026-05-31T16:00:00") == "20260601"


def test_head_ref_and_sha_handle_malformed_items():
    assert _head_ref({"head": None}) == ""
    assert _head_sha({"head": None}) == ""
    assert _head_ref({"head": {"ref": 123}}) == ""
    assert _head_sha({"head": {"sha": 123}}) == ""


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


def test_find_latest_bot_comment_returns_none_without_match():
    assert find_latest_bot_comment([], review_marker("abc")) is None
    other_user = [
        {
            "id": 1,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "someone-else"},
            "body": review_marker("abc"),
        }
    ]
    assert find_latest_bot_comment(other_user, review_marker("abc")) is None


def test_text_parsing_helpers():
    assert _positive_int("5", 3) == 5
    assert _positive_int("0", 3) == 3
    assert _positive_int("abc", 3) == 3
    assert _bool_text("TRUE") is True
    assert _bool_text("1") is True
    assert _bool_text("false") is False
    assert _bool_text("") is False
    assert _int_or_none(" 7 ") == 7
    assert _int_or_none("") is None
    assert _int_or_none("abc") is None


def _report_args(**overrides):
    values = {
        "report_date": "20260531",
        "run_id": "26709621743",
        "pr_number": "97",
        "head_ref": "data/auto-update-20260531",
        "head_sha": "abc123",
        "merge_ok": "true",
        "merged": "",
        "merge_outcome": "",
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
    }
    values.update(overrides)
    return type("Args", (), values)()


def test_build_auto_review_report_records_no_response_stop():
    report = build_auto_review_report(
        _report_args(
            merge_ok="false",
            merge_outcome="skipped",
            stop_reason="no_response",
            review_complete="false",
            responded="false",
            attempts_used="3",
            response_attempt="",
            response_seconds="",
            trigger_comment_ids="10,11,12",
        )
    )

    assert report["schema_version"] == "1"
    assert report["status"] == "stopped"
    assert report["stop_reason"] == "no_response"
    assert report["review"]["responded"] is False
    assert report["review"]["attempts_used"] == 3
    assert report["review"]["trigger_comment_ids"] == ["10", "11", "12"]


def test_build_auto_review_report_records_merge_failure():
    report = build_auto_review_report(_report_args(merge_outcome="failure"))

    assert report["status"] == "merge_failed"
    assert report["stop_reason"] == "merge_failed"
    assert report["merge_ok"] is True
    assert report["merged"] is False
    assert report["merge_outcome"] == "failure"


def test_build_auto_review_report_records_merged():
    report = build_auto_review_report(
        _report_args(merged="true", merge_outcome="success", stop_reason="findings")
    )

    assert report["status"] == "merged"
    # merged の場合は入力の stop_reason によらず none になる
    assert report["stop_reason"] == "none"
    assert report["merged"] is True


def test_build_auto_review_report_records_merge_ready():
    report = build_auto_review_report(_report_args())

    assert report["status"] == "merge_ready"
    assert report["stop_reason"] == "none"
    assert report["merge_ok"] is True
    assert report["merged"] is False
