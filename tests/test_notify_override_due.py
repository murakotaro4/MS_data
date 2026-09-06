import json
from pathlib import Path

import pytest

from ms_data.gh import notify_override_due as due
from ms_data.gh.gh_json import gh_api_json
from ms_data.gh.notify_override_due import (
    DueCounts,
    build_due_body,
    ensure_override_due_issue,
    latest_notified_counts,
    parse_due_counts,
    should_comment,
)

REPO = "owner/repo"
ISSUES_ENDPOINT = f"repos/{REPO}/issues?state=open&labels=override-due&per_page=100"
RUN_URL = "https://github.com/owner/repo/actions/runs/123"


def _body(report_date: str = "20260901", review: int = 46, remove: int = 0) -> str:
    return build_due_body(
        report_date=report_date,
        counts=DueCounts(review_due=review, remove_due=remove),
        audit_report="reports/2026/09/official_overrides_audit_20260901.md",
        run_url=RUN_URL,
    )


def test_build_due_body_contains_bullets_and_marker():
    body = _body()

    assert "- report_date: 20260901" in body
    assert "- review_due: 46" in body
    assert "- remove_due: 0" in body
    assert f"- workflow_run: {RUN_URL}" in body
    assert body.rstrip().endswith(
        "<!-- override-due report_date=20260901 review_due=46 remove_due=0 -->"
    )


def test_parse_due_counts_prefers_marker_over_bullets():
    text = "- review_due: 1\n- remove_due: 2\n<!-- override-due report_date=20260901 review_due=46 remove_due=0 -->"

    assert parse_due_counts(text) == DueCounts(review_due=46, remove_due=0)


def test_parse_due_counts_reads_legacy_bullets_without_marker():
    legacy = (
        "official_overrides の期限確認が必要です。\n\n"
        "- report_date: 20260824\n- review_due: 46\n- remove_due: 0\n"
        "- audit_report: reports/2026/08/official_overrides_audit_20260824.md\n"
    )

    assert parse_due_counts(legacy) == DueCounts(review_due=46, remove_due=0)


@pytest.mark.parametrize("text", ["", "no counts here", "- review_due: 3"])
def test_parse_due_counts_returns_none_when_incomplete(text):
    assert parse_due_counts(text) is None


def test_latest_notified_counts_uses_last_parsable_comment_then_body():
    issue = {"body": _body(review=10, remove=0)}
    comments = [
        {"body": _body(review=20, remove=0)},
        {"body": "unrelated human comment"},
    ]

    assert latest_notified_counts(issue, comments) == DueCounts(20, 0)
    assert latest_notified_counts(issue, []) == DueCounts(10, 0)
    assert latest_notified_counts({"body": ""}, []) is None


def test_should_comment_only_when_counts_change():
    current = DueCounts(46, 0)

    assert should_comment(None, current) is True
    assert should_comment(DueCounts(46, 0), current) is False
    assert should_comment(DueCounts(46, 1), current) is True


def _runner(open_issues, comments=None, created_number=8):
    calls = []

    def runner(cmd):
        calls.append(cmd)
        if cmd[:3] == ["gh", "label", "create"]:
            return ""
        endpoint = cmd[2] if len(cmd) > 2 else ""
        if endpoint == ISSUES_ENDPOINT:
            return json.dumps(open_issues)
        if endpoint.endswith("/comments?per_page=100"):
            return json.dumps(comments or [])
        if endpoint.endswith("/comments") and "-X" in cmd:
            return json.dumps({"id": 99})
        if endpoint == f"repos/{REPO}/issues" and "-X" in cmd:
            return json.dumps({"number": created_number})
        if "PATCH" in cmd:
            return json.dumps({"state": "closed"})
        raise AssertionError(f"unexpected command: {cmd}")

    return runner, calls


def _ensure(runner, review=46, remove=0):
    return ensure_override_due_issue(
        repo=REPO,
        report_date="20260901",
        counts=DueCounts(review_due=review, remove_due=remove),
        audit_report="reports/2026/09/official_overrides_audit_20260901.md",
        run_url=RUN_URL,
        runner=runner,
    )


def _existing_issue(number=218, body=""):
    return {
        "number": number,
        "state": "open",
        "title": "official_overrides 期限確認",
        "labels": [{"name": "override-due"}, {"name": "official-overrides"}],
        "body": body,
    }


def test_creates_issue_with_both_labels_when_absent():
    runner, calls = _runner([])

    assert _ensure(runner) == ("created", 8)

    label_calls = [cmd for cmd in calls if cmd[:3] == ["gh", "label", "create"]]
    assert [cmd[3] for cmd in label_calls] == ["override-due", "official-overrides"]
    create = next(cmd for cmd in calls if cmd[2] == f"repos/{REPO}/issues")
    assert "-f" in create
    fields = [create[i + 1] for i, tok in enumerate(create) if tok == "-f"]
    assert "title=official_overrides 期限確認" in fields
    assert "labels[]=override-due" in fields
    assert "labels[]=official-overrides" in fields
    assert any(
        field.startswith("body=") and "review_due=46" in field for field in fields
    )


def test_skips_comment_when_latest_counts_unchanged():
    legacy_comment = {
        "body": "- report_date: 20260824\n- review_due: 46\n- remove_due: 0\n"
    }
    runner, calls = _runner([_existing_issue()], comments=[legacy_comment])

    assert _ensure(runner) == ("skipped", 218)
    assert not any(
        cmd[:4] == ["gh", "api", f"repos/{REPO}/issues/218/comments", "-X"]
        for cmd in calls
    )


def test_comments_when_counts_changed():
    runner, calls = _runner(
        [_existing_issue(body=_body(review=46, remove=0))], comments=[]
    )

    assert _ensure(runner, review=46, remove=3) == ("commented", 218)
    comment = next(
        cmd
        for cmd in calls
        if cmd[:4] == ["gh", "api", f"repos/{REPO}/issues/218/comments", "-X"]
    )
    assert "remove_due=3" in comment[-1]


def test_comments_when_no_previous_counts_are_readable():
    runner, calls = _runner([_existing_issue(body="手書きの本文")], comments=[])

    assert _ensure(runner) == ("commented", 218)


def test_duplicate_issues_are_converged_to_lowest_number():
    runner, calls = _runner(
        [_existing_issue(number=230), _existing_issue(number=218)], comments=[]
    )

    assert _ensure(runner) == ("deduplicated", 218)
    close = next(cmd for cmd in calls if cmd[2] == f"repos/{REPO}/issues/230")
    assert "-X" in close and "PATCH" in close
    assert any(
        cmd[2] == f"repos/{REPO}/issues/218/comments" and "期限情報を集約" in cmd[-1]
        for cmd in calls
    )


def test_gh_api_json_repeats_sequence_fields():
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return "{}"

    gh_api_json(
        "repos/o/r/issues",
        method="POST",
        fields={"title": "t", "labels[]": ["a", "b"]},
        runner=runner,
    )

    assert calls[0] == [
        "gh",
        "api",
        "repos/o/r/issues",
        "-X",
        "POST",
        "-f",
        "title=t",
        "-f",
        "labels[]=a",
        "-f",
        "labels[]=b",
    ]


def test_main_skips_when_no_due(capsys, monkeypatch):
    monkeypatch.setattr(
        due, "ensure_override_due_issue", lambda **_: pytest.fail("must not call")
    )

    code = due.main(
        [
            "--repo",
            REPO,
            "--report-date",
            "20260901",
            "--review-due",
            "0",
            "--remove-due",
            "0",
            "--audit-report",
            "r.md",
            "--run-url",
            RUN_URL,
        ]
    )

    assert code == 0
    assert "スキップ" in capsys.readouterr().out


def test_main_writes_step_summary_and_reports_action(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(due, "ensure_override_due_issue", lambda **_: ("skipped", 218))
    summary = tmp_path / "summary.md"

    code = due.main(
        [
            "--repo",
            REPO,
            "--report-date",
            "20260901",
            "--review-due",
            "46",
            "--remove-due",
            "0",
            "--audit-report",
            "r.md",
            "--run-url",
            RUN_URL,
            "--step-summary",
            str(summary),
        ]
    )

    assert code == 0
    text = summary.read_text(encoding="utf-8")
    assert "- action: skipped" in text
    assert "- issue: #218" in text


def test_main_returns_one_when_notification_fails(monkeypatch, capsys):
    def _boom(**_):
        raise RuntimeError("gh down")

    monkeypatch.setattr(due, "ensure_override_due_issue", _boom)

    code = due.main(
        [
            "--repo",
            REPO,
            "--report-date",
            "20260901",
            "--review-due",
            "1",
            "--remove-due",
            "0",
            "--audit-report",
            "r.md",
            "--run-url",
            RUN_URL,
        ]
    )

    assert code == 1
    assert "gh down" in capsys.readouterr().err


def test_main_rejects_negative_counts():
    with pytest.raises(SystemExit):
        due.parse_args(
            [
                "--repo",
                REPO,
                "--report-date",
                "20260901",
                "--review-due",
                "-1",
                "--remove-due",
                "0",
                "--audit-report",
                "r.md",
                "--run-url",
                RUN_URL,
            ]
        )


def _workflow_block(start_marker: str, end_marker: str) -> str:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/data_update.yml"
    ).read_text(encoding="utf-8")
    start = workflow.index(start_marker)
    end = workflow.index(end_marker, start)
    return workflow[start:end]


def test_data_update_uses_notify_module_without_inline_issue_commands():
    block = _workflow_block(
        "      - name: Notify official override due issue\n",
        "\n      - id: detection\n",
    )

    assert "uv run python -m ms_data.gh.notify_override_due" in block
    assert (
        '--review-due "${{ steps.official_overrides_audit.outputs.review_due }}"'
        in block
    )
    assert (
        '--remove-due "${{ steps.official_overrides_audit.outputs.remove_due }}"'
        in block
    )
    assert '--audit-report "${OVERRIDES_AUDIT_FILE}"' in block
    assert '--step-summary "$GITHUB_STEP_SUMMARY"' in block
    assert "gh issue create" not in block
    assert "gh issue comment" not in block
    assert "gh label create" not in block


def test_data_update_ensures_pr_labels_via_repo_labels_module():
    block = _workflow_block(
        "      - name: Ensure pull request labels\n",
        "\n      - name: Create pull request\n",
    )

    assert "uv run python -m ms_data.gh.repo_labels" in block
    assert "data-update rollback-guard official-overrides atwiki-quality" in block
    assert "gh label create" not in block
