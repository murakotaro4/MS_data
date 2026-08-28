import json
from argparse import Namespace
from pathlib import Path

import pytest

from ms_data.gh import auto_review_merge, auto_review_resume

HEAD_SHA = "abc123"
PENDING = {"merge_ok": False, "finding_count": 0, "stop_reason": "no_response"}
FINDINGS = {"merge_ok": False, "finding_count": 1, "stop_reason": "findings"}
MERGE_OK = {"merge_ok": True, "finding_count": 0, "stop_reason": "none"}


def _candidate() -> dict[str, str]:
    return {
        "pr_number": "97",
        "head_sha": HEAD_SHA,
        "head_ref": "data/auto-update-20260531",
        "report_date": "20260531",
        "created_at": "2026-05-31T09:00:00Z",
        "stop_reason": "codex_no_response",
        "body": "source_run_id:111",
    }


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


def _prepare_cmd_resume(monkeypatch, fake_gh) -> None:
    monkeypatch.setattr(auto_review_merge, "GitHubClient", lambda _: fake_gh)
    monkeypatch.setattr(
        auto_review_merge,
        "select_resume_candidates",
        lambda **_: [_candidate()],
    )
    monkeypatch.setattr(
        auto_review_merge,
        "resolve_review_since",
        lambda **_: "2026-05-31T09:00:00Z",
    )
    monkeypatch.setattr(
        auto_review_merge, "collect_review_metrics", lambda **_: PENDING
    )


def test_cmd_resume_without_pat_leaves_pending(
    fake_gh, tmp_path, monkeypatch, read_github_output
):
    _prepare_cmd_resume(monkeypatch, fake_gh)
    monkeypatch.setattr(
        auto_review_merge,
        "ensure_review_comment",
        lambda **_: pytest.fail("PAT なしで resume コメントを投稿してはならない"),
    )

    assert auto_review_resume.cmd_resume(_args(tmp_path, pat_available="false")) == 0

    outputs = read_github_output(tmp_path / "output.txt")
    assert outputs == {"processed": "1", "merged_count": "0", "pending_count": "1"}
    assert "- pending(no_pat): #97" in (tmp_path / "summary.md").read_text(
        encoding="utf-8"
    )


def test_cmd_resume_posts_resume_comment_with_pat(fake_gh, tmp_path, monkeypatch):
    _prepare_cmd_resume(monkeypatch, fake_gh)
    ensure_calls: list[dict] = []
    monkeypatch.setattr(
        auto_review_merge,
        "ensure_review_comment",
        lambda **kwargs: ensure_calls.append(kwargs) or ("10", "", True),
    )
    monkeypatch.setattr(
        auto_review_merge, "_resume_wait_for_merge_ok", lambda **_: PENDING
    )

    assert (
        auto_review_resume.cmd_resume(
            _args(tmp_path, pat_available="true", pat_login="trigger-user")
        )
        == 0
    )

    assert len(ensure_calls) == 1
    assert ensure_calls[0]["marker"] == auto_review_resume._facade().resume_marker(
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
    ids=["merge", "findings", "pending"],
)
def test_cmd_resume_retry_outcomes(
    fake_gh,
    tmp_path,
    monkeypatch,
    read_github_output,
    retry_metrics,
    expected_summary,
    merged_count,
    pending_count,
):
    _prepare_cmd_resume(monkeypatch, fake_gh)
    monkeypatch.setattr(
        auto_review_merge,
        "ensure_review_comment",
        lambda **_: ("10", "2026-05-31T09:01:00Z", True),
    )
    monkeypatch.setattr(
        auto_review_merge,
        "_resume_wait_for_merge_ok",
        lambda **_: retry_metrics,
    )
    merge_calls: list[dict] = []
    finding_calls: list[dict] = []
    monkeypatch.setattr(
        auto_review_merge,
        "_merge_and_notify",
        lambda **kwargs: merge_calls.append(kwargs) or "merge-sha",
    )
    monkeypatch.setattr(
        auto_review_merge,
        "_handle_resume_findings",
        lambda **kwargs: finding_calls.append(kwargs),
    )

    assert (
        auto_review_resume.cmd_resume(
            _args(tmp_path, pat_available="true", pat_login="trigger-user")
        )
        == 0
    )

    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert expected_summary in summary
    outputs = read_github_output(tmp_path / "output.txt")
    assert outputs["merged_count"] == merged_count
    assert outputs["pending_count"] == pending_count
    assert bool(merge_calls) is (retry_metrics is MERGE_OK)
    assert bool(finding_calls) is (retry_metrics is FINDINGS)


def test_resume_wait_polls_until_merge_ok(fake_gh, fake_time, monkeypatch):
    scripted = iter([PENDING, MERGE_OK])
    calls: list[dict] = []

    def collect(**kwargs):
        calls.append(kwargs)
        return next(scripted)

    monkeypatch.setattr(auto_review_merge, "collect_review_metrics", collect)

    result = auto_review_resume._resume_wait_for_merge_ok(
        client=fake_gh,
        pr_number="97",
        head_sha=HEAD_SHA,
        since="2026-05-31T09:00:00Z",
        retry_wait_seconds=60,
        poll_seconds=30,
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


def test_handle_resume_findings_posts_marker_and_notifies(fake_gh, monkeypatch):
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

    monkeypatch.setattr(auto_review_merge, "notify_review_stop", notify)
    monkeypatch.setattr(
        auto_review_merge,
        "github_run_url",
        lambda: "https://github.com/owner/repo/actions/runs/555",
    )

    auto_review_resume._handle_resume_findings(
        client=fake_gh,
        pr_number="97",
        head_sha=HEAD_SHA,
        report_date="20260531",
        resume_run_id="555",
    )

    assert any("reason:codex_findings" in body for _, body in fake_gh.posted_comments)
    assert notify_calls[0]["pr_number"] == 97
    assert notify_calls[0]["payload"] == [
        {"path": "msData.json", "line": 12, "body": "finding"}
    ]
