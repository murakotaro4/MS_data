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


def _mock_gh(monkeypatch, *, branches, pulls, branch_shas=None, delete_404=False):
    calls = []
    branch_shas = branch_shas or {}

    def fake_run(cmd):
        calls.append(cmd)
        endpoint = cmd[-1]
        if cmd[:4] == ["gh", "api", "--paginate", "--slurp"]:
            if "/branches?" in endpoint:
                return json.dumps([[{"name": name} for name in branches]])
            if "/pulls?" in endpoint:
                return json.dumps([pulls])
        if cmd[:2] == ["gh", "api"] and endpoint == "repos/owner/repo":
            return json.dumps({"default_branch": "main"})
        if cmd[:4] == ["gh", "api", "-X", "DELETE"]:
            if delete_404:
                raise subprocess.CalledProcessError(
                    1,
                    cmd,
                    stderr="HTTP 404: Not Found",
                )
            return ""
        if cmd[:2] == ["gh", "api"] and "/git/ref/heads/" in endpoint:
            branch = endpoint.split("/git/ref/heads/", 1)[1]
            return json.dumps({"object": {"sha": branch_shas.get(branch, "head-sha")}})
        raise AssertionError(f"unexpected gh command: {cmd}")

    monkeypatch.setattr(cleanup_auto_update_prs, "_run", fake_run)
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


def test_gh_json_rejects_concatenated_documents(monkeypatch):
    monkeypatch.setattr(
        cleanup_auto_update_prs,
        "_run",
        lambda cmd: '[{"id": 1}]\n[{"id": 2}]',
    )

    with pytest.raises(json.JSONDecodeError, match="Extra data"):
        cleanup_auto_update_prs._gh_json("repos/owner/repo/pulls")


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
    assert ["gh", "api", "-X", "DELETE", f"repos/owner/repo/git/refs/heads/{branch}"] in calls


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
    assert not any("DELETE" in call for call in calls)


def test_delete_404_is_success(monkeypatch):
    branch = "data/auto-update-20260702"
    _mock_gh(
        monkeypatch,
        branches=[branch],
        pulls=[_branch_pull(1, branch, "MERGED")],
        delete_404=True,
    )

    results = cleanup_merged_branches("owner/repo", dry_run=False)

    assert results[0].action == "deleted"
    assert results[0].reason == "already_deleted"
