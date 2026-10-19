import json

import pytest

from ms_data.gh import post_merge_assets
from ms_data.gh.post_merge_assets import resolve_assets


def test_resolve_assets_uses_checkout_reports_and_downloaded_snapshot(tmp_path):
    reports = tmp_path / "reports" / "2026" / "05"
    reports.mkdir(parents=True)
    (reports / "diff_msdata_20260531.md").write_text("diff", encoding="utf-8")
    (reports / "provenance_20260531.json").write_text("{}", encoding="utf-8")
    (reports / "atwiki_quality_20260531.json").write_text("{}", encoding="utf-8")

    assets = resolve_assets(
        head_ref="data/auto-update-20260531",
        source_run_id_input="26709410162",
        pr_body="",
        root=tmp_path,
        require_files=True,
    )

    assert assets.report_path == "reports/2026/05/diff_msdata_20260531.md"
    assert assets.provenance_path == "reports/2026/05/provenance_20260531.json"
    assert assets.atwiki_quality_path == "reports/2026/05/atwiki_quality_20260531.json"
    assert assets.report_asset_path == assets.report_path
    assert assets.provenance_asset_path == assets.provenance_path
    assert assets.atwiki_quality_asset_path == assets.atwiki_quality_path
    assert (
        assets.snapshot_asset_path
        == "release_assets/raw_snapshot_20260531_run26709410162.tar.xz"
    )


def test_resolve_assets_rejects_missing_checkout_report(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_assets(
            head_ref="data/auto-update-20260531",
            source_run_id_input="26709410162",
            pr_body="",
            root=tmp_path,
            require_files=True,
        )


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
