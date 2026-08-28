"""raw snapshot に近いサンプルを作成し、復元後の検証まで行う。"""

from __future__ import annotations

import argparse
import json
import tarfile
import tempfile
from pathlib import Path

from ms_data.pipeline.restore_snapshot import restore_snapshot
from ms_data.validation import validate_msdata, validate_report_contract

REPORT_DATE = "20260531"
REPORT_YEAR_MONTH = f"{REPORT_DATE[:4]}/{REPORT_DATE[4:6]}"
SOURCE_RUN_ID = "12345"


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_sample_record(msdata_path: Path) -> dict[str, object]:
    data = json.loads(msdata_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError(f"sample msData must be a non-empty JSON array: {msdata_path}")
    return data[0]


def create_sample_snapshot(root: Path, snapshot_path: Path) -> None:
    record = _load_sample_record(root / "msData.json")
    sample_dir = snapshot_path.parent / "sample_snapshot"
    cache_dir = sample_dir / "cache"
    reports_month_dir = sample_dir / "reports" / REPORT_DATE[:4] / REPORT_DATE[4:6]
    html_dir = cache_dir / "html"

    _write_json(
        cache_dir / "index.json",
        [
            {
                "name": str(record["MS名"]).rsplit("_LV", 1)[0],
                "url": record.get("wiki_url", ""),
            }
        ],
    )
    (cache_dir / "details.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_json(cache_dir / "details.json", [record])
    html_dir.mkdir(parents=True, exist_ok=True)
    reports_month_dir.mkdir(parents=True, exist_ok=True)
    (html_dir / "sample.html").write_text(
        "<html><body>sample</body></html>\n", encoding="utf-8"
    )
    (reports_month_dir / f"diff_msdata_{REPORT_DATE}.md").write_text(
        "# sample diff\n\n- レコード数: 1 → 1 | +0 -0 ~0\n",
        encoding="utf-8",
    )
    _write_json(
        reports_month_dir / f"provenance_{REPORT_DATE}.json",
        {
            "date": REPORT_DATE,
            "source_run_id": SOURCE_RUN_ID,
            "artifact": {
                "name": f"raw-snapshot-{REPORT_DATE}-run-{SOURCE_RUN_ID}",
                "retention_days": 90,
            },
            "release": {
                "tag": f"raw-snapshot-{REPORT_DATE}-run-{SOURCE_RUN_ID}",
            },
            "snapshot": {
                "file": f"raw_snapshot_{REPORT_DATE}_run{SOURCE_RUN_ID}.tar.xz",
            },
        },
    )
    _write_json(
        reports_month_dir / f"atwiki_quality_{REPORT_DATE}.json",
        {
            "schema_version": "1",
            "report_date": REPORT_DATE,
            "source_run_id": SOURCE_RUN_ID,
            "index": {
                "total_count": 1,
                "candidate_count": 1,
                "full_update": False,
                "fast_path": True,
                "fallback_reason": "none",
            },
            "detail_fetch": {
                "attempted_url_count": 1,
                "successful_url_count": 1,
                "failed_url_count": 0,
                "http_status_counts": {"200": 1},
                "conditional_cache_hit_count": 0,
                "cache_utilization": 0.0,
            },
            "details": {
                "json_records": 1,
                "jsonl_records": 1,
            },
            "msdata_diff": {
                "old_count": 1,
                "new_count": 1,
                "added": 0,
                "removed": 0,
                "changed": 0,
            },
            "warnings": [],
        },
    )

    with tarfile.open(snapshot_path, "w:xz") as archive:
        for path in (
            html_dir,
            cache_dir / "index.json",
            cache_dir / "details.jsonl",
            cache_dir / "details.json",
            reports_month_dir / f"diff_msdata_{REPORT_DATE}.md",
            reports_month_dir / f"provenance_{REPORT_DATE}.json",
            reports_month_dir / f"atwiki_quality_{REPORT_DATE}.json",
        ):
            archive.add(path, arcname=path.relative_to(sample_dir).as_posix())


def verify(root: Path) -> None:
    with tempfile.TemporaryDirectory() as temp_name:
        temp_dir = Path(temp_name)
        snapshot_path = (
            temp_dir / f"raw_snapshot_{REPORT_DATE}_run{SOURCE_RUN_ID}.tar.xz"
        )
        restore_dir = temp_dir / "restore"
        create_sample_snapshot(root, snapshot_path)
        restored = restore_snapshot(snapshot_path, restore_dir)
        required = {
            "cache/html",
            "cache/index.json",
            "cache/details.jsonl",
            "cache/details.json",
            f"reports/{REPORT_YEAR_MONTH}/diff_msdata_{REPORT_DATE}.md",
            f"reports/{REPORT_YEAR_MONTH}/provenance_{REPORT_DATE}.json",
            f"reports/{REPORT_YEAR_MONTH}/atwiki_quality_{REPORT_DATE}.json",
        }
        missing = required - set(restored)
        if missing:
            raise ValueError(f"snapshot restore missing entries: {sorted(missing)}")

        if validate_msdata.main([str(restore_dir / "cache/details.json")]) != 0:
            raise ValueError("restored cache/details.json did not validate as msData")

        rc = validate_report_contract.main(
            [
                "--mode",
                "post-merge",
                "--manifest",
                str(root / "reports_manifest.json"),
                "--report-date",
                REPORT_DATE,
                "--source-run-id",
                SOURCE_RUN_ID,
                "--head-ref",
                f"data/auto-update-{REPORT_DATE}",
                "--diff-path",
                f"reports/{REPORT_YEAR_MONTH}/diff_msdata_{REPORT_DATE}.md",
                "--provenance-path",
                f"reports/{REPORT_YEAR_MONTH}/provenance_{REPORT_DATE}.json",
                "--artifact-name",
                f"raw-snapshot-{REPORT_DATE}-run-{SOURCE_RUN_ID}",
                "--snapshot-file",
                f"raw_snapshot_{REPORT_DATE}_run{SOURCE_RUN_ID}.tar.xz",
                "--release-tag",
                f"raw-snapshot-{REPORT_DATE}-run-{SOURCE_RUN_ID}",
            ]
        )
        if rc != 0:
            raise ValueError("restored snapshot report contract validation failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    verify(args.root)
    print("OK: snapshot restore verification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
