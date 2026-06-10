"""auto_review_merge の GitHubClient / cmd_* サブコマンドのテスト。

GitHubClient 自体は subprocess.run のパッチで、cmd_* は conftest の
FakeGitHubClient / FakeTime 注入で検証する（実 gh CLI は一切呼ばない）。
"""

import json
from types import SimpleNamespace

from ms_data.gh import auto_review_merge
from ms_data.gh.auto_review_merge import (
    GitHubClient,
    collect_review_metrics,
    ensure_review_comment,
    main,
    retry_marker,
    review_marker,
)

CODEX_BOT = "chatgpt-codex-connector[bot]"
HEAD_SHA = "abc123"


def _codex_review(commit_id: str = HEAD_SHA) -> dict:
    return {"user": {"login": CODEX_BOT}, "commit_id": commit_id}


def _codex_finding(commit_id: str = HEAD_SHA) -> dict:
    return {
        "user": {"login": CODEX_BOT},
        "commit_id": commit_id,
        "body": "ここにバグがあります",
    }


def _metrics(**overrides) -> dict:
    base = {
        "review_count": 0,
        "finding_count": 0,
        "reaction_count": 0,
        "issue_comment_count": 0,
        "no_issue_comment_count": 0,
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
# 層A: GitHubClient（subprocess.run パッチ）
# ---------------------------------------------------------------------------


def test_api_json_builds_get_command(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='[{"id": 1}]')

    monkeypatch.setattr(auto_review_merge.subprocess, "run", fake_run)
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

    monkeypatch.setattr(auto_review_merge.subprocess, "run", fake_run)
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

    monkeypatch.setattr(auto_review_merge.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")

    assert client.issue_comments("97") == [{"id": 1}, {"id": 2}]


def test_issue_comment_fetches_detail(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='{"id": 42}')

    monkeypatch.setattr(auto_review_merge.subprocess, "run", fake_run)
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


def test_cmd_resolve_target_pr_skip_path(
    fake_gh, read_github_output, tmp_path, capsys
):
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


def test_cmd_trigger_review_outputs_comment_id(fake_gh, read_github_output, tmp_path):
    out = tmp_path / "out.txt"

    rc = main(
        [
            "trigger-review",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--head-sha",
            HEAD_SHA,
            "--github-output",
            str(out),
        ]
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["trigger_comment_id"] == "1000"
    assert outputs["trigger_created_at"] == "2026-05-31T10:00:00Z"
    assert outputs["created_new"] == "true"


def _wait_argv(out, summary, *, max_attempts="2", settle="0"):
    return [
        "wait-for-review",
        "--repo",
        "owner/repo",
        "--pr-number",
        "97",
        "--head-sha",
        HEAD_SHA,
        "--trigger-comment-id",
        "10",
        "--trigger-comment-created-at",
        "2026-05-31T10:00:00Z",
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


def test_cmd_wait_for_review_responds_first_poll(
    fake_gh, fake_time, read_github_output, tmp_path, monkeypatch
):
    _script_metrics(monkeypatch, [_metrics(review_complete=True, terminal_count=1)])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = main(_wait_argv(out, summary))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "true"
    assert outputs["response_attempt"] == "1"
    assert outputs["attempts_used"] == "1"
    assert outputs["trigger_comment_ids"] == "10"
    assert fake_time.sleeps == []  # settle=0 かつ即応答なので sleep しない
    assert "- responded: true" in summary.read_text(encoding="utf-8")


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
    assert outputs["attempts_used"] == "2"
    assert outputs["response_attempt"] == ""
    # attempt 2 で retry_marker 付きのトリガーが新規投稿され ids に蓄積される
    assert outputs["trigger_comment_ids"] == "10,1000"
    assert retry_marker(2, HEAD_SHA) in fake_gh.posted_comments[0][1]
    # 2 attempts x 2 ポーリング
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


def test_cmd_wait_for_review_recovers_on_second_attempt(
    fake_gh, fake_time, read_github_output, tmp_path, monkeypatch
):
    # attempt 1 は2回ポーリングして未応答、attempt 2 の初回ポーリングで応答
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

    rc = main(_wait_argv(out, summary, max_attempts="3"))

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "true"
    assert outputs["response_attempt"] == "2"
    assert outputs["attempts_used"] == "2"
    assert outputs["trigger_comment_ids"] == "10,1000"
    assert len(calls) == 3


def test_cmd_check_gate_merge_ok(fake_gh, read_github_output, tmp_path):
    fake_gh.responses["/pulls/97/reviews"] = [_codex_review()]
    out = tmp_path / "out.txt"

    rc = main(
        [
            "check-gate",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--head-sha",
            HEAD_SHA,
            "--trigger-comment-ids",
            "10, ,11",
            "--first-trigger-created-at",
            "2026-05-31T10:00:00Z",
            "--github-output",
            str(out),
        ]
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["merge_ok"] == "true"
    assert outputs["stop_reason"] == "none"
    assert outputs["review_complete"] == "true"
    assert outputs["findings"] == "0"


def test_cmd_check_gate_findings_stop(fake_gh, read_github_output, tmp_path):
    fake_gh.responses["/pulls/97/comments"] = [_codex_finding()]
    out = tmp_path / "out.txt"

    rc = main(
        [
            "check-gate",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--head-sha",
            HEAD_SHA,
            "--trigger-comment-ids",
            "10",
            "--first-trigger-created-at",
            "2026-05-31T10:00:00Z",
            "--github-output",
            str(out),
        ]
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["merge_ok"] == "false"
    assert outputs["stop_reason"] == "findings"
    assert outputs["findings"] == "1"


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
            "10",
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
    assert report["review"]["trigger_comment_ids"] == ["10"]
    text = summary.read_text(encoding="utf-8")
    assert "- status: merged" in text
    assert f"- report: {out}" in text
