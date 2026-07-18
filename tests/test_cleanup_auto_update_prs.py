import json
import subprocess

import pytest

from ms_data.gh import cleanup_auto_update_prs
from ms_data.gh.cleanup_auto_update_prs import (
    cleanup_merged_branches,
    parse_report_date,
    plan_cleanup,
    render_summary,
)


def _pull(number, head_ref):
    return {"number": number, "head": {"ref": head_ref}}


def _branch_pull(number, branch, state, *, sha="head-sha", base="main"):
    return {
        "number": number,
        "state": "closed" if state in {"MERGED", "CLOSED"} else "open",
        "merged_at": "2026-07-02T00:00:00Z" if state == "MERGED" else None,
        "head": {
            "ref": branch,
            "sha": sha,
            "repo": {"full_name": "owner/repo"},
        },
        "base": {"ref": base},
    }


def _mock_gh(
    monkeypatch,
    *,
    branches,
    pulls,
    branch_shas=None,
    missing_branch_shas=None,
    delete_error=None,
    origin_url="https://github.com/owner/repo.git",
    push_origin_url=None,
):
    calls = []
    branch_shas = branch_shas or {}
    missing_branch_shas = set(missing_branch_shas or [])
    push_origin_url = push_origin_url or origin_url

    def fake_run(cmd):
        calls.append(cmd)
        if cmd == ["git", "remote", "get-url", "origin"]:
            return origin_url
        if cmd == ["git", "remote", "get-url", "--push", "origin"]:
            return push_origin_url
        if cmd[:2] == ["git", "push"]:
            if delete_error == "already_deleted":
                raise subprocess.CalledProcessError(
                    1,
                    cmd,
                    stderr="error: unable to delete: remote ref does not exist",
                )
            if delete_error == "lease_failed":
                raise subprocess.CalledProcessError(
                    1,
                    cmd,
                    stderr="! [rejected] (stale info)",
                )
            return ""
        if cmd[:2] == ["gh", "api"] and "--paginate" in cmd:
            endpoint = cmd[2]
            if "/branches?" in endpoint:
                return json.dumps([{"name": name} for name in branches])
            if "/pulls?" in endpoint:
                return json.dumps(pulls)
        endpoint = cmd[-1]
        if cmd[:2] == ["gh", "api"] and endpoint == "repos/owner/repo":
            return json.dumps({"default_branch": "main"})
        if cmd[:2] == ["gh", "api"] and "/git/ref/heads/" in endpoint:
            branch = endpoint.split("/git/ref/heads/", 1)[1]
            if branch in missing_branch_shas:
                raise subprocess.CalledProcessError(
                    1,
                    cmd,
                    stderr="gh: Not Found (HTTP 404)",
                )
            return json.dumps({"object": {"sha": branch_shas.get(branch, "head-sha")}})
        raise AssertionError(f"unexpected gh command: {cmd}")

    monkeypatch.setattr(cleanup_auto_update_prs, "run_gh", fake_run)
    return calls


def test_parse_report_date():
    assert parse_report_date("data/auto-update-20260531") == "20260531"
    assert parse_report_date("feature/test") is None


def test_plan_cleanup_closes_only_stale_auto_update_prs():
    actions = plan_cleanup(
        [
            _pull(1, "data/auto-update-20260531"),
            _pull(2, "data/auto-update-20260530"),
            _pull(3, "data/auto-update-20260527"),
            _pull(4, "feature/test"),
        ],
        today="20260531",
        keep_days=2,
    )

    by_number = {item.number: item for item in actions}
    assert by_number[1].action == "keep"
    assert by_number[1].reason == "today"
    assert by_number[2].action == "keep"
    assert by_number[3].action == "close"
    assert by_number[3].reason == "stale_open_pr:4d"
    assert 4 not in by_number


def test_render_summary_includes_dry_run_counts():
    actions = plan_cleanup(
        [_pull(3, "data/auto-update-20260527")],
        today="20260531",
        keep_days=2,
    )

    text = render_summary(actions, dry_run=True)

    assert "- dry_run: true" in text
    assert "- close: 1" in text
    assert "| #3 | data/auto-update-20260527 |" in text


def test_render_summary_includes_branch_cleanup_results():
    branch_results = [
        cleanup_auto_update_prs.BranchCleanupResult(
            "data/auto-update-20260702",
            "deleted",
            "deleted",
            "head-sha",
        ),
        cleanup_auto_update_prs.BranchCleanupResult(
            "data/auto-update-20260703",
            "skipped",
            "no_pr",
        ),
    ]

    text = render_summary([], dry_run=False, branch_results=branch_results)

    assert "### Auto Update Branch Cleanup" in text
    assert "- deleted: 1" in text
    assert "- skipped: 1" in text
    assert "| data/auto-update-20260703 |  | skipped | no_pr |" in text


def test_fetch_all_pulls_parses_concatenated_paginated_json(monkeypatch):
    monkeypatch.setattr(
        cleanup_auto_update_prs,
        "run_gh",
        lambda cmd: '[{"id": 1}]\n[{"id": 2}]',
    )

    assert cleanup_auto_update_prs.fetch_all_pulls("owner/repo") == [
        {"id": 1},
        {"id": 2},
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Owner/Repo.git",
        "git@github.com:Owner/Repo.git",
        "ssh://git@github.com/Owner/Repo.git",
    ],
)
def test_normalize_github_repo_url(url):
    assert cleanup_auto_update_prs.normalize_github_repo_url(url) == "owner/repo"


def test_eligible_merged_branch_is_deleted(monkeypatch):
    branch = "data/auto-update-20260702"
    calls = _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "MERGED")],
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "deleted"
    assert results[0].reason == "deleted"
    assert [
        "git",
        "push",
        f"--force-with-lease=refs/heads/{branch}:head-sha",
        "origin",
        f":refs/heads/{branch}",
    ] in calls


@pytest.mark.parametrize(
    ("pull", "reason"),
    [
        (_branch_pull(1, "data/auto-update-20260702", "OPEN"), "open_pr_head"),
        (
            _branch_pull(
                1,
                "feature/source",
                "OPEN",
                base="data/auto-update-20260702",
            ),
            "open_pr_base",
        ),
    ],
)
def test_open_pr_head_or_base_branch_is_skipped(monkeypatch, pull, reason):
    branch = "data/auto-update-20260702"
    _mock_gh(monkeypatch, branches=[branch], pulls=[pull])

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "skipped"
    assert results[0].reason == reason


def test_branch_without_pr_is_skipped(monkeypatch):
    branch = "data/auto-update-20260702"
    _mock_gh(monkeypatch, branches=[branch], pulls=[])

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results == [
        cleanup_auto_update_prs.BranchCleanupResult(branch, "skipped", "no_pr")
    ]


def test_merged_head_oid_mismatch_is_skipped(monkeypatch):
    branch = "data/auto-update-20260702"
    _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "MERGED", sha="merged-sha")],
        branch_shas={branch: "current-sha"},
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "skipped"
    assert results[0].reason == "merged_head_oid_mismatch"


def test_current_sha_in_multiple_merged_oids_is_deleted(monkeypatch):
    branch = "data/auto-update-20260702"
    calls = _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[
            _branch_pull(1, branch, "MERGED", sha="old-sha"),
            _branch_pull(2, branch, "MERGED", sha="current-sha"),
        ],
        branch_shas={branch: "current-sha"},
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "deleted"
    assert results[0].reason == "deleted"
    assert any(
        call[:3]
        == [
            "git",
            "push",
            f"--force-with-lease=refs/heads/{branch}:current-sha",
        ]
        for call in calls
    )


def test_fetch_branch_sha_404_is_already_deleted_and_continues(monkeypatch):
    missing_branch = "data/auto-update-20260702"
    remaining_branch = "data/auto-update-20260703"
    calls = _mock_gh(
        monkeypatch,
        branches=[missing_branch, remaining_branch],
        pulls=[
            _branch_pull(1, missing_branch, "MERGED"),
            _branch_pull(2, remaining_branch, "MERGED"),
        ],
        missing_branch_shas={missing_branch},
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0] == cleanup_auto_update_prs.BranchCleanupResult(
        missing_branch,
        "deleted",
        "already_deleted",
    )
    assert results[1].action == "deleted"
    assert any(
        call[:2] == ["git", "push"] and remaining_branch in call[-1]
        for call in calls
    )


def test_closed_only_branch_is_skipped(monkeypatch):
    branch = "data/auto-update-20260702"
    calls = _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "CLOSED")],
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "skipped"
    assert results[0].reason == "closed_only_no_merged"
    assert not any(call[:2] == ["git", "push"] for call in calls)


def test_non_auto_update_branch_is_not_enumerated_as_candidate(monkeypatch):
    calls = _mock_gh(
        monkeypatch,
        branches=["feature/test", "data/auto-update-20260702"],
        pulls=[],
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert [item.branch for item in results] == ["data/auto-update-20260702"]
    assert not any("feature/test" in part for call in calls for part in call)


def test_dry_run_never_calls_delete(monkeypatch):
    branch = "data/auto-update-20260702"
    calls = _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "MERGED")],
    )

    results = cleanup_merged_branches("owner/repo", dry_run=True)

    assert results[0].action == "planned"
    assert not any(call[:2] == ["git", "push"] for call in calls)


def test_missing_remote_ref_is_success(monkeypatch):
    branch = "data/auto-update-20260702"
    _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "MERGED")],
        delete_error="already_deleted",
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "deleted"
    assert results[0].reason == "already_deleted"


def test_lease_failure_is_skipped(monkeypatch):
    branch = "data/auto-update-20260702"
    _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "MERGED")],
        delete_error="lease_failed",
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "skipped"
    assert results[0].reason == "lease_failed"


def test_origin_mismatch_skips_all_candidates_without_push(monkeypatch):
    branches = [
        "data/auto-update-20260702",
        "data/auto-update-20260703",
    ]
    calls = _mock_gh(
        monkeypatch,
        branches=branches,
        pulls=[_branch_pull(1, branches[0], "MERGED")],
        origin_url="git@github.com:other/repo.git",
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert [item.branch for item in results] == branches
    assert all(item.action == "skipped" for item in results)
    assert all(item.reason == "origin_mismatch" for item in results)
    assert calls.count(["git", "remote", "get-url", "origin"]) == 1
    assert calls.count(["git", "remote", "get-url", "--push", "origin"]) == 1
    assert not any(call[:2] == ["git", "push"] for call in calls)


def test_push_origin_mismatch_skips_all_candidates_without_push(monkeypatch):
    branch = "data/auto-update-20260702"
    calls = _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "MERGED")],
        push_origin_url="git@github.com:other/repo.git",
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results == [
        cleanup_auto_update_prs.BranchCleanupResult(
            branch,
            "skipped",
            "origin_mismatch",
        )
    ]
    assert calls.count(["git", "remote", "get-url", "origin"]) == 1
    assert calls.count(["git", "remote", "get-url", "--push", "origin"]) == 1
    assert not any(call[:2] == ["git", "push"] for call in calls)
