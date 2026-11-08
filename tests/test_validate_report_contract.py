from pathlib import Path

import pytest

from ms_data.validation import validate_report_contract

from helpers import write_json


def _manifest() -> dict:
    return {
        "version": 3,
        "compatibility": {
            "legacy_path_support": False,
            "min_release_cycles": 1,
            "retirement_criteria": ["legacy consumer count is 0"],
        },
        "naming": {
            "report_date_format": "YYYYMMDD",
            "head_ref_pattern": "data/auto-update-{report_date}",
            "diff_pattern": (
                "reports/{report_year}/{report_month}/diff_msdata_{report_date}.md"
            ),
            "provenance_pattern": (
                "reports/{report_year}/{report_month}/provenance_{report_date}.json"
            ),
            "artifact_pattern": "raw-snapshot-{report_date}-run-{source_run_id}",
            "snapshot_pattern": "raw_snapshot_{report_date}_run{source_run_id}.tar.xz",
            "release_tag_pattern": "raw-snapshot-{report_date}-run-{source_run_id}",
            "idempotency_key": "source_run_id+head_ref",
        },
        "entries": [
            {
                "id": "diff",
                "type": "generated",
                "path_patterns": ["reports/*/*/diff_msdata_*.md"],
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
    write_json(manifest, _manifest())

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


def test_data_update_mode_release_tag_mismatch(tmp_path: Path) -> None:
    manifest = tmp_path / "reports_manifest.json"
    write_json(manifest, _manifest())

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
            "raw-snapshot-20260320-run12345",
        ]
    )
    assert rc == 1


def test_manifest_rejects_unknown_entry_type(tmp_path: Path) -> None:
    bad = _manifest()
    bad["entries"] = [
        {
            "id": "arch",
            "type": "archive",
            "path_patterns": ["reports/archive/**"],
            "producer": ["human"],
            "consumers": ["human"],
            "retention": "git",
        },
    ]
    manifest = tmp_path / "reports_manifest.json"
    write_json(manifest, bad)

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
    write_json(manifest, _manifest())
    reports_dir = tmp_path / "reports"
    (reports_dir / "2026" / "03").mkdir(parents=True)
    (reports_dir / "2026" / "03" / "diff_msdata_20260320.md").write_text(
        "ok", encoding="utf-8"
    )
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
    manifest_data["naming"]["diff_pattern"] = (
        "logical_reports/diff_msdata_{report_date}.md"
    )
    manifest_data["naming"]["provenance_pattern"] = (
        "logical_reports/provenance_{report_date}.json"
    )
    manifest_data["entries"][0]["path_patterns"] = ["logical_reports/diff_msdata_*.md"]
    manifest = Path("reports_manifest.json")
    write_json(manifest, manifest_data)
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
    manifest_data = _manifest()
    # 年月階層の `*` は任意の深さに一致するため、直下限定の pattern で接尾辞一致を検証する。
    manifest_data["entries"][0]["path_patterns"] = ["reports/diff_msdata_*.md"]
    write_json(manifest, manifest_data)
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


def test_data_update_mode_accepts_windows_native_report_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "reports_manifest.json"
    write_json(manifest, _manifest())

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
    write_json(manifest, manifest_data)

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


def _run(tmp_path: Path, manifest: dict, *args: str) -> int:
    path = tmp_path / "reports_manifest.json"
    write_json(path, manifest)
    return validate_report_contract.main(["--manifest", str(path), *args])


def test_auto_review_mode_ok(tmp_path: Path) -> None:
    rc = _run(
        tmp_path,
        _manifest(),
        "--mode",
        "auto-review",
        "--report-date",
        "20260320",
        "--head-ref",
        "data/auto-update-20260320",
    )
    assert rc == 0


def test_auto_review_mode_requires_head_ref(tmp_path: Path, capsys) -> None:
    rc = _run(
        tmp_path, _manifest(), "--mode", "auto-review", "--report-date", "20260320"
    )
    assert rc == 1
    assert "head_ref is required" in capsys.readouterr().err


def test_auto_review_mode_rejects_head_ref_mismatch(tmp_path: Path, capsys) -> None:
    rc = _run(
        tmp_path,
        _manifest(),
        "--mode",
        "auto-review",
        "--report-date",
        "20260320",
        "--head-ref",
        "data/auto-update-20260321",
    )
    assert rc == 1
    assert "head_ref mismatch" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("report_date", "message"),
    [("", "report_date is required"), ("2026-03-20", "must be YYYYMMDD")],
)
def test_data_update_mode_rejects_bad_report_date(
    tmp_path: Path, capsys, report_date: str, message: str
) -> None:
    rc = _run(
        tmp_path,
        _manifest(),
        "--mode",
        "data-update",
        "--report-date",
        report_date,
        "--source-run-id",
        "1",
    )
    assert rc == 1
    assert message in capsys.readouterr().err


def test_data_update_mode_requires_source_run_id(tmp_path: Path, capsys) -> None:
    rc = _run(
        tmp_path, _manifest(), "--mode", "data-update", "--report-date", "20260320"
    )
    assert rc == 1
    assert "source_run_id is required" in capsys.readouterr().err


def test_data_update_mode_reports_missing_args(tmp_path: Path, capsys) -> None:
    rc = _run(
        tmp_path,
        _manifest(),
        "--mode",
        "data-update",
        "--report-date",
        "20260320",
        "--source-run-id",
        "1",
    )
    err = capsys.readouterr().err
    assert rc == 1
    for key in (
        "head_ref",
        "diff",
        "provenance",
        "artifact",
        "snapshot",
        "release_tag",
    ):
        assert f"{key} is required" in err


def test_manifest_shape_rejects_missing_keys_and_empty_entries(
    tmp_path: Path, capsys
) -> None:
    rc = _run(tmp_path, {"entries": []}, "--mode", "ci")
    err = capsys.readouterr().err
    assert rc == 1
    assert "manifest missing keys" in err
    assert "manifest.entries must be a non-empty list" in err


def test_manifest_shape_rejects_missing_and_duplicate_entry_id(
    tmp_path: Path, capsys
) -> None:
    manifest = _manifest()
    manifest["entries"] = [
        {"type": "manual"},
        {"id": "a", "type": "manual"},
        {"id": "a", "type": "manual"},
    ]
    rc = _run(tmp_path, manifest, "--mode", "ci")
    err = capsys.readouterr().err
    assert rc == 1
    assert "entry.id is required" in err
    assert "entry.id duplicated: a" in err


def test_ci_mode_passes_when_reports_dir_missing(tmp_path: Path) -> None:
    rc = _run(
        tmp_path,
        _manifest(),
        "--mode",
        "ci",
        "--reports-dir",
        str(tmp_path / "nope"),
    )
    assert rc == 0
