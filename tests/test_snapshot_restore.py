import io
import tarfile
from pathlib import Path

import pytest

from ms_data.pipeline.restore_snapshot import main as restore_snapshot_main
from ms_data.pipeline.restore_snapshot import restore_snapshot
from ms_data.validation import verify_snapshot_restore


def _add_text(archive, name, text):
    data = text.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def test_restore_snapshot_restores_cache_and_reports(tmp_path):
    snapshot = tmp_path / "raw_snapshot.tar.xz"
    with tarfile.open(snapshot, "w:xz") as archive:
        _add_text(archive, "cache/index.json", "[]")
        _add_text(archive, "reports/provenance_20260531.json", "{}")

    restored = restore_snapshot(snapshot, tmp_path / "out")

    assert restored == ["cache/index.json", "reports/provenance_20260531.json"]
    assert (tmp_path / "out/cache/index.json").read_text(encoding="utf-8") == "[]"
    assert (tmp_path / "out/reports/provenance_20260531.json").read_text(
        encoding="utf-8"
    ) == "{}"


def test_restore_snapshot_rejects_path_traversal(tmp_path):
    snapshot = tmp_path / "bad_snapshot.tar.xz"
    with tarfile.open(snapshot, "w:xz") as archive:
        _add_text(archive, "../escape.txt", "bad")

    with pytest.raises(ValueError):
        restore_snapshot(snapshot, tmp_path / "out")


def test_restore_snapshot_rejects_absolute_path(tmp_path):
    snapshot = tmp_path / "abs_snapshot.tar.xz"
    with tarfile.open(snapshot, "w:xz") as archive:
        _add_text(archive, "/etc/escape.txt", "bad")

    with pytest.raises(ValueError, match="absolute path"):
        restore_snapshot(snapshot, tmp_path / "out")


def test_restore_snapshot_creates_directory_entries(tmp_path):
    snapshot = tmp_path / "dir_snapshot.tar.xz"
    with tarfile.open(snapshot, "w:xz") as archive:
        info = tarfile.TarInfo("cache/html")
        info.type = tarfile.DIRTYPE
        archive.addfile(info)

    restored = restore_snapshot(snapshot, tmp_path / "out")

    assert restored == ["cache/html"]
    assert (tmp_path / "out/cache/html").is_dir()


def test_restore_snapshot_rejects_unsupported_entry(tmp_path):
    snapshot = tmp_path / "link_snapshot.tar.xz"
    with tarfile.open(snapshot, "w:xz") as archive:
        info = tarfile.TarInfo("cache/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "index.json"
        archive.addfile(info)

    with pytest.raises(ValueError, match="unsupported snapshot entry"):
        restore_snapshot(snapshot, tmp_path / "out")


def test_restore_snapshot_main_prints_entries(tmp_path, capsys):
    snapshot = tmp_path / "raw_snapshot.tar.xz"
    with tarfile.open(snapshot, "w:xz") as archive:
        _add_text(archive, "cache/index.json", "[]")

    rc = restore_snapshot_main(
        ["--snapshot", str(snapshot), "--out-dir", str(tmp_path / "out")]
    )

    assert rc == 0
    assert capsys.readouterr().out.splitlines() == [
        "cache/index.json",
        "restored: 1 entries",
    ]


def test_verify_snapshot_restore_round_trip_with_current_contract():
    verify_snapshot_restore.verify(Path("."))


@pytest.mark.parametrize("content", ["{}", "[]", "[1]"])
def test_load_sample_record_rejects_invalid_msdata(tmp_path, content):
    path = tmp_path / "msData.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty JSON array"):
        verify_snapshot_restore._load_sample_record(path)


def test_verify_detects_missing_restored_entries(monkeypatch):
    monkeypatch.setattr(
        verify_snapshot_restore, "restore_snapshot", lambda *_args: ["cache/index.json"]
    )

    with pytest.raises(ValueError, match="missing entries"):
        verify_snapshot_restore.verify(Path("."))


def test_verify_detects_invalid_restored_msdata(monkeypatch):
    monkeypatch.setattr(
        verify_snapshot_restore.validate_msdata, "main", lambda _argv: 1
    )

    with pytest.raises(ValueError, match="did not validate as msData"):
        verify_snapshot_restore.verify(Path("."))


def test_verify_detects_report_contract_failure(monkeypatch):
    monkeypatch.setattr(
        verify_snapshot_restore.validate_report_contract, "main", lambda _argv: 1
    )

    with pytest.raises(ValueError, match="report contract validation failed"):
        verify_snapshot_restore.verify(Path("."))


def test_verify_snapshot_restore_main_reports_ok(capsys):
    assert verify_snapshot_restore.main(["--root", "."]) == 0

    assert "OK: snapshot restore verification" in capsys.readouterr().out
