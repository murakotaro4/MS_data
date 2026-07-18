import json

import pytest

from ms_data.gh.notify_failure import (
    build_failure_mail_body,
    ensure_failure_issue,
    find_open_issue,
    notify_failure,
    should_notify,
)


@pytest.mark.parametrize(
    "conclusion",
    ["failure", "timed_out", "startup_failure", "action_required"],
)
def test_should_notify_target_conclusions(conclusion):
    assert should_notify(conclusion) is True


def test_should_not_notify_cancelled():
    assert should_notify("cancelled") is False


def test_find_open_issue_prefers_exact_open_title_and_label():
    issues = [
        {
            "number": 1,
            "state": "closed",
            "title": "[pipeline-failure] data update",
            "labels": [{"name": "pipeline-failure"}],
        },
        {
            "number": 2,
            "state": "open",
            "title": "[pipeline-failure] data update",
            "labels": [{"name": "pipeline-failure"}],
        },
    ]

    issue = find_open_issue(issues, title="[pipeline-failure] data update")

    assert issue is not None
    assert issue["number"] == 2


def test_find_open_issue_returns_none_without_open_match():
    issues = [
        {
            "number": 1,
            "state": "closed",
            "title": "[pipeline-failure] data update",
            "labels": [{"name": "pipeline-failure"}],
        }
    ]

    assert (
        find_open_issue(issues, title="[pipeline-failure] data update") is None
    )


def test_failure_mail_body_contains_workflow_name_and_run_url():
    body = build_failure_mail_body(
        workflow_name="data update",
        conclusion="failure",
        run_url="https://github.com/owner/repo/actions/runs/123",
        run_id="123",
        created_at="2026-07-18T09:00:00Z",
    )

    assert "data update" in body
    assert "https://github.com/owner/repo/actions/runs/123" in body


def _issue_runner(open_issues):
    calls = []

    def runner(cmd):
        calls.append(cmd)
        if cmd[:3] == ["gh", "label", "create"]:
            return ""
        if cmd[:3] == [
            "gh",
            "api",
            "repos/owner/repo/issues?state=open&labels=pipeline-failure&per_page=100",
        ]:
            return json.dumps(open_issues)
        if cmd[:3] == ["gh", "api", "repos/owner/repo/issues/7/comments"]:
            return json.dumps({"id": 99})
        if cmd[:3] == ["gh", "api", "repos/owner/repo/issues"]:
            return json.dumps({"number": 8})
        raise AssertionError(f"unexpected command: {cmd}")

    return runner, calls


def _ensure_issue(runner):
    return ensure_failure_issue(
        repo="owner/repo",
        workflow_name="data update",
        conclusion="failure",
        run_url="https://github.com/owner/repo/actions/runs/123",
        run_id="123",
        created_at="2026-07-18T09:00:00Z",
        runner=runner,
    )


def test_existing_open_issue_gets_comment_and_commands_are_injected():
    runner, calls = _issue_runner(
        [
            {
                "number": 7,
                "state": "open",
                "title": "[pipeline-failure] data update",
                "labels": [{"name": "pipeline-failure"}],
            }
        ]
    )

    assert _ensure_issue(runner) == ("commented", 7)
    assert calls[0] == [
        "gh",
        "label",
        "create",
        "pipeline-failure",
        "--repo",
        "owner/repo",
        "--description",
        "Automatic pipeline failure notification",
        "--color",
        "B60205",
        "--force",
    ]
    assert calls[1] == [
        "gh",
        "api",
        "repos/owner/repo/issues?state=open&labels=pipeline-failure&per_page=100",
        "--paginate",
    ]
    assert calls[2][:4] == [
        "gh",
        "api",
        "repos/owner/repo/issues/7/comments",
        "-X",
    ]
    assert "body=" in calls[2][-1]


def test_no_open_issue_creates_new_issue():
    runner, calls = _issue_runner([])

    assert _ensure_issue(runner) == ("created", 8)
    create_call = calls[2]
    assert create_call[:4] == ["gh", "api", "repos/owner/repo/issues", "-X"]
    assert "title=[pipeline-failure] data update" in create_call
    assert "labels[]=pipeline-failure" in create_call


def test_cancelled_skips_mail_and_github():
    def unexpected(*args, **kwargs):
        raise AssertionError("notification must be skipped")

    result = notify_failure(
        repo="owner/repo",
        workflow_name="data update",
        conclusion="cancelled",
        run_url="https://example.invalid/run",
        run_id="123",
        created_at="2026-07-18T09:00:00Z",
        runner=unexpected,
        mail_sender=unexpected,
    )

    assert result == 0


def test_only_both_notification_failures_return_nonzero():
    def failed(*args, **kwargs):
        raise RuntimeError("failed")

    common = {
        "repo": "owner/repo",
        "workflow_name": "data update",
        "conclusion": "failure",
        "run_url": "https://example.invalid/run",
        "run_id": "123",
        "created_at": "2026-07-18T09:00:00Z",
    }

    issue_runner, _ = _issue_runner([])

    assert notify_failure(**common, runner=failed, mail_sender=lambda *_: None) == 0
    assert notify_failure(**common, runner=issue_runner, mail_sender=failed) == 0
    assert notify_failure(**common, runner=failed, mail_sender=failed) == 1
