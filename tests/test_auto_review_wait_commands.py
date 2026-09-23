"""wait-for-review サブコマンドのテスト（PAT 有無・タイムアウト・settle）。"""

from ms_data.gh import auto_review_merge
from ms_data.gh.auto_review_merge import (
    retry_marker,
    review_marker,
)

from auto_review_helpers import (
    BASELINE,
    HEAD_SHA,
    PAT_LOGIN,
    metrics,
    run_main,
    script_metrics,
)


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
    fake_time, read_github_output, tmp_path, fake_gh
):
    """attempt 1 で review_marker 付き投稿→初回試行内で応答検知する。"""
    calls, collect = script_metrics([metrics(review_complete=True, terminal_count=1)])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = run_main(_wait_argv(out, summary), fake_gh, fake_time, collect_metrics=collect)

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
    fake_gh, fake_time, read_github_output, tmp_path, capsys
):
    """PAT ありなら attempt 1 から人間名義で投稿し、応答が遅ければ retry も投稿する。"""
    calls, collect = script_metrics(
        [
            metrics(),
            metrics(),
            metrics(review_complete=True, terminal_count=1),
        ],
    )
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    ensure_calls: list[dict] = []
    real_ensure = auto_review_merge.ensure_review_comment

    def tracking_ensure(**kwargs):
        ensure_calls.append(kwargs)
        return real_ensure(**kwargs)

    rc = run_main(
        _wait_argv(out, summary, max_attempts="3"),
        fake_gh,
        fake_time,
        collect_metrics=collect,
        ensure_comment=tracking_ensure,
    )

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
    fake_gh, fake_time, read_github_output, tmp_path, capsys
):
    """PAT 不在でも attempt 1 から bot 名義で @codex review を投稿する。"""
    calls, collect = script_metrics(
        [
            metrics(),
            metrics(),
            metrics(review_complete=True, terminal_count=1),
        ],
    )
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    ensure_calls: list[dict] = []
    real_ensure = auto_review_merge.ensure_review_comment

    def tracking_ensure(**kwargs):
        ensure_calls.append(kwargs)
        return real_ensure(**kwargs)

    rc = run_main(
        _wait_argv(out, summary, max_attempts="3", pat_available="false", pat_login=""),
        fake_gh,
        fake_time,
        collect_metrics=collect,
        ensure_comment=tracking_ensure,
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
    fake_gh, fake_time, read_github_output, tmp_path
):
    """pat_available=true でも pat_login 空なら bot 名義で投稿する。"""
    _, collect = script_metrics([metrics()])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = run_main(
        _wait_argv(out, summary, max_attempts="2", pat_available="true", pat_login=""),
        fake_gh,
        fake_time,
        collect_metrics=collect,
    )

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["responded"] == "false"
    assert outputs["trigger_comment_ids"] == "1000,1001"
    assert len(fake_gh.posted_comments) == 2
    assert review_marker(HEAD_SHA) in fake_gh.posted_comments[0][1]
    assert retry_marker(2, HEAD_SHA) in fake_gh.posted_comments[1][1]


def test_cmd_wait_for_review_disconnect_aborts_early(
    fake_time, read_github_output, tmp_path, fake_gh
):
    calls, collect = script_metrics(
        [metrics(disconnect_count=1, stop_reason="disconnected")]
    )
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = run_main(
        _wait_argv(out, summary, max_attempts="3"),
        fake_gh,
        fake_time,
        collect_metrics=collect,
    )

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
    fake_gh, fake_time, read_github_output, tmp_path
):
    calls, collect = script_metrics([metrics()])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = run_main(
        _wait_argv(out, summary, max_attempts="2"),
        fake_gh,
        fake_time,
        collect_metrics=collect,
    )

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
    fake_gh, fake_time, read_github_output, tmp_path
):
    _, collect = script_metrics([metrics(review_complete=True, terminal_count=1)])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = run_main(
        _wait_argv(out, summary, settle="45"),
        fake_gh,
        fake_time,
        collect_metrics=collect,
    )

    assert rc == 0
    assert fake_time.sleeps == [45]
    outputs = read_github_output(out)
    assert outputs["settle_seconds"] == "45"
    assert outputs["trigger_comment_ids"] == "1000"


def test_cmd_wait_for_review_invalid_settle_uses_default(
    fake_gh, fake_time, read_github_output, tmp_path
):
    _, collect = script_metrics([metrics(review_complete=True, terminal_count=1)])
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = run_main(
        _wait_argv(out, summary, settle="invalid"),
        fake_gh,
        fake_time,
        collect_metrics=collect,
    )

    assert rc == 0
    assert fake_time.sleeps == [60]
    assert read_github_output(out)["settle_seconds"] == "60"
