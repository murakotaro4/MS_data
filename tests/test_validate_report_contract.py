import json
from pathlib import Path

import pytest

from ms_data.validation import validate_report_contract


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _manifest() -> dict:
    return {
        "version": 1,
        "compatibility": {
            "legacy_path_support": True,
            "min_release_cycles": 1,
            "retirement_criteria": ["legacy consumer count is 0"],
        },
        "naming": {
            "report_date_format": "YYYYMMDD",
            "head_ref_pattern": "data/auto-update-{report_date}",
            "diff_pattern": "reports/diff_msdata_{report_date}.md",
            "provenance_pattern": "reports/provenance_{report_date}.json",
            "artifact_pattern": "raw-snapshot-{report_date}-run-{source_run_id}",
            "snapshot_pattern": "raw_snapshot_{report_date}_run{source_run_id}.tar.xz",
            "release_tag_pattern": "raw-snapshot-{report_date}-run-{source_run_id}",
            "idempotency_key": "source_run_id+head_ref",
        },
        "entries": [
            {
                "id": "diff",
                "type": "generated",
                "path_patterns": ["reports/diff_msdata_*.md"],
                "producer": ["ms_data.reporting.report_msdata_diff"],
                "consumers": ["workflow"],
                "retention": "git",
            },
            {
                "id": "manual",
                "type": "manual",
                "path_patterns": ["reports/README.md"],
                "producer": ["human"],
                "consumers": ["human"],
                "retention": "git",
            },
        ],
    }


def test_data_update_mode_ok(tmp_path: Path) -> None:
    manifest = tmp_path / "reports_manifest.json"
    _write_json(manifest, _manifest())

    rc = validate_report_contract.main(
        [
            "--mode",
            "data-update",
            "--manifest",
            str(manifest),
            "--report-date",
            "20260320",
            "--source-run-id",
            "12345",
            "--head-ref",
            "data/auto-update-20260320",
            "--diff-path",
            "reports/diff_msdata_20260320.md",
            "--provenance-path",
            "reports/provenance_20260320.json",
            "--artifact-name",
            "raw-snapshot-20260320-run-12345",
            "--snapshot-file",
            "raw_snapshot_20260320_run12345.tar.xz",
            "--release-tag",
            "raw-snapshot-20260320-run-12345",
        ]
    )
    assert rc == 0


def test_data_update_mode_release_tag_mismatch(tmp_path: Path) -> None:
    manifest = tmp_path / "reports_manifest.json"
    _write_json(manifest, _manifest())

    rc = validate_report_contract.main(
        [
            "--mode",
            "data-update",
            "--manifest",
            str(manifest),
            "--report-date",
            "20260320",
            "--source-run-id",
            "12345",
            "--head-ref",
            "data/auto-update-20260320",
            "--diff-path",
            "reports/diff_msdata_20260320.md",
            "--provenance-path",
            "reports/provenance_20260320.json",
            "--artifact-name",
            "raw-snapshot-20260320-run-12345",
            "--snapshot-file",
            "raw_snapshot_20260320_run12345.tar.xz",
            "--release-tag",
            "raw-snapshot-20260320-run12345",
        ]
    )
    assert rc == 1


def test_manifest_rejects_unknown_entry_type(tmp_path: Path) -> None:
    bad = {
        "version": 1,
        "compatibility": {
            "legacy_path_support": True,
            "min_release_cycles": 1,
            "retirement_criteria": ["x"],
        },
        "naming": {
            "report_date_format": "YYYYMMDD",
            "head_ref_pattern": "data/auto-update-{report_date}",
            "diff_pattern": "reports/diff_msdata_{report_date}.md",
            "provenance_pattern": "reports/provenance_{report_date}.json",
            "artifact_pattern": "raw-snapshot-{report_date}-run-{source_run_id}",
            "snapshot_pattern": "raw_snapshot_{report_date}_run{source_run_id}.tar.xz",
            "release_tag_pattern": "raw-snapshot-{report_date}-run-{source_run_id}",
            "idempotency_key": "source_run_id+head_ref",
        },
        "entries": [
            {
                "id": "arch",
                "type": "archive",
                "path_patterns": ["reports/archive/**"],
                "producer": ["human"],
                "consumers": ["human"],
                "retention": "git",
            },
        ],
    }
    manifest = tmp_path / "reports_manifest.json"
    _write_json(manifest, bad)

    rc = validate_report_contract.main(
        [
            "--mode",
            "ci",
            "--manifest",
            str(manifest),
            "--reports-dir",
            str(tmp_path / "reports"),
        ]
    )
    assert rc == 1


def test_ci_mode_rejects_unknown_report_file(tmp_path: Path) -> None:
    manifest = tmp_path / "reports_manifest.json"
    _write_json(manifest, _manifest())
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "diff_msdata_20260320.md").write_text("ok", encoding="utf-8")
    (reports_dir / "unknown_note.md").write_text("ng", encoding="utf-8")

    rc = validate_report_contract.main(
        [
            "--mode",
            "ci",
            "--manifest",
            str(manifest),
            "--reports-dir",
            str(reports_dir),
        ]
    )
    assert rc == 1


def test_custom_reports_dir_uses_manifest_logical_root(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest_data = _manifest()
    manifest_data["naming"]["reports_root"] = "logical_reports"
    manifest_data["naming"][
        "diff_pattern"
    ] = "logical_reports/diff_msdata_{report_date}.md"
    manifest_data["naming"][
        "provenance_pattern"
    ] = "logical_reports/provenance_{report_date}.json"
    manifest_data["entries"][0]["path_patterns"] = ["logical_reports/diff_msdata_*.md"]
    manifest = Path("reports_manifest.json")
    _write_json(manifest, manifest_data)
    reports_dir = Path("custom_dir")
    reports_dir.mkdir(parents=True)
    (reports_dir / "diff_msdata_20260320.md").write_text("ok", encoding="utf-8")

    ci_rc = validate_report_contract.main(
        [
            "--mode",
            "ci",
            "--manifest",
            str(manifest),
            "--reports-dir",
            "custom_dir",
        ]
    )
    data_update_rc = validate_report_contract.main(
        [
            "--mode",
            "data-update",
            "--manifest",
            str(manifest),
            "--reports-dir",
            "custom_dir",
            "--report-date",
            "20260320",
            "--source-run-id",
            "12345",
            "--head-ref",
            "data/auto-update-20260320",
            "--diff-path",
            "custom_dir/diff_msdata_20260320.md",
            "--provenance-path",
            "custom_dir/provenance_20260320.json",
            "--artifact-name",
            "raw-snapshot-20260320-run-12345",
            "--snapshot-file",
            "raw_snapshot_20260320_run12345.tar.xz",
            "--release-tag",
            "raw-snapshot-20260320-run-12345",
        ]
    )

    assert ci_rc == 0
    assert data_update_rc == 0


def test_ci_mode_rejects_nested_reports_suffix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("reports_manifest.json")
    _write_json(manifest, _manifest())
    nested_dir = Path("custom_dir/foo/reports")
    nested_dir.mkdir(parents=True)
    (nested_dir / "diff_msdata_20260320.md").write_text("ng", encoding="utf-8")

    rc = validate_report_contract.main(
        [
            "--mode",
            "ci",
            "--manifest",
            str(manifest),
            "--reports-dir",
            "custom_dir",
        ]
    )

    assert rc == 1


def test_data_update_mode_year_month_patterns(tmp_path: Path) -> None:
    manifest_data = _manifest()
    manifest_data["naming"][
        "diff_pattern"
    ] = "reports/{report_year}/{report_month}/diff_msdata_{report_date}.md"
    manifest_data["naming"][
        "provenance_pattern"
    ] = "reports/{report_year}/{report_month}/provenance_{report_date}.json"
    manifest = tmp_path / "reports_manifest.json"
    _write_json(manifest, manifest_data)

    rc = validate_report_contract.main(
        [
            "--mode",
            "data-update",
            "--manifest",
            str(manifest),
            "--report-date",
            "20260320",
            "--source-run-id",
            "12345",
            "--head-ref",
            "data/auto-update-20260320",
            "--diff-path",
            "reports/2026/03/diff_msdata_20260320.md",
            "--provenance-path",
            "reports/2026/03/provenance_20260320.json",
            "--artifact-name",
            "raw-snapshot-20260320-run-12345",
            "--snapshot-file",
            "raw_snapshot_20260320_run12345.tar.xz",
            "--release-tag",
            "raw-snapshot-20260320-run-12345",
        ]
    )
    assert rc == 0


def test_data_update_mode_accepts_windows_native_report_paths(tmp_path: Path) -> None:
    manifest_data = _manifest()
    manifest_data["naming"][
        "diff_pattern"
    ] = "reports/{report_year}/{report_month}/diff_msdata_{report_date}.md"
    manifest_data["naming"][
        "provenance_pattern"
    ] = "reports/{report_year}/{report_month}/provenance_{report_date}.json"
    manifest = tmp_path / "reports_manifest.json"
    _write_json(manifest, manifest_data)

    rc = validate_report_contract.main(
        [
            "--mode",
            "data-update",
            "--manifest",
            str(manifest),
            "--reports-dir",
            r"C:\tmp\reports",
            "--report-date",
            "20260320",
            "--source-run-id",
            "12345",
            "--head-ref",
            "data/auto-update-20260320",
            "--diff-path",
            r"C:\tmp\reports\2026\03\diff_msdata_20260320.md",
            "--provenance-path",
            r"C:\tmp\reports\2026\03\provenance_20260320.json",
            "--artifact-name",
            "raw-snapshot-20260320-run-12345",
            "--snapshot-file",
            "raw_snapshot_20260320_run12345.tar.xz",
            "--release-tag",
            "raw-snapshot-20260320-run-12345",
        ]
    )

    assert rc == 0


@pytest.mark.parametrize("pattern_key", ["diff_pattern", "provenance_pattern"])
def test_data_update_mode_rejects_parent_directory_in_report_pattern(
    tmp_path: Path, pattern_key: str
) -> None:
    manifest_data = _manifest()
    manifest_data["naming"][pattern_key] = "reports/../outside_{report_date}.md"
    manifest = tmp_path / "reports_manifest.json"
    _write_json(manifest, manifest_data)

    rc = validate_report_contract.main(
        [
            "--mode",
            "data-update",
            "--manifest",
            str(manifest),
            "--reports-dir",
            "custom",
            "--report-date",
            "20260320",
            "--source-run-id",
            "12345",
            "--head-ref",
            "data/auto-update-20260320",
            "--diff-path",
            (
                "custom/../outside_20260320.md"
                if pattern_key == "diff_pattern"
                else "custom/diff_msdata_20260320.md"
            ),
            "--provenance-path",
            (
                "custom/../outside_20260320.md"
                if pattern_key == "provenance_pattern"
                else "custom/provenance_20260320.json"
            ),
            "--artifact-name",
            "raw-snapshot-20260320-run-12345",
            "--snapshot-file",
            "raw_snapshot_20260320_run12345.tar.xz",
            "--release-tag",
            "raw-snapshot-20260320-run-12345",
        ]
    )

    assert rc == 1
