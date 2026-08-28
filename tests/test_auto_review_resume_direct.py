import json
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from ms_data.gh import auto_review_merge, auto_review_resume
from ms_data.gh.argtypes import ReviewDeps

HEAD_SHA = "abc123"
BASELINE = "2026-05-31T09:00:00Z"
PENDING = {"merge_ok": False, "finding_count": 0, "stop_reason": "no_response"}
FINDINGS = {"merge_ok": False, "finding_count": 1, "stop_reason": "findings"}
MERGE_OK = {"merge_ok": True, "finding_count": 0, "stop_reason": "none"}


def _args(tmp_path: Path, *, pat_available: str, pat_login: str = "") -> Namespace:
    return Namespace(
        repo="owner/repo",
        run_id="555",
        max_candidates="3",
        retry_wait_seconds="60",
        poll_seconds="30",
        pat_available=pat_available,
        pat_login=pat_login,
        github_output=tmp_path / "output.txt",
        step_summary=tmp_path / "summary.md",
    )


def _prepare_client(fake_gh) -> None:
    stop = auto_review_merge.stop_marker("codex_no_response", "99", HEAD_SHA)
    fake_gh.responses["/pulls?state=open"] = [
        {
            "number": 97,
            "created_at": BASELINE,
            "user": {"login": "github-actions[bot]"},
            "base": {"ref": "main"},
            "head": {
                "ref": "data/auto-update-20260531",
                "sha": HEAD_SHA,
                "repo": {"full_name": "owner/repo"},
            },
            "body": "source_run_id:111",
        }
    ]
    fake_gh.responses["/issues/97/comments"] = [
        {
            "id": 1,
            "created_at": BASELINE,
            "user": {"login": "github-actions[bot]"},
            "body": f"stopped\n\n{stop}",
        }
    ]
    fake_gh.responses[f"/commits/{HEAD_SHA}"] = {
        "commit": {"committer": {"date": BASELINE}}
    }


def _deps(fake_gh, fake_time, **changes) -> ReviewDeps:
    deps = replace(
        ReviewDeps.default(),
        client=lambda _: fake_gh,
        clock=fake_time,
        collect_metrics=lambda **_: PENDING,
    )
    return replace(deps, **changes)


def test_cmd_resume_without_pat_leaves_pending(
    fake_gh, fake_time, tmp_path, read_github_output
):
    _prepare_client(fake_gh)
    deps = _deps(
        fake_gh,
        fake_time,
        ensure_comment=lambda **_: pytest.fail(
            "PAT なしで resume コメントを投稿してはならない"
        ),
    )

    assert (
        auto_review_resume.cmd_resume(_args(tmp_path, pat_available="false"), deps) == 0
    )
    assert read_github_output(tmp_path / "output.txt") == {
        "processed": "1",
        "merged_count": "0",
        "pending_count": "1",
    }


def test_cmd_resume_treats_closed_pr_race_as_safe_skip(
    fake_gh, fake_time, tmp_path, read_github_output
):
    _prepare_client(fake_gh)
    calls: list[list[str]] = []

    def run_gh(command):
        calls.append(command)
        assert command[1:3] == ["pr", "view"]
        return json.dumps(
            {"state": "CLOSED", "headRefOid": HEAD_SHA, "mergeCommit": None}
        )

    deps = _deps(
        fake_gh, fake_time, collect_metrics=lambda **_: MERGE_OK, run_gh=run_gh
    )

    assert (
        auto_review_resume.cmd_resume(_args(tmp_path, pat_available="false"), deps) == 0
    )
    assert read_github_output(tmp_path / "output.txt") == {
        "processed": "1",
        "merged_count": "0",
        "pending_count": "0",
    }
    assert len(calls) == 1
    assert "- merge_skipped(not_open): #97" in (tmp_path / "summary.md").read_text(
        encoding="utf-8"
    )


def test_cmd_resume_treats_merged_pr_race_as_success_and_notifies(
    fake_gh, fake_time, tmp_path, read_github_output
):
    _prepare_client(fake_gh)
    calls: list[list[str]] = []

    def run_gh(command):
        calls.append(command)
        if command[1:3] == ["pr", "view"]:
            return json.dumps(
                {
                    "state": "MERGED",
                    "headRefOid": HEAD_SHA,
                    "mergeCommit": {"oid": "merge-sha"},
                }
            )
        return ""

    deps = _deps(
        fake_gh, fake_time, collect_metrics=lambda **_: MERGE_OK, run_gh=run_gh
    )

    assert (
        auto_review_resume.cmd_resume(_args(tmp_path, pat_available="false"), deps) == 0
    )
    assert read_github_output(tmp_path / "output.txt") == {
        "processed": "1",
        "merged_count": "1",
        "pending_count": "0",
    }
    assert [call[1:3] for call in calls] == [
        ["pr", "view"],
        ["workflow", "run"],
        ["api", "repos/owner/repo/issues/97/comments"],
    ]
    assert not any(call[1:3] == ["pr", "merge"] for call in calls)
    assert "- merged: #97 (merge-sha)" in (tmp_path / "summary.md").read_text(
        encoding="utf-8"
    )
    recovered_call = calls[-1]
    assert auto_review_merge.recovered_marker("555", "merge-sha", "111") in next(
        value.removeprefix("body=")
        for value in recovered_call
        if value.startswith("body=")
    )


def test_cmd_resume_posts_resume_comment_with_pat(fake_gh, fake_time, tmp_path):
    _prepare_client(fake_gh)
    ensure_calls: list[dict] = []
    deps = _deps(
        fake_gh,
        fake_time,
        ensure_comment=lambda **kwargs: ensure_calls.append(kwargs) or ("10", "", True),
    )

    assert (
        auto_review_resume.cmd_resume(
            _args(tmp_path, pat_available="true", pat_login="trigger-user"), deps
        )
        == 0
    )
    assert ensure_calls[0]["marker"] == auto_review_resume.resume_marker(
        "555", HEAD_SHA
    )
    assert ensure_calls[0]["allowed_logins"] == {
        "github-actions[bot]",
        "trigger-user",
    }
    assert ensure_calls[0]["use_trigger_token"] is True


@pytest.mark.parametrize(
    ("retry_metrics", "expected_summary", "merged_count", "pending_count"),
    [
        (MERGE_OK, "- merged_after_retry: #97 (merge-sha)", "1", "0"),
        (FINDINGS, "- stopped_findings: #97", "0", "0"),
        (PENDING, "- pending(no_response): #97", "0", "1"),
    ],
)
def test_cmd_resume_retry_outcomes(
    fake_gh,
    fake_time,
    tmp_path,
    monkeypatch,
    read_github_output,
    retry_metrics,
    expected_summary,
    merged_count,
    pending_count,
):
    _prepare_client(fake_gh)
    monkeypatch.setattr(
        auto_review_resume, "_resume_wait_for_merge_ok", lambda **_: retry_metrics
    )
    monkeypatch.setattr(
        auto_review_resume, "_merge_and_notify", lambda **_: "merge-sha"
    )
    monkeypatch.setattr(auto_review_resume, "_handle_resume_findings", lambda **_: None)
    deps = _deps(
        fake_gh,
        fake_time,
        ensure_comment=lambda **_: ("10", "2026-05-31T09:01:00Z", True),
    )

    assert (
        auto_review_resume.cmd_resume(
            _args(tmp_path, pat_available="true", pat_login="trigger-user"), deps
        )
        == 0
    )
    assert expected_summary in (tmp_path / "summary.md").read_text(encoding="utf-8")
    outputs = read_github_output(tmp_path / "output.txt")
    assert outputs["merged_count"] == merged_count
    assert outputs["pending_count"] == pending_count


def test_resume_wait_polls_until_merge_ok(fake_gh, fake_time):
    scripted = iter([PENDING, MERGE_OK])
    calls: list[dict] = []

    def collect(**kwargs):
        calls.append(kwargs)
        return next(scripted)

    deps = _deps(fake_gh, fake_time, collect_metrics=collect)
    result = auto_review_resume._resume_wait_for_merge_ok(
        client=fake_gh,
        pr_number="97",
        head_sha=HEAD_SHA,
        since=BASELINE,
        retry_wait_seconds=60,
        poll_seconds=30,
        deps=deps,
    )

    assert result is MERGE_OK
    assert len(calls) == 2
    assert fake_time.sleeps == [30]


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        ({"stop_reason": "findings"}, True),
        ({"finding_count": "2"}, True),
        ({"finding_count": 0}, False),
        ({"finding_count": object()}, False),
    ],
)
def test_metrics_has_findings(metrics, expected):
    assert auto_review_resume._metrics_has_findings(metrics) is expected


def test_handle_resume_findings_posts_marker_and_notifies(fake_gh, fake_time):
    fake_gh.responses["/pulls/97/comments"] = [
        {
            "id": 10,
            "user": {"login": "chatgpt-codex-connector[bot]"},
            "commit_id": HEAD_SHA,
            "path": "msData.json",
            "line": 12,
            "body": "finding",
        }
    ]
    notify_calls: list[dict] = []

    def notify(**kwargs):
        payload = json.loads(kwargs["findings_json"].read_text(encoding="utf-8"))
        notify_calls.append({**kwargs, "payload": payload})
        kwargs["findings_json"].unlink()
        return 0

    deps = _deps(
        fake_gh,
        fake_time,
        notify_stop=notify,
        run_url=lambda: "https://github.com/owner/repo/actions/runs/555",
    )
    auto_review_resume._handle_resume_findings(
        client=fake_gh,
        pr_number="97",
        head_sha=HEAD_SHA,
        report_date="20260531",
        resume_run_id="555",
        deps=deps,
    )

    assert any("reason:codex_findings" in body for _, body in fake_gh.posted_comments)
    assert notify_calls[0]["pr_number"] == 97
    assert notify_calls[0]["payload"] == [
        {"path": "msData.json", "line": 12, "body": "finding"}
    ]
