"""auto_review_merge の GitHubClient / cmd_* サブコマンドのテスト。

GitHubClient 自体は gh_json.subprocess.run のパッチで、cmd_* は conftest の
FakeGitHubClient / FakeTime 注入で検証する（実 gh CLI は一切呼ばない）。
"""

import json
from types import SimpleNamespace

from ms_data.gh import auto_review_merge
from ms_data.gh import gh_json
from ms_data.gh.auto_review_merge import (
    GITHUB_ACTIONS_BOT,
    GitHubClient,
    collect_review_metrics,
    ensure_review_comment,
    find_latest_bot_comment,
    main,
    retry_marker,
    review_marker,
)

CODEX_BOT = "chatgpt-codex-connector[bot]"
HEAD_SHA = "abc123"
PAT_LOGIN = "codex-trigger-user"
BASELINE = "2026-05-31T09:10:00Z"


def _codex_review(commit_id: str = HEAD_SHA) -> dict:
    return {"user": {"login": CODEX_BOT}, "commit_id": commit_id}


def _codex_finding(commit_id: str = HEAD_SHA) -> dict:
    return {
        "user": {"login": CODEX_BOT},
        "commit_id": commit_id,
        "path": "msData.json",
        "line": 12,
        "body": "ここにバグがあります",
    }


def _metrics(**overrides) -> dict:
    base = {
        "review_count": 0,
        "finding_count": 0,
        "reaction_count": 0,
        "issue_comment_count": 0,
        "no_issue_comment_count": 0,
        "disconnect_count": 0,
        "terminal_count": 0,
        "review_complete": False,
        "merge_ok": False,
        "stop_reason": "no_response",
    }
    base.update(overrides)
    return base


def _script_metrics(monkeypatch, script: list[dict]) -> list[dict]:
    """collect_review_metrics を呼び出し回数で返値を切り替えるスタブに差し替える。"""
    calls: list[dict] = []

    def fake(**kwargs):
        index = min(len(calls), len(script) - 1)
        calls.append(kwargs)
        return script[index]

    monkeypatch.setattr(auto_review_merge, "collect_review_metrics", fake)
    return calls


# ---------------------------------------------------------------------------
# 層A: GitHubClient（gh_json.subprocess.run パッチ）
# ---------------------------------------------------------------------------


def test_api_json_builds_get_command(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='[{"id": 1}]')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")
    result = client.api_json(
        "repos/owner/repo/pulls",
        paginate=True,
        headers=["Accept: application/vnd.github+json"],
    )

    assert captured["cmd"] == [
        "gh",
        "api",
        "repos/owner/repo/pulls",
        "--paginate",
        "-H",
        "Accept: application/vnd.github+json",
    ]
    assert result == [{"id": 1}]


def test_api_json_post_with_fields(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='{"id": 5}')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")
    result = client.post_issue_comment("97", "hello")

    assert captured["cmd"] == [
        "gh",
        "api",
        "repos/owner/repo/issues/97/comments",
        "-X",
        "POST",
        "-f",
        "body=hello",
    ]
    assert result == {"id": 5}


def test_api_json_parses_paginated_stream(monkeypatch):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout='[{"id": 1}]\n[{"id": 2}]')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")

    assert client.issue_comments("97") == [{"id": 1}, {"id": 2}]


def test_issue_comment_fetches_detail(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='{"id": 42}')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")

    assert client.issue_comment("42") == {"id": 42}
    assert captured["cmd"] == ["gh", "api", "repos/owner/repo/issues/comments/42"]


# ---------------------------------------------------------------------------
# 層B: 関数単位（FakeGitHubClient）
# ---------------------------------------------------------------------------


def test_ensure_review_comment_posts_when_missing(fake_gh):
    marker = review_marker(HEAD_SHA)
    comment_id, created_at, created_new = ensure_review_comment(
        client=fake_gh, pr_number="97", marker=marker
    )

    assert created_new is True
    assert comment_id == "1000"
    assert created_at == "2026-05-31T10:00:00Z"
    assert len(fake_gh.posted_comments) == 1
    body = fake_gh.posted_comments[0][1]
    assert body.startswith("@codex review")
    assert marker in body


def test_ensure_review_comment_reuses_existing(fake_gh):
    marker = review_marker(HEAD_SHA)
    fake_gh.responses["/issues/97/comments"] = [
        {
            "id": 42,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "github-actions[bot]"},
            "body": f"@codex review\n\n{marker}",
        }
    ]
    fake_gh.responses["/issues/comments/42"] = {
        "id": 42,
        "created_at": "2026-05-31T09:00:00Z",
    }

    comment_id, created_at, created_new = ensure_review_comment(
        client=fake_gh, pr_number="97", marker=marker
    )

    assert created_new is False
    assert comment_id == "42"
    assert created_at == "2026-05-31T09:00:00Z"
    assert fake_gh.posted_comments == []


def test_ensure_review_comment_reuses_pat_login_comment(fake_gh):
    marker = retry_marker(2, HEAD_SHA)
    fake_gh.responses["/issues/97/comments"] = [
        {
            "id": 77,
            "created_at": "2026-05-31T09:30:00Z",
            "user": {"login": PAT_LOGIN},
            "body": f"@codex review\n\n{marker}",
        }
    ]
    fake_gh.responses["/issues/comments/77"] = {
        "id": 77,
        "created_at": "2026-05-31T09:30:00Z",
    }

    comment_id, _, created_new = ensure_review_comment(
        client=fake_gh,
        pr_number="97",
        marker=marker,
        allowed_logins={GITHUB_ACTIONS_BOT, PAT_LOGIN},
    )

    assert created_new is False
    assert comment_id == "77"
    assert fake_gh.posted_comments == []


def test_find_latest_bot_comment_rejects_other_user_same_marker():
    marker = retry_marker(2, HEAD_SHA)
    comments = [
        {
            "id": 1,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "random-user"},
            "body": f"@codex review\n\n{marker}",
        }
    ]
    assert (
        find_latest_bot_comment(comments, marker, {GITHUB_ACTIONS_BOT, PAT_LOGIN})
        is None
    )


def test_collect_review_metrics_aggregates_reactions_across_triggers(fake_gh):
    fake_gh.responses["/pulls/97/reviews"] = [_codex_review()]
    fake_gh.responses["/issues/comments/10/reactions"] = [
        {"user": {"login": CODEX_BOT}, "content": "+1"}
    ]
    fake_gh.responses["/issues/comments/11/reactions"] = [
        {"user": {"login": CODEX_BOT}, "content": "+1"}
    ]

    metrics = collect_review_metrics(
        client=fake_gh,
        pr_number="97",
        head_sha=HEAD_SHA,
        trigger_comment_ids=["10", "11"],
        since="2026-05-31T10:00:00Z",
    )

    assert metrics["reaction_count"] == 2
    assert metrics["review_count"] == 1
    assert metrics["merge_ok"] is True


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

    rc = main(
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
        ]
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

    rc = main(
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
        ]
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

    rc = main(
        [
            "establish-baseline",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--github-output",
            str(out),
        ]
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

    rc = main(
        [
            "establish-baseline",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--github-output",
            str(out),
        ]
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

    rc = main(
        [
            "establish-baseline",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--github-output",
            str(out),
        ]
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


def _wait_argv(
    out,
    summary,
    *,
    max_attempts="2",
    settle="0",
    pat_available="true",
    pat_login=PAT_LOGIN,
):
    return [
        "wait-for-review",
        "--repo",
        "owner/repo",
        "--pr-number",
        "97",
        "--head-sha",
        HEAD_SHA,
        "--baseline-created-at",
        BASELINE,
        "--pat-available",
        pat_available,
        "--pat-login",
        pat_login,
        "--max-attempts",
        max_attempts,
        # timeout=60, poll=30 -> 1 attempt あたり最大2ポーリング（t=0, t=30）
        "--attempt-timeout-seconds",
        "60",
        "--poll-seconds",
        "30",
        "--settle-seconds",
        settle,
        "--github-output",
        str(out),
        "--step-summary",
        str(summary),
    ]


def test_cmd_wait_for_review_posts_review_marker_and_responds_on_attempt_1(
    fake_time, read_github_output, tmp_path, monkeypatch, fake_gh
):
    """attempt 1 で review_marker 付き投稿→初回試行内で応答検知する。"""
    calls = _script_metrics(
        monkeypatch, [_metrics(review_complete=True, terminal_count=1)]
    )
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = main(_wait_argv(out, summary))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "true"
    assert outputs["disconnected"] == "false"
    assert outputs["response_attempt"] == "1"
    assert outputs["attempts_used"] == "1"
    assert outputs["trigger_comment_ids"] == "1000"
    assert outputs["first_trigger_created_at"] == BASELINE
    assert len(fake_gh.posted_comments) == 1
    assert review_marker(HEAD_SHA) in fake_gh.posted_comments[0][1]
    assert "@codex review" in fake_gh.posted_comments[0][1]
    assert calls[0]["since"] == BASELINE
    assert fake_time.sleeps == []
    assert "- responded: true" in summary.read_text(encoding="utf-8")


def test_cmd_wait_for_review_pat_posts_from_attempt_1(
    fake_gh, fake_time, read_github_output, tmp_path, monkeypatch, capsys
):
    """PAT ありなら attempt 1 から人間名義で投稿し、応答が遅ければ retry も投稿する。"""
    calls = _script_metrics(
        monkeypatch,
        [
            _metrics(),
            _metrics(),
            _metrics(review_complete=True, terminal_count=1),
        ],
    )
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    ensure_calls: list[dict] = []
    real_ensure = auto_review_merge.ensure_review_comment

    def tracking_ensure(**kwargs):
        ensure_calls.append(kwargs)
        return real_ensure(**kwargs)

    monkeypatch.setattr(auto_review_merge, "ensure_review_comment", tracking_ensure)

    rc = main(_wait_argv(out, summary, max_attempts="3"))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "true"
    assert outputs["response_attempt"] == "2"
    assert outputs["attempts_used"] == "2"
    assert outputs["trigger_comment_ids"] == "1000,1001"
    assert len(fake_gh.posted_comments) == 2
    assert review_marker(HEAD_SHA) in fake_gh.posted_comments[0][1]
    assert retry_marker(2, HEAD_SHA) in fake_gh.posted_comments[1][1]
    assert len(ensure_calls) == 2
    assert PAT_LOGIN in ensure_calls[0]["allowed_logins"]
    assert "(PAT)" in capsys.readouterr().out
    assert len(calls) == 3


def test_cmd_wait_for_review_without_pat_posts_bot_comment_from_attempt_1(
    fake_gh, fake_time, read_github_output, tmp_path, monkeypatch, capsys
):
    """PAT 不在でも attempt 1 から bot 名義で @codex review を投稿する。"""
    calls = _script_metrics(
        monkeypatch,
        [
            _metrics(),
            _metrics(),
            _metrics(review_complete=True, terminal_count=1),
        ],
    )
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    ensure_calls: list[dict] = []
    real_ensure = auto_review_merge.ensure_review_comment

    def tracking_ensure(**kwargs):
        ensure_calls.append(kwargs)
        return real_ensure(**kwargs)

    monkeypatch.setattr(auto_review_merge, "ensure_review_comment", tracking_ensure)

    rc = main(
        _wait_argv(out, summary, max_attempts="3", pat_available="false", pat_login="")
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "true"
    assert outputs["response_attempt"] == "2"
    assert outputs["trigger_comment_ids"] == "1000,1001"
    assert len(fake_gh.posted_comments) == 2
    assert review_marker(HEAD_SHA) in fake_gh.posted_comments[0][1]
    assert retry_marker(2, HEAD_SHA) in fake_gh.posted_comments[1][1]
    assert "@codex review" in fake_gh.posted_comments[0][1]
    assert len(ensure_calls) == 2
    assert "allowed_logins" not in ensure_calls[0]
    assert "use_trigger_token" not in ensure_calls[0]
    assert "(bot)" in capsys.readouterr().out
    assert len(calls) == 3


def test_cmd_wait_for_review_empty_pat_login_posts_bot_comment(
    fake_gh, fake_time, read_github_output, tmp_path, monkeypatch
):
    """pat_available=true でも pat_login 空なら bot 名義で投稿する。"""
    _script_metrics(monkeypatch, [_metrics()])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = main(
        _wait_argv(out, summary, max_attempts="2", pat_available="true", pat_login="")
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "false"
    assert outputs["trigger_comment_ids"] == "1000,1001"
    assert len(fake_gh.posted_comments) == 2
    assert review_marker(HEAD_SHA) in fake_gh.posted_comments[0][1]
    assert retry_marker(2, HEAD_SHA) in fake_gh.posted_comments[1][1]


def test_cmd_wait_for_review_disconnect_aborts_early(
    fake_time, read_github_output, tmp_path, monkeypatch, fake_gh
):
    calls = _script_metrics(
        monkeypatch,
        [_metrics(disconnect_count=1, stop_reason="disconnected")],
    )
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = main(_wait_argv(out, summary, max_attempts="3"))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "false"
    assert outputs["disconnected"] == "true"
    assert outputs["attempts_used"] == "1"
    assert outputs["trigger_comment_ids"] == "1000"
    assert len(fake_gh.posted_comments) == 1
    assert review_marker(HEAD_SHA) in fake_gh.posted_comments[0][1]
    assert len(calls) == 1  # 全 attempt を消費しない


def test_cmd_wait_for_review_times_out_all_attempts(
    fake_gh, fake_time, read_github_output, tmp_path, monkeypatch
):
    calls = _script_metrics(monkeypatch, [_metrics()])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = main(_wait_argv(out, summary, max_attempts="2"))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "false"
    assert outputs["disconnected"] == "false"
    assert outputs["attempts_used"] == "2"
    assert outputs["response_attempt"] == ""
    assert outputs["trigger_comment_ids"] == "1000,1001"
    assert review_marker(HEAD_SHA) in fake_gh.posted_comments[0][1]
    assert retry_marker(2, HEAD_SHA) in fake_gh.posted_comments[1][1]
    assert len(calls) == 4
    assert "- responded: false" in summary.read_text(encoding="utf-8")


def test_cmd_wait_for_review_settle_sleep(
    fake_gh, fake_time, read_github_output, tmp_path, monkeypatch
):
    _script_metrics(monkeypatch, [_metrics(review_complete=True, terminal_count=1)])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = main(_wait_argv(out, summary, settle="45"))

    assert rc == 0
    assert fake_time.sleeps == [45]
    outputs = read_github_output(out)
    assert outputs["settle_seconds"] == "45"
    assert outputs["trigger_comment_ids"] == "1000"


def _check_gate_argv(out, *, trigger_comment_ids="10"):
    return [
        "check-gate",
        "--repo",
        "owner/repo",
        "--pr-number",
        "97",
        "--head-sha",
        HEAD_SHA,
        "--trigger-comment-ids",
        trigger_comment_ids,
        "--first-trigger-created-at",
        BASELINE,
        "--github-output",
        str(out),
    ]


def test_cmd_check_gate_merge_ok(fake_gh, read_github_output, tmp_path):
    fake_gh.responses["/pulls/97/reviews"] = [_codex_review()]
    out = tmp_path / "out.txt"

    rc = main(_check_gate_argv(out, trigger_comment_ids="10, ,11"))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["merge_ok"] == "true"
    assert outputs["stop_reason"] == "none"
    assert outputs["review_complete"] == "true"
    assert outputs["findings"] == "0"


def test_cmd_check_gate_findings_stop(fake_gh, read_github_output, tmp_path):
    fake_gh.responses["/pulls/97/comments"] = [_codex_finding()]
    out = tmp_path / "out.txt"

    rc = main(_check_gate_argv(out))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["merge_ok"] == "false"
    assert outputs["stop_reason"] == "findings"
    assert outputs["findings"] == "1"


def test_cmd_check_gate_resolved_findings_do_not_block(
    fake_gh, read_github_output, tmp_path
):
    finding = _codex_finding()
    finding["id"] = 3820325517
    fake_gh.responses["/pulls/97/reviews"] = [_codex_review()]
    fake_gh.responses["/pulls/97/comments"] = [finding]
    fake_gh.resolved_comment_ids = {"3820325517"}
    out = tmp_path / "out.txt"

    rc = main(_check_gate_argv(out))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["merge_ok"] == "true"
    assert outputs["stop_reason"] == "none"
    assert outputs["findings"] == "0"


def _record_stop_argv(summary, *, stop_reason, findings="0"):
    return [
        "record-stop",
        "--repo",
        "owner/repo",
        "--pr-number",
        "97",
        "--head-sha",
        HEAD_SHA,
        "--findings",
        findings,
        "--stop-reason",
        stop_reason,
        "--run-id",
        "111",
        "--attempts-used",
        "3",
        "--max-attempts",
        "3",
        "--attempt-timeout-seconds",
        "420",
        "--step-summary",
        str(summary),
    ]


def test_cmd_record_stop_no_response_posts_comment(fake_gh, tmp_path):
    summary = tmp_path / "summary.md"

    rc = main(_record_stop_argv(summary, stop_reason="no_response"))

    assert rc == 0
    assert len(fake_gh.posted_comments) == 1
    body = fake_gh.posted_comments[0][1]
    assert "reason:codex_no_response" in body
    assert "3/3 回試行" in body
    text = summary.read_text(encoding="utf-8")
    assert "- reason: codex_no_response" in text
    assert "- findings:" not in text  # no_response では findings 行を出さない
    assert "- comment_posted: true" in text


def test_cmd_record_stop_disconnected_message(fake_gh, tmp_path):
    summary = tmp_path / "summary.md"

    rc = main(_record_stop_argv(summary, stop_reason="disconnected"))

    assert rc == 0
    body = fake_gh.posted_comments[0][1]
    assert "reason:codex_disconnected" in body
    assert "chatgpt.com/codex/cloud/settings/connectors" in body
    assert "翌朝 09:00 JST" in body
    assert "@codex review" in body
    text = summary.read_text(encoding="utf-8")
    assert "- reason: codex_disconnected" in text


def test_cmd_record_stop_findings_idempotent(fake_gh, tmp_path):
    marker = auto_review_merge.stop_marker("codex_findings", "111", HEAD_SHA)
    fake_gh.responses["/issues/97/comments"] = [
        {
            "id": 42,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "github-actions[bot]"},
            "body": f"stop\n\n{marker}",
        }
    ]
    summary = tmp_path / "summary.md"

    rc = main(_record_stop_argv(summary, stop_reason="findings", findings="5"))

    assert rc == 0
    assert fake_gh.posted_comments == []  # 既存の停止コメントがあるため再投稿しない
    text = summary.read_text(encoding="utf-8")
    assert "- reason: codex_findings" in text
    assert "- findings: 5" in text
    assert "- comment_posted: false" in text


def test_cmd_export_findings_writes_json_and_path_only_outputs(
    fake_gh, read_github_output, tmp_path, capsys
):
    fake_gh.responses["/pulls/97/comments"] = [
        _codex_finding(),
        {
            "user": {"login": CODEX_BOT},
            "commit_id": "other",
            "path": "skip.py",
            "line": 1,
            "body": "old commit",
        },
        {
            "user": {"login": "someone"},
            "commit_id": HEAD_SHA,
            "path": "other.py",
            "line": 2,
            "body": "not codex",
        },
    ]
    findings_path = tmp_path / "findings.json"
    out = tmp_path / "out.txt"

    rc = main(
        [
            "export-findings",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--head-sha",
            HEAD_SHA,
            "--out",
            str(findings_path),
            "--github-output",
            str(out),
        ]
    )

    assert rc == 0
    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    assert payload == [
        {"path": "msData.json", "line": 12, "body": "ここにバグがあります"}
    ]
    outputs = read_github_output(out)
    assert outputs["findings_path"] == str(findings_path)
    assert outputs["findings_count"] == "1"
    assert set(outputs) == {"findings_path", "findings_count"}
    # body を stdout / Outputs に出さない
    stdout = capsys.readouterr().out
    assert "ここにバグがあります" not in stdout
    assert "ここにバグがあります" not in out.read_text(encoding="utf-8")


def test_cmd_write_report_writes_json_and_summary(tmp_path):
    out = tmp_path / "reports" / "auto_review_20260531.json"
    summary = tmp_path / "summary.md"

    rc = main(
        [
            "write-report",
            "--report-date",
            "20260531",
            "--run-id",
            "111",
            "--pr-number",
            "97",
            "--head-ref",
            "data/auto-update-20260531",
            "--head-sha",
            HEAD_SHA,
            "--responded",
            "true",
            "--attempts-used",
            "1",
            "--max-attempts",
            "3",
            "--merge-ok",
            "true",
            "--merged",
            "true",
            "--merge-outcome",
            "success",
            "--trigger-comment-ids",
            "",
            "--first-trigger-created-at",
            BASELINE,
            "--out",
            str(out),
            "--step-summary",
            str(summary),
        ]
    )

    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "merged"
    assert report["stop_reason"] == "none"
    assert report["review"]["trigger_comment_ids"] == []
    assert report["review"]["first_trigger_created_at"] == BASELINE
    text = summary.read_text(encoding="utf-8")
    assert "- status: merged" in text
    assert f"- report: {out}" in text


def test_cmd_resume_honors_facade_merge_and_notify_monkeypatch(
    fake_gh, read_github_output, tmp_path, monkeypatch
):
    """分割後も facade 上の _merge_and_notify monkeypatch が効くこと。"""
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

    merge_calls: list[dict] = []

    def fake_merge(**kwargs):
        merge_calls.append(kwargs)
        return "merge-sha-patched"

    monkeypatch.setattr(auto_review_merge, "_merge_and_notify", fake_merge)
    _script_metrics(monkeypatch, [_metrics(merge_ok=True, review_complete=True)])

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
        ]
    )

    assert rc == 0
    assert len(merge_calls) == 1
    assert merge_calls[0]["pr_number"] == "97"
    assert merge_calls[0]["evaluated_sha"] == HEAD_SHA
    outputs = read_github_output(out)
    assert outputs["merged_count"] == "1"
    assert "- merged: #97 (merge-sha-patched)" in summary.read_text(encoding="utf-8")


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
    fake_gh.responses["/pulls/97/comments"] = [_codex_finding()]

    notify_calls: list[dict] = []

    def fake_notify(**kwargs):
        notify_calls.append(kwargs)
        return 0

    monkeypatch.setattr(auto_review_merge, "notify_review_stop", fake_notify)
    ensure_calls: list[dict] = []

    def fake_ensure(**kwargs):
        ensure_calls.append(kwargs)
        raise AssertionError("findings 停止時に retry 投稿してはならない")

    monkeypatch.setattr(auto_review_merge, "ensure_review_comment", fake_ensure)
    _script_metrics(
        monkeypatch,
        [
            _metrics(
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

    rc = main(
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
        ]
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
    fake_gh.responses["/pulls/97/comments"] = [_codex_finding()]

    notify_calls: list[dict] = []

    def fake_notify(**kwargs):
        notify_calls.append(kwargs)
        return 0

    monkeypatch.setattr(auto_review_merge, "notify_review_stop", fake_notify)
    calls = _script_metrics(
        monkeypatch,
        [
            _metrics(
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

    rc = main(
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
        ]
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
