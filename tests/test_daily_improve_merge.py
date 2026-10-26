"""daily_improve_merge のゲート判定・停止・マージ経路のテスト。"""

import subprocess
from dataclasses import replace

import pytest

from ms_data.gh import daily_improve_merge
from ms_data.gh.argtypes import ReviewDeps

from auto_review_helpers import metrics, successful_ci_runs
from workflow_contract import assert_contains, workflow_text

REPO = "owner/repo"
HEAD = "head-sha"
BRANCH = "claude/daily-improve-20261026"


def make_pull(**overrides) -> dict:
    pull = {
        "number": 368,
        "state": "open",
        "draft": False,
        "created_at": "2026-10-25T23:04:47Z",
        "user": {"login": "owner"},
        "labels": [{"name": daily_improve_merge.MERGE_LABEL}],
        "base": {"ref": "main"},
        "head": {"ref": BRANCH, "sha": HEAD, "repo": {"full_name": REPO}},
    }
    pull.update(overrides)
    return pull


class FakeGh:
    """`gh pr view` / CI runs / `gh pr merge` を記録しながら応答する run_gh 代替。"""

    def __init__(self, *, ci_payload: str):
        self.ci_payload = ci_payload.replace("data/auto-update-20260531", BRANCH)
        self.merged = False
        self.calls: list[list[str]] = []

    def __call__(self, args, **_kwargs) -> str:
        self.calls.append(list(args))
        if args[1:3] == ["pr", "view"]:
            state = "MERGED" if self.merged else "OPEN"
            merge = '{"oid": "merge-sha"}' if self.merged else "null"
            return f'{{"state": "{state}", "headRefOid": "{HEAD}", "mergeCommit": {merge}}}'
        if args[1] == "api":
            return self.ci_payload
        if args[1:3] == ["pr", "merge"]:
            self.merged = True
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


def run(tmp_path, fake_gh, *, pull, gate, ci_payload=None):
    fake_gh.responses[f"repos/{REPO}/pulls/368"] = pull
    fake_gh.repo = REPO
    runner = FakeGh(ci_payload=ci_payload or successful_ci_runs(HEAD))
    collected: list[dict] = []

    def collect(**kwargs):
        collected.append(kwargs)
        return gate

    deps = replace(
        ReviewDeps.default(),
        client=lambda _repo: fake_gh,
        run_gh=runner,
        collect_metrics=collect,
        run_url=lambda: "https://example.invalid/run/1",
    )
    output = tmp_path / "output"
    code = daily_improve_merge.main(
        [
            "--repo",
            REPO,
            "--pr-number",
            "368",
            "--github-output",
            str(output),
            "--step-summary",
            str(tmp_path / "summary"),
        ],
        deps_factory=lambda: deps,
    )
    return code, output.read_text(encoding="utf-8"), runner, collected


CLEAN = metrics(
    merge_ok=True, terminal_count=1, no_issue_comment_count=1, stop_reason="none"
)


def test_merges_when_all_gates_pass(tmp_path, fake_gh):
    code, output, runner, collected = run(
        tmp_path, fake_gh, pull=make_pull(), gate=CLEAN
    )

    assert code == 0
    assert "merged=true" in output
    assert "merge_commit_sha=merge-sha" in output
    merge_call = next(call for call in runner.calls if call[1:3] == ["pr", "merge"])
    assert "--match-head-commit" in merge_call and HEAD in merge_call
    assert "--delete-branch" in merge_call
    assert collected[0]["head_sha"] == HEAD
    assert fake_gh.posted_comments == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"draft": True}, "draft"),
        ({"base": {"ref": "develop"}}, "base_mismatch"),
        (
            {"head": {"ref": BRANCH, "sha": HEAD, "repo": {"full_name": "fork/repo"}}},
            "head_repo_mismatch",
        ),
        (
            {
                "head": {
                    "ref": "data/auto-update-20261026",
                    "sha": HEAD,
                    "repo": {"full_name": REPO},
                }
            },
            "head_ref_mismatch",
        ),
        ({"user": {"login": "someone"}}, "author_mismatch"),
    ],
)
def test_ineligible_pr_is_stopped_with_comment(tmp_path, fake_gh, overrides, reason):
    code, output, runner, collected = run(
        tmp_path, fake_gh, pull=make_pull(**overrides), gate=CLEAN
    )

    assert code == 1
    assert f"skip_reason={reason}" in output
    assert not any(call[1:3] == ["pr", "merge"] for call in runner.calls)
    assert collected == []
    assert reason in fake_gh.posted_comments[0][1]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"state": "closed"}, "not_open"),
        ({"labels": []}, "label_missing"),
    ],
)
def test_stale_event_stops_without_comment(tmp_path, fake_gh, overrides, reason):
    code, output, _runner, _collected = run(
        tmp_path, fake_gh, pull=make_pull(**overrides), gate=CLEAN
    )

    assert code == 1
    assert f"skip_reason={reason}" in output
    assert fake_gh.posted_comments == []


@pytest.mark.parametrize(
    ("gate", "reason"),
    [
        (
            metrics(finding_count=1, review_complete=True, stop_reason="findings"),
            "codex_findings",
        ),
        (metrics(stop_reason="no_response"), "codex_no_response"),
    ],
)
def test_codex_gate_blocks_merge(tmp_path, fake_gh, gate, reason):
    code, output, runner, _collected = run(
        tmp_path, fake_gh, pull=make_pull(), gate=gate
    )

    assert code == 1
    assert f"skip_reason={reason}" in output
    assert not any(call[1:3] == ["pr", "merge"] for call in runner.calls)
    assert daily_improve_merge.MERGE_LABEL in fake_gh.posted_comments[0][1]


def test_ci_not_success_blocks_merge(tmp_path, fake_gh):
    failed = successful_ci_runs(HEAD).replace('"success"', '"failure"')
    code, output, runner, _collected = run(
        tmp_path, fake_gh, pull=make_pull(), gate=CLEAN, ci_payload=failed
    )

    assert code == 1
    assert "skip_reason=ci_not_success" in output
    assert not any(call[1:3] == ["pr", "merge"] for call in runner.calls)


def test_workflow_runs_only_on_label_from_base_branch():
    text = workflow_text("daily_improve_merge.yml")

    assert_contains(
        text,
        [
            "pull_request_target:",
            "types: [labeled]",
            "github.event.label.name == 'daily-improve-merge'",
            "persist-credentials: false",
            "GH_TOKEN: ${{ github.token }}",
            "uv run python -m ms_data.gh.daily_improve_merge",
        ],
    )
    assert "ref:" not in text


def test_merge_error_still_stops_with_comment_and_label_removal(tmp_path, fake_gh):
    fake_gh.repo = REPO
    fake_gh.responses[f"repos/{REPO}/pulls/368"] = make_pull()
    deleted: list[str] = []
    original_api_json = fake_gh.api_json

    def api_json(endpoint, *, method="GET", **kwargs):
        if method == "DELETE":
            deleted.append(endpoint)
            return []
        return original_api_json(endpoint, method=method, **kwargs)

    fake_gh.api_json = api_json

    def failing_gh(args, **_kwargs):
        if args[1:3] == ["pr", "merge"]:
            raise subprocess.CalledProcessError(1, args)
        return FakeGh(ci_payload=successful_ci_runs(HEAD))(args)

    deps = replace(
        ReviewDeps.default(),
        client=lambda _repo: fake_gh,
        run_gh=failing_gh,
        collect_metrics=lambda **_kwargs: CLEAN,
        run_url=lambda: "",
    )
    output = tmp_path / "output"
    code = daily_improve_merge.main(
        ["--repo", REPO, "--pr-number", "368", "--github-output", str(output)],
        deps_factory=lambda: deps,
    )

    assert code == 1
    assert "skip_reason=error_CalledProcessError" in output.read_text(encoding="utf-8")
    assert "error_CalledProcessError" in fake_gh.posted_comments[0][1]
    assert deleted == [
        f"repos/{REPO}/issues/368/labels/{daily_improve_merge.MERGE_LABEL}"
    ]
