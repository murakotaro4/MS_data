"""check-gate / record-stop / export-findings / write-report サブコマンドのテスト。"""

import json

from ms_data.gh import auto_review_merge

from auto_review_helpers import (
    BASELINE,
    CODEX_BOT,
    HEAD_SHA,
    codex_finding,
    codex_review,
    run_main,
)


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
    fake_gh.responses["/pulls/97/reviews"] = [codex_review()]
    out = tmp_path / "out.txt"

    rc = run_main(_check_gate_argv(out, trigger_comment_ids="10, ,11"), fake_gh)

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["merge_ok"] == "true"
    assert outputs["stop_reason"] == "none"
    assert outputs["review_complete"] == "true"
    assert outputs["findings"] == "0"


def test_cmd_check_gate_findings_stop(fake_gh, read_github_output, tmp_path):
    fake_gh.responses["/pulls/97/comments"] = [codex_finding()]
    out = tmp_path / "out.txt"

    rc = run_main(_check_gate_argv(out), fake_gh)

    assert rc == 0
    outputs = read_github_output(out)
    assert outputs["merge_ok"] == "false"
    assert outputs["stop_reason"] == "findings"
    assert outputs["findings"] == "1"


def test_cmd_check_gate_resolved_findings_do_not_block(
    fake_gh, read_github_output, tmp_path
):
    finding = codex_finding()
    finding["id"] = 3820325517
    fake_gh.responses["/pulls/97/reviews"] = [codex_review()]
    fake_gh.responses["/pulls/97/comments"] = [finding]
    fake_gh.resolved_comment_ids = {"3820325517"}
    out = tmp_path / "out.txt"

    rc = run_main(_check_gate_argv(out), fake_gh)

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

    rc = run_main(_record_stop_argv(summary, stop_reason="no_response"), fake_gh)

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

    rc = run_main(_record_stop_argv(summary, stop_reason="disconnected"), fake_gh)

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

    rc = run_main(
        _record_stop_argv(summary, stop_reason="findings", findings="5"), fake_gh
    )

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
        codex_finding(),
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

    rc = run_main(
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
        ],
        fake_gh,
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

    rc = run_main(
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
