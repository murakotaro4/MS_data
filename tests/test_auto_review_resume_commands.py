"""resume サブコマンドのテスト（ReviewDeps 注入・findings 停止・superseded）。"""

import json
from dataclasses import replace

from ms_data.gh import auto_review_merge
from ms_data.gh.auto_review_merge import (
    ReviewDeps,
    main,
)

from auto_review_helpers import (
    BASELINE,
    HEAD_SHA,
    PAT_LOGIN,
    codex_finding,
    metrics,
    run_main,
    script_metrics,
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
