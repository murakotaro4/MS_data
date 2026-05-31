import json

from scripts.build_atwiki_quality_report import build_report


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_build_atwiki_quality_report_counts_fetch_quality_and_diff(tmp_path):
    index = tmp_path / "cache/index.json"
    changed_index = tmp_path / "cache/index_changed.json"
    changed_meta = tmp_path / "cache/index_changed_meta.json"
    detail_fetch_state = tmp_path / "cache/detail_fetch_state.json"
    details_json = tmp_path / "cache/details.json"
    details_jsonl = tmp_path / "cache/details.jsonl"
    before = tmp_path / "before.json"
    current = tmp_path / "current.json"

    _write_json(
        index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    _write_json(
        changed_index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    _write_json(
        changed_meta,
        {
            "candidate_count": 2,
            "fast_path": True,
            "fallback_reason": "",
            "age_coverage": 1.0,
            "reason_counts": {"recent_update": 2},
        },
    )
    _write_json(
        detail_fetch_state,
        {
            "items": {
                "https://example.test/a": {"http_status": 304},
            }
        },
    )
    _write_json(details_json, [{"MS名": "A_LV1"}, {"MS名": "B_LV1"}])
    details_jsonl.write_text('{"MS名":"A_LV1"}\n{"MS名":"B_LV1"}\n', encoding="utf-8")
    _write_json(before, [{"MS名": "A_LV1", "HP": 100}])
    _write_json(current, [{"MS名": "A_LV1", "HP": 120}, {"MS名": "B_LV1", "HP": 100}])

    report = build_report(
        report_date="20260531",
        source_run_id="12345",
        index_path=index,
        changed_index_path=changed_index,
        changed_meta_path=changed_meta,
        detail_fetch_state_path=detail_fetch_state,
        details_json_path=details_json,
        details_jsonl_path=details_jsonl,
        before_msdata_path=before,
        current_msdata_path=current,
    )

    assert report["index"]["total_count"] == 2
    assert report["index"]["candidate_count"] == 2
    assert report["detail_fetch"]["attempted_url_count"] == 2
    assert report["detail_fetch"]["successful_url_count"] == 1
    assert report["detail_fetch"]["failed_url_count"] == 1
    assert report["detail_fetch"]["conditional_cache_hit_count"] == 1
    assert report["warnings"][0]["id"] == "high_failure_rate"
    assert report["details"]["json_records"] == 2
    assert report["details"]["jsonl_records"] == 2
    assert report["msdata_diff"] == {
        "old_count": 1,
        "new_count": 2,
        "added": 1,
        "removed": 0,
        "changed": 1,
    }


def test_build_atwiki_quality_report_ignores_previous_run_success(tmp_path):
    index = tmp_path / "cache/index.json"
    changed_index = tmp_path / "cache/index_changed.json"
    changed_meta = tmp_path / "cache/index_changed_meta.json"
    detail_fetch_state = tmp_path / "cache/detail_fetch_state.json"
    details_json = tmp_path / "cache/details.json"
    details_jsonl = tmp_path / "cache/details.jsonl"
    before = tmp_path / "before.json"
    current = tmp_path / "current.json"

    _write_json(
        index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    _write_json(
        changed_index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    _write_json(changed_meta, {"candidate_count": 2})
    _write_json(
        detail_fetch_state,
        {
            "run_started_at": "2026-05-31T12:00:00Z",
            "items": {
                "https://example.test/a": {
                    "attempted_at": "2026-05-30T12:00:00Z",
                    "ok": True,
                    "http_status": 200,
                },
                "https://example.test/b": {
                    "attempted_at": "2026-05-31T12:00:00Z",
                    "ok": False,
                    "http_status": None,
                    "error": "timeout",
                },
            },
        },
    )
    _write_json(details_json, [])
    details_jsonl.write_text("", encoding="utf-8")
    _write_json(before, [])
    _write_json(current, [])

    report = build_report(
        report_date="20260531",
        source_run_id="12345",
        index_path=index,
        changed_index_path=changed_index,
        changed_meta_path=changed_meta,
        detail_fetch_state_path=detail_fetch_state,
        details_json_path=details_json,
        details_jsonl_path=details_jsonl,
        before_msdata_path=before,
        current_msdata_path=current,
    )

    assert report["detail_fetch"]["attempted_url_count"] == 2
    assert report["detail_fetch"]["successful_url_count"] == 0
    assert report["detail_fetch"]["failed_url_count"] == 2


def test_build_atwiki_quality_report_warns_on_large_full_update(tmp_path):
    index = tmp_path / "cache/index.json"
    changed_index = tmp_path / "cache/index_changed.json"
    changed_meta = tmp_path / "cache/index_changed_meta.json"
    detail_fetch_state = tmp_path / "cache/detail_fetch_state.json"
    details_json = tmp_path / "cache/details.json"
    details_jsonl = tmp_path / "cache/details.jsonl"
    before = tmp_path / "before.json"
    current = tmp_path / "current.json"

    _write_json(index, [{"name": "A", "url": "https://example.test/a"}])
    _write_json(changed_index, [{"name": "A", "url": "https://example.test/a"}])
    _write_json(changed_meta, {"candidate_count": 1, "fast_path": False})
    _write_json(
        detail_fetch_state,
        {
            "items": {
                "https://example.test/a": {"ok": True, "http_status": 200},
            }
        },
    )
    _write_json(details_json, [{"MS名": "A_LV1"}])
    details_jsonl.write_text('{"MS名":"A_LV1"}\n', encoding="utf-8")
    _write_json(before, [{"MS名": "A_LV1", "HP": 100}])
    _write_json(current, [{"MS名": "A_LV1", "HP": 120}])

    report = build_report(
        report_date="20260531",
        source_run_id="12345",
        index_path=index,
        changed_index_path=changed_index,
        changed_meta_path=changed_meta,
        detail_fetch_state_path=detail_fetch_state,
        details_json_path=details_json,
        details_jsonl_path=details_jsonl,
        before_msdata_path=before,
        current_msdata_path=current,
        full_update=True,
        full_diff_warning_count=1,
    )

    assert report["index"]["full_update"] is True
    assert {warning["id"] for warning in report["warnings"]} == {
        "large_full_update_diff"
    }
