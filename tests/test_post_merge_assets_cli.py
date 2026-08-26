import json

import pytest

from ms_data.gh import post_merge_assets


def test_resolve_source_run_id_raises_when_both_sources_are_empty():
    with pytest.raises(ValueError, match="source_run_id"):
        post_merge_assets.resolve_source_run_id("", "marker なし")


def test_main_reads_pr_body_from_environment(monkeypatch, capsys):
    monkeypatch.setenv("TEST_PR_BODY", "<!-- source_run_id:26709410162 -->")

    assert (
        post_merge_assets.main(
            [
                "--head-ref",
                "data/auto-update-20260531",
                "--pr-body-env",
                "TEST_PR_BODY",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["report_date"] == "20260531"
    assert payload["source_run_id"] == "26709410162"
    assert payload["snapshot_file"] == ("raw_snapshot_20260531_run26709410162.tar.xz")
