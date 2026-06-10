import hashlib
import json
from pathlib import Path

from ms_data.pipeline import generate_provenance


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_sha256_file(tmp_path):
    content = b"abc123"
    p = tmp_path / "tmp_sha_test.bin"
    p.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert generate_provenance.sha256_file(p) == expected


def test_count_jsonl_records_ignores_blank(tmp_path):
    p = tmp_path / "details.jsonl"
    p.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
    assert generate_provenance.count_jsonl_records(p) == 2


def test_main_writes_provenance_json(tmp_path, monkeypatch):
    index = tmp_path / "cache/index.json"
    details_jsonl = tmp_path / "cache/details.jsonl"
    details_json = tmp_path / "cache/details.json"
    msdata = tmp_path / "msData.json"
    diff = tmp_path / "reports/diff_msdata_20260222.md"
    html_dir = tmp_path / "cache/html"
    out = tmp_path / "reports/provenance_20260222.json"

    _write_json(index, [{"name": "A"}, {"name": "B"}])
    _write_text(details_jsonl, '{"MS名":"A_LV1"}\n{"MS名":"B_LV1"}\n')
    _write_json(details_json, [{"MS名": "A_LV1"}, {"MS名": "B_LV1"}])
    _write_json(msdata, [{"MS名": "A_LV1"}])
    _write_text(diff, "# diff\n")
    _write_text(html_dir / "a.html", "<html>A</html>")
    _write_text(html_dir / "b.meta.json", '{"etag":"x"}')

    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_WORKFLOW", "data update")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")

    rc = generate_provenance.main(
        [
            "--date",
            "20260222",
            "--index",
            str(index),
            "--details-jsonl",
            str(details_jsonl),
            "--details-json",
            str(details_json),
            "--msdata",
            str(msdata),
            "--diff",
            str(diff),
            "--html-dir",
            str(html_dir),
            "--out",
            str(out),
            "--ttl",
            "7d",
            "--rate",
            "1.0",
            "--limit",
            "0",
            "--artifact-retention-days",
            "90",
        ]
    )
    assert rc == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert data["report_date"] == "20260222"
    assert data["github"]["run_id"] == "12345"
    assert data["inputs"]["index"]["record_count"] == 2
    assert data["inputs"]["details_jsonl"]["record_count"] == 2
    assert data["inputs"]["details_json"]["record_count"] == 2
    assert data["inputs"]["html_cache"]["file_count"] == 2
    assert data["outputs"]["msdata_json"]["record_count"] == 1
    assert data["artifact"]["name"] == "raw-snapshot-20260222-run-12345"
    assert data["release"]["tag"] == "raw-snapshot-20260222-run-12345"
    assert (
        data["release"]["url"]
        == "https://github.com/owner/repo/releases/tag/raw-snapshot-20260222-run-12345"
    )


def test_main_fails_when_required_input_missing(tmp_path):
    diff = tmp_path / "reports/diff_msdata_20260222.md"
    _write_text(diff, "diff")
    out = tmp_path / "reports/provenance_20260222.json"

    rc = generate_provenance.main(
        [
            "--date",
            "20260222",
            "--index",
            str(tmp_path / "cache/index.json"),
            "--details-jsonl",
            str(tmp_path / "cache/details.jsonl"),
            "--details-json",
            str(tmp_path / "cache/details.json"),
            "--msdata",
            str(tmp_path / "msData.json"),
            "--diff",
            str(diff),
            "--html-dir",
            str(tmp_path / "cache/html"),
            "--out",
            str(out),
        ]
    )
    assert rc == 1
    assert not out.exists()
