"""resume サブコマンドのテスト（ReviewDeps 注入・findings 停止・superseded）。"""

import json
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from ms_data.gh import auto_review_merge, auto_review_resume
from ms_data.gh.argtypes import ReviewDeps
from ms_data.gh.auto_review_merge import main

from auto_review_helpers import (
    BASELINE,
    HEAD_SHA,
    PAT_LOGIN,
    codex_finding,
    metrics,
    run_main,
    script_metrics,
    successful_ci_runs,
)


def test_cmd_resume_honors_injected_deps_through_merge_and_notify(
    fake_gh, fake_time, read_github_output, tmp_path
):
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

    fake_gh.responses["/pulls/97"] = {"head": {"sha": HEAD_SHA}}
    gh_calls: list[list[str]] = []

    views = iter(
        [
            {"state": "OPEN", "headRefOid": HEAD_SHA, "mergeCommit": None},
            {
                "state": "MERGED",
                "headRefOid": HEAD_SHA,
                "mergeCommit": {"oid": "merge-sha"},
            },
        ]
    )

    def fake_run_gh(command):
        gh_calls.append(command)
        if command[1:2] == ["api"] and "/actions/workflows/ci.yml/runs?" in command[2]:
            return successful_ci_runs(HEAD_SHA)
        if command[1:3] == ["pr", "view"]:
            return json.dumps(next(views))
        return ""

    deps = replace(
        ReviewDeps.default(),
        client=lambda _: fake_gh,
        clock=fake_time,
        run_gh=fake_run_gh,
        collect_metrics=lambda **_: metrics(merge_ok=True, review_complete=True),
    )

    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    rc = main(
        [
            "resume",
            "--repo",
            "owner/repo",
            "--run-id",
            "555",
            "--pat-available",
            "false",
            "--github-output",
            str(out),
            "--step-summary",
            str(summary),
        ],
        deps_factory=lambda: deps,
    )

    assert rc == 0
    assert [call[1:3] for call in gh_calls] == [
        ["pr", "view"],
        [
            "api",
            "repos/owner/repo/actions/workflows/ci.yml/runs?head_sha=abc123&event=pull_request&per_page=100",
        ],
        ["pr", "merge"],
        ["pr", "view"],
        ["workflow", "run"],
        ["api", "repos/owner/repo/issues/97/comments"],
    ]
    outputs = read_github_output(out)
    assert outputs["merged_count"] == "1"
    assert "- merged: #97 (merge-sha)" in summary.read_text(encoding="utf-8")


def test_cmd_resume_stops_on_findings_without_retry(
    fake_gh, read_github_output, tmp_path, monkeypatch
):
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
    fake_gh.responses["/pulls/97/comments"] = [codex_finding()]

    notify_calls: list[dict] = []

    def fake_notify(**kwargs):
        notify_calls.append(kwargs)
        return 0

    ensure_calls: list[dict] = []

    def fake_ensure(**kwargs):
        ensure_calls.append(kwargs)
        raise AssertionError("findings 停止時に retry 投稿してはならない")

    _, collect = script_metrics(
        [
            metrics(
                finding_count=1,
                review_complete=True,
                merge_ok=False,
                stop_reason="findings",
            )
        ],
    )

    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "555")

    rc = run_main(
        [
            "resume",
            "--repo",
            "owner/repo",
            "--run-id",
            "555",
            "--pat-available",
            "true",
            "--pat-login",
            PAT_LOGIN,
            "--retry-wait-seconds",
            "60",
            "--poll-seconds",
            "30",
            "--github-output",
            str(out),
            "--step-summary",
            str(summary),
        ],
        fake_gh,
        collect_metrics=collect,
        ensure_comment=fake_ensure,
        notify_stop=fake_notify,
    )

    assert rc == 0
    assert ensure_calls == []
    assert len(notify_calls) == 1
    assert notify_calls[0]["stop_reason"] == "findings"
    assert notify_calls[0]["pr_number"] == 97
    assert notify_calls[0]["report_date"] == "20260531"
    assert notify_calls[0]["pr_url"] == "https://github.com/owner/repo/pull/97"
    assert (
        notify_calls[0]["run_url"] == "https://github.com/owner/repo/actions/runs/555"
    )
    assert any("reason:codex_findings" in body for _, body in fake_gh.posted_comments)
    text = summary.read_text(encoding="utf-8")
    assert "- stopped_findings: #97" in text
    outputs = read_github_output(out)
    assert outputs["merged_count"] == "0"
    assert outputs["pending_count"] == "0"


def test_cmd_resume_processes_only_newest_and_supersedes_older(
    fake_gh, read_github_output, tmp_path, monkeypatch
):
    # 各 PR は main 基点の全量スナップショットのため、旧日 PR を後からマージすると
    # データが巻き戻る。最新日 1 件のみ処理し、旧日は superseded として残す。
    old_sha = "old-sha"
    stop_new = auto_review_merge.stop_marker("codex_no_response", "99", HEAD_SHA)
    stop_old = auto_review_merge.stop_marker("codex_no_response", "98", old_sha)
    fake_gh.responses["/pulls?state=open"] = [
        {
            "number": 96,
            "created_at": BASELINE,
            "user": {"login": "github-actions[bot]"},
            "base": {"ref": "main"},
            "head": {
                "ref": "data/auto-update-20260530",
                "sha": old_sha,
                "repo": {"full_name": "owner/repo"},
            },
            "body": "source_run_id:110",
        },
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
        },
    ]
    fake_gh.responses["/issues/96/comments"] = [
        {
            "id": 1,
            "created_at": BASELINE,
            "user": {"login": "github-actions[bot]"},
            "body": f"stopped\n\n{stop_old}",
        }
    ]
    fake_gh.responses["/issues/97/comments"] = [
        {
            "id": 2,
            "created_at": BASELINE,
            "user": {"login": "github-actions[bot]"},
            "body": f"stopped\n\n{stop_new}",
        }
    ]
    fake_gh.responses[f"/commits/{HEAD_SHA}"] = {
        "commit": {"committer": {"date": BASELINE}}
    }
    fake_gh.responses["/pulls/97/comments"] = [codex_finding()]

    notify_calls: list[dict] = []

    def fake_notify(**kwargs):
        notify_calls.append(kwargs)
        return 0

    calls, collect = script_metrics(
        [
            metrics(
                finding_count=1,
                review_complete=True,
                merge_ok=False,
                stop_reason="findings",
            )
        ],
    )

    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "556")

    rc = run_main(
        [
            "resume",
            "--repo",
            "owner/repo",
            "--run-id",
            "556",
            "--pat-available",
            "false",
            "--retry-wait-seconds",
            "60",
            "--poll-seconds",
            "30",
            "--github-output",
            str(out),
            "--step-summary",
            str(summary),
        ],
        fake_gh,
        collect_metrics=collect,
        notify_stop=fake_notify,
    )

    assert rc == 0
    # 最新日 (#97) だけがゲート評価され、旧日 (#96) は評価されない
    assert len(calls) == 1
    assert len(notify_calls) == 1
    assert notify_calls[0]["pr_number"] == 97
    text = summary.read_text(encoding="utf-8")
    assert "- superseded(skip): #96" in text
    outputs = read_github_output(out)
    assert outputs["merged_count"] == "0"


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
        ensure_comment=lambda **_: ("10", "2026-05-31T09:11:00Z", True),
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


@pytest.mark.parametrize(
    ("ci_changes", "reason"),
    [
        ({"conclusion": "failure"}, "ci_not_success"),
        ({"status": "in_progress"}, "ci_incomplete"),
        ({"head_sha": "old-head"}, "ci_target_mismatch"),
        ({"id": None}, "ci_unavailable"),
        (None, "ci_not_found"),
    ],
)
def test_resume_with_successful_review_still_requires_latest_head_ci(
    fake_gh, fake_time, tmp_path, ci_changes, reason
):
    from auto_review_helpers import successful_ci_runs

    _prepare_client(fake_gh)
    calls = []
    runs = json.loads(successful_ci_runs(HEAD_SHA)) if ci_changes is not None else []
    if runs:
        runs[0].update(ci_changes)

    def run_gh(command):
        calls.append(command)
        if command[1:3] == ["pr", "view"]:
            return json.dumps(
                {"state": "OPEN", "headRefOid": HEAD_SHA, "mergeCommit": None}
            )
        assert command[1] == "api" and "/actions/workflows/ci.yml/runs?" in command[2]
        return json.dumps(runs)

    deps = _deps(
        fake_gh, fake_time, collect_metrics=lambda **_: MERGE_OK, run_gh=run_gh
    )
    with pytest.raises(RuntimeError, match=reason):
        auto_review_resume.cmd_resume(_args(tmp_path, pat_available="false"), deps)
    summary = (tmp_path / "summary.md").read_text()
    assert "### Auto Review Resume" in summary
    assert "- failed: #97" in summary
    assert f"reason={reason}" in summary
    assert len(calls) == 2
    assert not any(
        call[1:3] in (["pr", "merge"], ["workflow", "run"]) for call in calls
    )
