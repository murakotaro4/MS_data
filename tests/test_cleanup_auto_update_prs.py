import json

import pytest

from ms_data.gh import cleanup_auto_update_prs
from ms_data.gh.cleanup_auto_update_prs import (
    parse_report_date,
    plan_cleanup,
    render_summary,
)


def _pull(number, head_ref):
    return {"number": number, "head": {"ref": head_ref}}


def test_parse_report_date():
    assert parse_report_date("data/auto-update-20260531") == "20260531"
    assert parse_report_date("feature/test") is None


def test_plan_cleanup_closes_only_stale_auto_update_prs():
    actions = plan_cleanup(
        [
            _pull(1, "data/auto-update-20260531"),
            _pull(2, "data/auto-update-20260530"),
            _pull(3, "data/auto-update-20260527"),
            _pull(4, "feature/test"),
        ],
        today="20260531",
        keep_days=2,
    )

    by_number = {item.number: item for item in actions}
    assert by_number[1].action == "keep"
    assert by_number[1].reason == "today"
    assert by_number[2].action == "keep"
    assert by_number[3].action == "close"
    assert by_number[3].reason == "stale_open_pr:4d"
    assert 4 not in by_number


def test_render_summary_includes_dry_run_counts():
    actions = plan_cleanup(
        [_pull(3, "data/auto-update-20260527")],
        today="20260531",
        keep_days=2,
    )

    text = render_summary(actions, dry_run=True)

    assert "- dry_run: true" in text
    assert "- close: 1" in text
    assert "| #3 | data/auto-update-20260527 |" in text


def test_gh_json_rejects_concatenated_documents(monkeypatch):
    monkeypatch.setattr(
        cleanup_auto_update_prs,
        "_run",
        lambda cmd: '[{"id": 1}]\n[{"id": 2}]',
    )

    with pytest.raises(json.JSONDecodeError, match="Extra data"):
        cleanup_auto_update_prs._gh_json("repos/owner/repo/pulls")
