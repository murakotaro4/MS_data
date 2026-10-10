"""ms_data.reporting.prune_reports のテスト。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ms_data.reporting.prune_reports import (
    extract_report_date,
    plan_prune,
    plan_prune_entry,
)

from helpers import write_json


def _entry(**overrides):
    entry = {
        "id": "diff_msdata",
        "type": "generated",
        "path_patterns": ["reports/diff_msdata_*.md"],
        "producer": ["x"],
        "consumers": ["y"],
        "retention": "git",
        "prune": {"max_age_days": 90, "keep_min": 2},
    }
    entry.update(overrides)
    return entry


def _touch_reports(root: Path, dates: list[str]) -> None:
    (root / "reports").mkdir(parents=True, exist_ok=True)
    for date in dates:
        (root / "reports" / f"diff_msdata_{date}.md").write_text("x", encoding="utf-8")


def test_extract_report_date():
    assert extract_report_date(Path("reports/diff_msdata_20260101.md")) == "20260101"
    assert extract_report_date(Path("reports/provenance_20260101.json")) == "20260101"
    assert extract_report_date(Path("reports/label_audit_latest.md")) is None
    assert extract_report_date(Path("reports/README.md")) is None


def test_expired_files_are_deleted(tmp_path: Path):
    _touch_reports(tmp_path, ["20250101", "20250102", "20260601", "20260602"])
    actions = plan_prune_entry(_entry(), root=tmp_path, today="20260610")
    by_date = {item.report_date: item.action for item in actions}
    # 新しい2件は keep_min、古い2件は期限切れ
    assert by_date == {
        "20260602": "keep",
        "20260601": "keep",
        "20250102": "delete",
        "20250101": "delete",
    }


def test_keep_min_protects_expired_files(tmp_path: Path):
    # 全件期限切れでも keep_min 件は保持される
    _touch_reports(tmp_path, ["20250101", "20250102", "20250103"])
    actions = plan_prune_entry(_entry(), root=tmp_path, today="20260610")
    keeps = [item.report_date for item in actions if item.action == "keep"]
    deletes = [item.report_date for item in actions if item.action == "delete"]
    assert keeps == ["20250103", "20250102"]
    assert deletes == ["20250101"]


def test_within_max_age_is_kept(tmp_path: Path):
    _touch_reports(tmp_path, ["20260501", "20260502", "20260503", "20260504"])
    actions = plan_prune_entry(_entry(), root=tmp_path, today="20260610")
    assert all(item.action == "keep" for item in actions)


def test_dateless_files_are_ignored(tmp_path: Path):
    (tmp_path / "reports").mkdir(parents=True)
    (tmp_path / "reports" / "diff_msdata_latest.md").write_text("x", encoding="utf-8")
    actions = plan_prune_entry(_entry(), root=tmp_path, today="20260610")
    assert actions == []


def test_entry_without_prune_is_skipped(tmp_path: Path):
    _touch_reports(tmp_path, ["20250101"])
    entry = _entry()
    del entry["prune"]
    assert plan_prune_entry(entry, root=tmp_path, today="20260610") == []


def test_plan_prune_iterates_entries(tmp_path: Path):
    _touch_reports(tmp_path, ["20250101", "20250102", "20250103"])
    manifest = {"version": 2, "entries": [_entry()]}
    actions = plan_prune(manifest, root=tmp_path, today="20260610")
    assert sum(1 for item in actions if item.action == "delete") == 1


def test_overlapping_patterns_count_once(tmp_path: Path):
    # 同一ファイルが複数パターンにマッチしても1件として扱う
    _touch_reports(tmp_path, ["20250101", "20250102", "20250103"])
    entry = _entry(
        path_patterns=["reports/diff_msdata_*.md", "reports/diff_msdata_2025*.md"]
    )
    actions = plan_prune_entry(entry, root=tmp_path, today="20260610")
    assert len(actions) == 3
    assert sum(1 for item in actions if item.action == "delete") == 1


def test_nested_year_month_patterns_are_pruned(tmp_path: Path):
    reports = tmp_path / "reports"
    for date in ["20250101", "20250102", "20260601", "20260602"]:
        month_dir = reports / date[:4] / date[4:6]
        month_dir.mkdir(parents=True, exist_ok=True)
        (month_dir / f"diff_msdata_{date}.md").write_text("x", encoding="utf-8")
    entry = _entry(
        path_patterns=[
            "reports/*/*/diff_msdata_*.md",
            "reports/diff_msdata_*.md",
        ]
    )
    actions = plan_prune_entry(entry, root=tmp_path, today="20260610")
    by_date = {item.report_date: item.action for item in actions}
    assert by_date == {
        "20260602": "keep",
        "20260601": "keep",
        "20250102": "delete",
        "20250101": "delete",
    }


@pytest.mark.parametrize("keep_min", [0, 1])
@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
def test_cli_ignores_dated_directories(
    tmp_path: Path, keep_min: int, apply: bool
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "diff_msdata_20250101.md"
    report.write_text("report content\n", encoding="utf-8")
    directory = reports / "diff_msdata_20250102.md"
    directory.mkdir()
    marker = directory / "marker.txt"
    marker.write_text("directory content\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    write_json(
        manifest,
        {"entries": [_entry(prune={"max_age_days": 90, "keep_min": keep_min})]},
    )
    command = [
        sys.executable,
        "-m",
        "ms_data.reporting.prune_reports",
        "--manifest",
        str(manifest),
        "--root",
        str(tmp_path),
        "--today",
        "20260610",
    ]
    if apply:
        command.append("--apply")
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"- applied: {str(apply).lower()}" in result.stdout
    assert "- scanned: 1" in result.stdout
    assert f"- delete: {int(keep_min == 0)}" in result.stdout
    if apply and keep_min == 0:
        assert not report.exists()
    else:
        assert report.read_text(encoding="utf-8") == "report content\n"
    assert directory.is_dir()
    assert marker.read_text(encoding="utf-8") == "directory content\n"


def test_symlink_to_regular_report_is_still_planned(tmp_path: Path) -> None:
    target = tmp_path / "source.md"
    target.write_text("report content\n", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    link = reports / "diff_msdata_20250101.md"
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    actions = plan_prune_entry(
        _entry(prune={"max_age_days": 90, "keep_min": 0}),
        root=tmp_path,
        today="20260610",
    )
    assert len(actions) == 1
    assert actions[0].path == link
    assert actions[0].action == "delete"
