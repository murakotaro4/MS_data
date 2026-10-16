"""CI承認範囲と、承認後も成功しなければマージしない契約を検証。"""

import copy
import json
import subprocess
from dataclasses import replace

import pytest

from ms_data.gh.argtypes import ReviewDeps
from ms_data.gh.auto_ci_approval import approve_and_wait_ci, main
from ms_data.gh.auto_review_merge import merge_pull_request

from workflow_contract import workflow_text

REF = "data/auto-update-20261016"
SHA = "a" * 40
REPO = "owner/repo"


def test_approval_workflow_uses_trusted_main_and_serializes_only_eligible_job():
    text = workflow_text("approve_data_ci.yml")
    assert "ref: main" in text
    assert "persist-credentials: false" in text
    assert "  pull-requests: read" in text
    assert "  actions: write" in text
    assert "    concurrency:" in text
    assert "\nconcurrency:" not in text
    assert "ms_data.gh.auto_ci_approval" in text


def test_cli_approves_only_eligible_run(fake_time):
    data, deps, calls = scenario(fake_time)
    assert main(["--repo", REPO, "--run-id", "456"], deps=deps) == 0
    assert sum(call[2].endswith("/approve") for call in calls) == 1
    assert not any(call[1:3] == ["pr", "merge"] for call in calls)


def test_cli_ignores_already_successful_ci(fake_time):
    data, deps, calls = scenario(fake_time)
    data["run"]["conclusion"] = "success"
    assert main(["--repo", REPO, "--run-id", "456"], deps=deps) == 0
    assert len(calls) == 1


def scenario(fake_time, *, result="success", approval_denied=False):
    pull = {
        "state": "open",
        "draft": False,
        "user": {"login": "github-actions[bot]"},
        "base": {"ref": "main"},
        "head": {"ref": REF, "sha": SHA, "repo": {"full_name": REPO}},
        "body": "<!-- source_run_id:123 -->",
        "changed_files": 1,
    }
    run = {
        "id": 456,
        "created_at": "2026-10-16T09:00:00Z",
        "event": "pull_request",
        "head_sha": SHA,
        "head_branch": REF,
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "action_required",
        "actor": {"login": "github-actions[bot]"},
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
    }
    data = {
        "pull": pull,
        "fresh_pull": None,
        "run": run,
        "files": [{"filename": "msData.json", "status": "modified"}],
        "jobs": {"total_count": 0, "jobs": []},
        "source": {
            "id": 123,
            "path": ".github/workflows/data_update.yml",
            "event": "schedule",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": REPO},
        },
    }
    calls = []
    approved = False
    merged = False
    pull_reads = 0

    def runner(args):
        nonlocal approved, merged, pull_reads
        calls.append(args)
        if args[1:3] == ["pr", "view"]:
            return json.dumps(
                {
                    "state": "MERGED" if merged else "OPEN",
                    "headRefOid": SHA,
                    "mergeCommit": {"oid": "merge-sha"} if merged else None,
                }
            )
        if args[1:3] == ["pr", "merge"]:
            assert approved and result == "success"
            merged = True
            return ""
        endpoint = args[2]
        if endpoint.endswith("/approve"):
            if approval_denied:
                raise subprocess.CalledProcessError(1, args, stderr="HTTP 403")
            approved = True
            return ""
        current = copy.deepcopy(data["run"])
        current["id"] = data.get("response_id", current["id"])
        if approved:
            current["conclusion"] = result
        if "/actions/workflows/ci.yml/runs?" in endpoint:
            return json.dumps([current])
        if "/pulls?" in endpoint:
            return json.dumps([{**data["pull"], "number": 97}])
        if endpoint.endswith("/pulls/97"):
            pull_reads += 1
            return json.dumps(
                data["fresh_pull"]
                if pull_reads > 1 and data["fresh_pull"] is not None
                else data["pull"]
            )
        if endpoint.endswith("/files"):
            return json.dumps(data["files"])
        if endpoint.endswith("/123"):
            return json.dumps(data["source"])
        if endpoint.endswith("/jobs"):
            return json.dumps(data["jobs"])
        if endpoint.endswith("/456"):
            return json.dumps(current)
        pytest.fail(f"unexpected command: {args}")

    deps = replace(ReviewDeps.default(), clock=fake_time, run_gh=runner)
    return (data, deps, calls)


def approve(data, deps, **overrides):
    kwargs = {
        "repo": REPO, "pr_number": "97", "ref": REF, "sha": SHA, "run": data["run"], "deps": deps
    }
    kwargs.update(overrides)
    return approve_and_wait_ci(**kwargs)


def test_trusted_approval_then_ci_success_then_head_matched_merge(fake_time):
    data, deps, calls = scenario(fake_time)
    result = merge_pull_request(
        repo=REPO, pr_number="97", head_ref=REF, head_sha=SHA, deps=deps
    )
    assert result.merged
    assert sum((call[2].endswith("/approve") for call in calls)) == 1
    merge = next((call for call in calls if call[1:3] == ["pr", "merge"]))
    assert merge[-2:] == ["--match-head-commit", SHA]
    assert "--admin" not in merge
    assert sum(("/actions/workflows/ci.yml/runs?" in call[2] for call in calls)) == 2


@pytest.mark.parametrize(
    "kind",
    [
        "author",
        "fork",
        "draft",
        "base",
        "head",
        "marker",
        "code",
        "delete",
        "missing_data",
        "count",
        "source",
        "source_id",
        "jobs",
        "ci_target",
        "ci_actor",
        "ci_id",
        "head_race",
    ],
)
def test_untrusted_scope_is_never_approved(fake_time, kind):
    data, deps, calls = scenario(fake_time)
    if kind == "author":
        data["pull"]["user"]["login"] = "someone"
    elif kind == "fork":
        data["pull"]["head"]["repo"]["full_name"] = "other/repo"
    elif kind == "draft":
        data["pull"]["draft"] = True
    elif kind == "base":
        data["pull"]["base"]["ref"] = "release"
    elif kind == "head":
        data["pull"]["head"]["sha"] = "new"
    elif kind == "marker":
        data["pull"]["body"] = ""
    elif kind == "code":
        data["files"][0]["filename"] = "ms_data/tasks.py"
    elif kind == "delete":
        data["files"][0]["status"] = "removed"
    elif kind == "missing_data":
        data["files"] = []
    elif kind == "count":
        data["pull"]["changed_files"] = 2
    elif kind == "source":
        data["source"]["conclusion"] = "failure"
    elif kind == "source_id":
        data["source"]["id"] = 999
    elif kind == "jobs":
        data["jobs"]["total_count"] = 1
    elif kind == "ci_target":
        data["run"]["head_sha"] = "other"
    elif kind == "ci_actor":
        data["run"]["actor"]["login"] = "someone"
    elif kind == "ci_id":
        data["response_id"] = 789
    elif kind == "head_race":
        data["fresh_pull"] = copy.deepcopy(data["pull"])
        data["fresh_pull"]["head"]["sha"] = "new"
    assert approve(data, deps)
    assert not any((call[2].endswith("/approve") for call in calls))


@pytest.mark.parametrize("ref", ["feature/work", "data/auto-update-20261301"])
def test_non_data_branch_or_invalid_date_is_not_approved(fake_time, ref):
    data, deps, calls = scenario(fake_time)
    assert approve(data, deps, ref=ref)
    assert not any((call[2].endswith("/approve") for call in calls))


@pytest.mark.parametrize(
    "result,denied,reason",
    [
        ("failure", False, "ci_not_success"),
        ("action_required", False, "ci_approval_timeout"),
        ("success", True, "ci_approval_denied"),
    ],
)
def test_no_merge_when_approval_or_ci_does_not_succeed(
    fake_time, result, denied, reason
):
    data, deps, calls = scenario(fake_time, result=result, approval_denied=denied)
    outcome = merge_pull_request(
        repo=REPO, pr_number="97", head_ref=REF, head_sha=SHA, deps=deps
    )
    assert not outcome.merged
    assert outcome.skip_reason == reason
    assert sum((call[2].endswith("/approve") for call in calls)) == 1
    assert not any((call[1:3] == ["pr", "merge"] for call in calls))
