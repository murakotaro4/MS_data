import json
from dataclasses import replace
from pathlib import Path

import pytest

from ms_data.gh.argtypes import ReviewDeps
from ms_data.gh.auto_review_merge import build_parser, cmd_merge, main


def _view(state: str, *, head_sha: str = "head-sha", merge_sha: str = "") -> str:
    return json.dumps(
        {
            "state": state,
            "headRefOid": head_sha,
            "mergeCommit": {"oid": merge_sha} if merge_sha else None,
        }
    )


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "merge",
        "--repo",
        "owner/repo",
        "--pr-number",
        "97",
        "--head-ref",
        "data/auto-update-20260531",
        "--head-sha",
        "head-sha",
        "--source-run-id",
        "111",
        "--github-output",
        str(tmp_path / "output.txt"),
        "--step-summary",
        str(tmp_path / "summary.md"),
        *extra,
    ]


def _deps(fake_time, responses, calls, *, fail_on=None):
    scripted = iter(responses)

    def run_gh(command):
        calls.append(command)
        if fail_on is not None and fail_on(command):
            raise RuntimeError("injected notification failure")
        if command[1:3] == ["pr", "view"]:
            return next(scripted)
        return ""

    return replace(ReviewDeps.default(), clock=fake_time, run_gh=run_gh)


@pytest.mark.parametrize(
    ("extra", "expected_rc"),
    [(["--skip-if-not-open"], 0), ([], 1)],
)
def test_merge_not_open_contract(
    fake_time, tmp_path, read_github_output, extra, expected_rc
):
    calls = []
    deps = _deps(fake_time, [_view("CLOSED")], calls)

    rc = main(_argv(tmp_path, *extra), deps_factory=lambda: deps)

    assert rc == expected_rc
    assert read_github_output(tmp_path / "output.txt") == {
        "merged": "false",
        "skip_reason": "not_open",
        "pr_state": "CLOSED",
    }
    assert len(calls) == 1
    if expected_rc:
        assert "- reason: not_open" in (tmp_path / "summary.md").read_text()
    else:
        assert not (tmp_path / "summary.md").exists()


@pytest.mark.parametrize(
    ("responses", "reason", "state", "expected_gets"),
    [
        ([_view("OPEN", head_sha="changed")], "head_sha_mismatch", "OPEN", 1),
        (
            [_view("OPEN"), _view("OPEN")],
            "not_merged_state",
            "OPEN",
            2,
        ),
        (
            [_view("OPEN"), _view("MERGED")],
            "empty_merge_commit",
            "MERGED",
            2,
        ),
    ],
)
def test_merge_validation_failures(
    fake_time,
    tmp_path,
    read_github_output,
    responses,
    reason,
    state,
    expected_gets,
):
    calls = []
    deps = _deps(fake_time, responses, calls)

    assert main(_argv(tmp_path), deps_factory=lambda: deps) == 1

    outputs = read_github_output(tmp_path / "output.txt")
    assert outputs == {
        "merged": "false",
        "skip_reason": reason,
        "pr_state": state,
    }
    get_calls = [call for call in calls if call[1:3] == ["pr", "view"]]
    assert len(get_calls) == expected_gets
    assert all(call[-1] == "state,headRefOid,mergeCommit" for call in get_calls)
    assert f"- reason: {reason}" in (tmp_path / "summary.md").read_text()


def test_merge_success_writes_outputs_then_dispatches(
    fake_time, tmp_path, read_github_output
):
    calls = []
    deps = _deps(fake_time, [_view("OPEN"), _view("MERGED", merge_sha="merge")], calls)

    assert main(_argv(tmp_path), deps_factory=lambda: deps) == 0

    assert read_github_output(tmp_path / "output.txt") == {
        "merged": "true",
        "merge_commit_sha": "merge",
        "head_ref": "data/auto-update-20260531",
        "skip_reason": "",
        "pr_state": "MERGED",
    }
    assert [call[1:3] for call in calls] == [
        ["pr", "view"],
        ["pr", "merge"],
        ["pr", "view"],
        ["workflow", "run"],
    ]


def test_merge_already_merged_dispatches_and_posts_recovered_comment(
    fake_time, tmp_path, read_github_output
):
    calls = []
    deps = _deps(fake_time, [_view("MERGED", merge_sha="merge")], calls)

    assert (
        main(
            _argv(tmp_path, "--comment-marker", "recovered", "--run-id", "555"),
            deps_factory=lambda: deps,
        )
        == 0
    )

    assert read_github_output(tmp_path / "output.txt") == {
        "merged": "true",
        "merge_commit_sha": "merge",
        "head_ref": "data/auto-update-20260531",
        "skip_reason": "",
        "pr_state": "MERGED",
    }
    assert [call[1:3] for call in calls] == [
        ["pr", "view"],
        ["workflow", "run"],
        ["api", "repos/owner/repo/issues/97/comments"],
    ]
    assert not any(call[1:3] == ["pr", "merge"] for call in calls)


def test_merge_already_merged_without_commit_is_explicit_failure(
    fake_time, tmp_path, read_github_output
):
    calls = []
    deps = _deps(fake_time, [_view("MERGED")], calls)

    assert main(_argv(tmp_path), deps_factory=lambda: deps) == 1

    assert read_github_output(tmp_path / "output.txt") == {
        "merged": "false",
        "skip_reason": "empty_merge_commit",
        "pr_state": "MERGED",
    }
    assert len(calls) == 1
    assert "- reason: empty_merge_commit" in (tmp_path / "summary.md").read_text()


def test_merge_already_merged_with_different_head_fails_without_notifications(
    fake_time, tmp_path, read_github_output
):
    calls = []
    deps = _deps(
        fake_time,
        [_view("MERGED", head_sha="different-head", merge_sha="merge")],
        calls,
    )

    assert (
        main(
            _argv(tmp_path, "--comment-marker", "recovered", "--run-id", "555"),
            deps_factory=lambda: deps,
        )
        == 1
    )

    assert read_github_output(tmp_path / "output.txt") == {
        "merged": "false",
        "skip_reason": "head_sha_mismatch",
        "pr_state": "MERGED",
    }
    assert [call[1:3] for call in calls] == [["pr", "view"]]
    assert not any(call[1:3] == ["workflow", "run"] for call in calls)
    assert not any(call[1:2] == ["api"] for call in calls)
    assert "- reason: head_sha_mismatch" in (tmp_path / "summary.md").read_text()


def test_dispatch_failure_preserves_merged_outputs_and_skips_comment(
    fake_time, tmp_path, read_github_output
):
    calls = []
    deps = _deps(
        fake_time,
        [_view("OPEN"), _view("MERGED", merge_sha="merge")],
        calls,
        fail_on=lambda command: command[1:3] == ["workflow", "run"],
    )

    assert (
        main(
            _argv(tmp_path, "--comment-marker", "recovered", "--run-id", "555"),
            deps_factory=lambda: deps,
        )
        == 1
    )

    assert read_github_output(tmp_path / "output.txt")["merged"] == "true"
    assert not any(call[1:2] == ["api"] for call in calls)
    assert (
        "Merge succeeded, notification failed" in (tmp_path / "summary.md").read_text()
    )


def test_comment_failure_occurs_after_dispatch_and_preserves_outputs(
    fake_time, tmp_path, read_github_output
):
    calls = []
    deps = _deps(
        fake_time,
        [_view("OPEN"), _view("MERGED", merge_sha="merge")],
        calls,
        fail_on=lambda command: command[1:2] == ["api"],
    )

    assert (
        main(
            _argv(tmp_path, "--comment-marker", "recovered", "--run-id", "555"),
            deps_factory=lambda: deps,
        )
        == 1
    )

    assert read_github_output(tmp_path / "output.txt")["merged"] == "true"
    assert [call[1:3] for call in calls][-2:] == [
        ["workflow", "run"],
        ["api", "repos/owner/repo/issues/97/comments"],
    ]


def test_dispatch_notify_boolean_parser():
    parser = build_parser()
    base = _argv(Path("/tmp"))

    assert parser.parse_args(base).dispatch_notify is True
    assert (
        parser.parse_args([*base, "--dispatch-notify", "false"]).dispatch_notify
        is False
    )
    assert parser.parse_args([*base, "--dispatch-notify"]).dispatch_notify is True


def test_invalid_comment_marker_is_rejected_before_side_effects(tmp_path, capsys):
    def forbidden_deps_factory():
        pytest.fail("引数エラー時に依存を生成してはならない")

    with pytest.raises(SystemExit) as exc_info:
        main(
            _argv(tmp_path, "--comment-marker", "unsupported"),
            deps_factory=forbidden_deps_factory,
        )

    assert exc_info.value.code == 2
    assert "invalid choice: 'unsupported'" in capsys.readouterr().err
    assert not (tmp_path / "output.txt").exists()
    assert not (tmp_path / "summary.md").exists()


def test_cmd_merge_rejects_invalid_comment_marker_before_merge(fake_time, tmp_path):
    args = build_parser().parse_args(_argv(tmp_path))
    args.comment_marker = "unsupported"
    calls = []
    deps = _deps(fake_time, [], calls)

    with pytest.raises(ValueError, match="unsupported comment marker"):
        cmd_merge(args, deps)

    assert calls == []


def test_auto_review_merge_workflow_uses_merge_subcommand_once():
    workflow = Path(".github/workflows/auto_review_merge.yml").read_text(
        encoding="utf-8"
    )
    command_module = Path("ms_data/gh/auto_review_merge.py").read_text(encoding="utf-8")

    assert "- id: merge" in workflow
    assert workflow.count("ms_data.gh.auto_review_merge merge") == 1
    assert '--repo "${{ steps.prepare.outputs.repo }}"' in workflow
    assert '--pr-number "${{ steps.resolve.outputs.pr }}"' in workflow
    assert '--head-sha "${{ steps.resolve.outputs.head_sha }}"' in workflow
    assert '--source-run-id "${{ steps.prepare.outputs.run_id }}"' in workflow
    merge_step = workflow[
        workflow.index("- id: merge") : workflow.index(
            "- name: Write auto review report"
        )
    ]
    assert "--skip-if-not-open" in merge_step
    assert "steps.merge.outputs.merged" in workflow
    assert "steps.merge.outcome" in workflow
    for output_name in ("merged", "merge_commit_sha", "head_ref"):
        assert f'"{output_name}"' in command_module
    assert "gh pr merge" not in workflow
    assert workflow.count("post_merge_notify.yml") == 0
    assert command_module.count('"post_merge_notify.yml"') == 1
