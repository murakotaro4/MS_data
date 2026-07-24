from ms_data.gh.auto_review_merge import (
    GITHUB_ACTIONS_BOT,
    _bool_text,
    _head_ref,
    _head_sha,
    _int_or_none,
    _positive_int,
    build_auto_review_report,
    find_latest_bot_comment,
    jst_report_date,
    recovered_marker,
    resolve_source_run_id,
    resolve_target_pr,
    retry_marker,
    review_marker,
    select_resume_candidates,
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
    assert find_latest_bot_comment(comments, marker, {GITHUB_ACTIONS_BOT})["id"] == 2


def test_find_latest_bot_comment_returns_none_without_match():
    assert find_latest_bot_comment([], review_marker("abc"), {GITHUB_ACTIONS_BOT}) is None
    other_user = [
        {
            "id": 1,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "someone-else"},
            "body": review_marker("abc"),
        }
    ]
    assert (
        find_latest_bot_comment(other_user, review_marker("abc"), {GITHUB_ACTIONS_BOT})
        is None
    )


def test_find_latest_bot_comment_allows_pat_login_and_rejects_others():
    marker = review_marker("abc123")
    pat_login = "codex-trigger-user"
    comments = [
        {
            "id": 1,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "someone-else"},
            "body": marker,
        },
        {
            "id": 2,
            "created_at": "2026-05-31T09:01:00Z",
            "user": {"login": pat_login},
            "body": marker,
        },
    ]

    assert (
        find_latest_bot_comment(
            comments, marker, {GITHUB_ACTIONS_BOT, pat_login}
        )["id"]
        == 2
    )
    assert find_latest_bot_comment(comments, marker, {GITHUB_ACTIONS_BOT}) is None


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


def test_build_auto_review_report_allows_empty_trigger_comment_ids():
    report = build_auto_review_report(
        _report_args(
            merge_ok="false",
            stop_reason="disconnected",
            trigger_comment_ids="",
            first_trigger_created_at="2026-05-31T09:10:00Z",
            responded="false",
            review_complete="false",
        )
    )

    assert report["status"] == "stopped"
    assert report["stop_reason"] == "disconnected"
    assert report["review"]["trigger_comment_ids"] == []
    assert report["review"]["first_trigger_created_at"] == "2026-05-31T09:10:00Z"


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


def _auto_update_pr(
    *,
    number: int,
    report_date: str,
    head_sha: str,
    body: str = "source_run_id:111",
    login: str = "github-actions[bot]",
    base_ref: str = "main",
    repo: str = "owner/repo",
) -> dict:
    return {
        "number": number,
        "created_at": f"2026-05-{report_date[-2:]}T09:00:00Z",
        "user": {"login": login},
        "base": {"ref": base_ref},
        "head": {
            "ref": f"data/auto-update-{report_date}",
            "sha": head_sha,
            "repo": {"full_name": repo},
        },
        "body": body,
    }


def _stop_comment(reason: str, head_sha: str, run_id: str = "99") -> dict:
    return {
        "id": 1,
        "created_at": "2026-05-31T12:00:00Z",
        "user": {"login": "github-actions[bot]"},
        "body": f"stopped\n\n{stop_marker(reason, run_id, head_sha)}",
    }


def test_select_resume_candidates_filters_reason_and_head_sha():
    pulls = [
        _auto_update_pr(number=10, report_date="20260530", head_sha="sha10"),
        _auto_update_pr(number=11, report_date="20260531", head_sha="sha11"),
        _auto_update_pr(number=12, report_date="20260601", head_sha="sha12"),
        _auto_update_pr(number=13, report_date="20260602", head_sha="sha13"),
    ]
    comments_by_pr = {
        "10": [_stop_comment("codex_no_response", "sha10")],
        "11": [_stop_comment("codex_findings", "sha11")],  # findings は除外
        "12": [_stop_comment("codex_disconnected", "old-sha")],  # head_sha 不一致
        "13": [_stop_comment("codex_disconnected", "sha13")],
    }

    selected = select_resume_candidates(
        pulls=pulls,
        comments_by_pr=comments_by_pr,
        repo="owner/repo",
        max_candidates=5,
    )

    assert [item["pr_number"] for item in selected] == ["13", "10"]
    assert selected[0]["stop_reason"] == "codex_disconnected"
    assert selected[1]["stop_reason"] == "codex_no_response"


def test_select_resume_candidates_orders_desc_and_respects_limit():
    pulls = [
        _auto_update_pr(number=1, report_date="20260528", head_sha="a"),
        _auto_update_pr(number=2, report_date="20260530", head_sha="b"),
        _auto_update_pr(number=3, report_date="20260529", head_sha="c"),
    ]
    comments_by_pr = {
        "1": [_stop_comment("codex_no_response", "a")],
        "2": [_stop_comment("codex_no_response", "b")],
        "3": [_stop_comment("codex_disconnected", "c")],
    }

    selected = select_resume_candidates(
        pulls=pulls,
        comments_by_pr=comments_by_pr,
        repo="owner/repo",
        max_candidates=2,
    )

    assert [item["pr_number"] for item in selected] == ["2", "3"]
    assert [item["report_date"] for item in selected] == ["20260530", "20260529"]


def test_resolve_source_run_id_and_recovered_marker():
    assert resolve_source_run_id("hello\nsource_run_id:26709410162\n") == "26709410162"
    assert resolve_source_run_id("no marker") == ""
    assert (
        recovered_marker("555", "mergeoid", "111")
        == "<!-- auto-review-recovered run_id:555 merge_sha:mergeoid source_run_id:111 -->"
    )
