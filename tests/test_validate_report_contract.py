import json
from pathlib import Path

from scripts import validate_report_contract


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
                "producer": ["scripts.report_msdata_diff"],
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
    manifest = tmp_path / "reports_manifest.yml"
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
    manifest = tmp_path / "reports_manifest.yml"
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
    manifest = tmp_path / "reports_manifest.yml"
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
    manifest = tmp_path / "reports_manifest.yml"
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
