"""resolve-target-pr / establish-baseline サブコマンドと baseline 依存 metrics のテスト。"""

from ms_data.gh.auto_review_merge import (
    collect_review_metrics,
)

from auto_review_helpers import (
    BASELINE,
    CODEX_BOT,
    HEAD_SHA,
    run_main,
)

# ---------------------------------------------------------------------------
# 層B: cmd_*（main(argv) 経由、出力は tmp_path）
# ---------------------------------------------------------------------------


def test_cmd_resolve_target_pr_writes_outputs(
    fake_gh, read_github_output, tmp_path, capsys
):
    fake_gh.responses["/pulls?state=open"] = [
        {
            "number": 97,
            "created_at": "2026-05-31T09:10:00Z",
            "user": {"login": "github-actions[bot]"},
            "head": {"ref": "data/auto-update-20260531", "sha": HEAD_SHA},
            "body": "source_run_id:111",
        }
    ]
    out = tmp_path / "out.txt"

    rc = run_main(
        [
            "resolve-target-pr",
            "--repo",
            "owner/repo",
            "--run-id",
            "111",
            "--run-created-at",
            "2026-05-31T09:00:25Z",
            "--github-output",
            str(out),
        ],
        fake_gh,
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["skip"] == "false"
    assert outputs["pr"] == "97"
    assert outputs["head_sha"] == HEAD_SHA
    assert outputs["resolved_by"] == "source_run_id_marker"
    assert "Resolved PR #97" in capsys.readouterr().out


def test_cmd_resolve_target_pr_skip_path(fake_gh, read_github_output, tmp_path, capsys):
    out = tmp_path / "out.txt"

    rc = run_main(
        [
            "resolve-target-pr",
            "--repo",
            "owner/repo",
            "--run-id",
            "111",
            "--run-created-at",
            "2026-05-31T09:00:25Z",
            "--github-output",
            str(out),
        ],
        fake_gh,
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["skip"] == "true"
    assert outputs["skip_reason"] == "no_target_pr"
    assert "No matching open PR found." in capsys.readouterr().out


def test_cmd_establish_baseline_writes_created_at(
    fake_gh, read_github_output, tmp_path
):
    fake_gh.responses["/pulls/97"] = {
        "number": 97,
        "created_at": BASELINE,
        "head": {"sha": HEAD_SHA, "ref": "data/auto-update-20260531"},
    }
    # committer が PR created_at より古い場合は PR created_at を採用
    fake_gh.responses[f"/commits/{HEAD_SHA}"] = {
        "commit": {"committer": {"date": "2026-05-30T01:00:00Z"}}
    }
    out = tmp_path / "out.txt"

    rc = run_main(
        [
            "establish-baseline",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--github-output",
            str(out),
        ],
        fake_gh,
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["baseline_created_at"] == BASELINE
    assert fake_gh.posted_comments == []


def test_cmd_establish_baseline_uses_commit_date_after_force_push(
    fake_gh, read_github_output, tmp_path
):
    commit_date = "2026-05-31T15:00:00Z"
    fake_gh.responses["/pulls/97"] = {
        "number": 97,
        "created_at": BASELINE,
        "head": {"sha": HEAD_SHA, "ref": "data/auto-update-20260531"},
    }
    fake_gh.responses[f"/commits/{HEAD_SHA}"] = {
        "commit": {"committer": {"date": commit_date}}
    }
    out = tmp_path / "out.txt"

    rc = run_main(
        [
            "establish-baseline",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--github-output",
            str(out),
        ],
        fake_gh,
    )

    assert rc == 0
    assert read_github_output(out)["baseline_created_at"] == commit_date


def test_cmd_establish_baseline_uses_latest_force_push_event(
    fake_gh, read_github_output, tmp_path
):
    force_push_at = "2026-05-31T18:00:00Z"
    fake_gh.responses["/pulls/97"] = {
        "number": 97,
        "created_at": BASELINE,
        "head": {"sha": HEAD_SHA, "ref": "data/auto-update-20260531"},
    }
    # 古い committer 日時を force-push しても、timeline の最終 force-push が勝つ
    fake_gh.responses[f"/commits/{HEAD_SHA}"] = {
        "commit": {"committer": {"date": "2026-05-30T01:00:00Z"}}
    }
    fake_gh.responses["/issues/97/timeline"] = [
        {"event": "committed", "created_at": "2026-05-31T17:00:00Z"},
        {
            "event": "head_ref_force_pushed",
            "created_at": "2026-05-31T12:00:00Z",
        },
        {
            "event": "head_ref_force_pushed",
            "created_at": force_push_at,
        },
    ]
    out = tmp_path / "out.txt"

    rc = run_main(
        [
            "establish-baseline",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--github-output",
            str(out),
        ],
        fake_gh,
    )

    assert rc == 0
    assert read_github_output(out)["baseline_created_at"] == force_push_at


def test_collect_review_metrics_ignores_old_no_issue_before_force_push_baseline(
    fake_gh,
):
    # force-push 後の HEAD committer 日時を since にすると、旧 no-issue は terminal にならない
    fake_gh.responses["/issues/97/comments"] = [
        {
            "user": {"login": CODEX_BOT},
            "created_at": "2026-05-31T10:00:00Z",
            "body": "Codex Review: Didn't find any major issues. 旧 HEAD 向け",
        }
    ]

    metrics = collect_review_metrics(
        client=fake_gh,
        pr_number="97",
        head_sha=HEAD_SHA,
        trigger_comment_ids=[],
        since="2026-05-31T15:00:00Z",
    )

    assert metrics["terminal_count"] == 0
    assert metrics["no_issue_comment_count"] == 0
    assert metrics["merge_ok"] is False
    assert metrics["stop_reason"] == "no_response"
