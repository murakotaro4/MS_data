import io
import tarfile

import pytest

from ms_data.pipeline.restore_snapshot import restore_snapshot


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
