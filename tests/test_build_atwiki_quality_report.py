from ms_data.reporting.build_atwiki_quality_report import build_report

from helpers import write_json


def test_build_atwiki_quality_report_counts_fetch_quality_and_diff(tmp_path):
    index = tmp_path / "cache/index.json"
    changed_index = tmp_path / "cache/index_changed.json"
    changed_meta = tmp_path / "cache/index_changed_meta.json"
    detail_fetch_state = tmp_path / "cache/detail_fetch_state.json"
    details_json = tmp_path / "cache/details.json"
    details_jsonl = tmp_path / "cache/details.jsonl"
    before = tmp_path / "before.json"
    current = tmp_path / "current.json"

    write_json(
        index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    write_json(
        changed_index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    write_json(
        changed_meta,
        {
            "candidate_count": 2,
            "fast_path": True,
            "fallback_reason": "",
            "age_coverage": 1.0,
            "min_age_coverage": 0.9,
            "reason_counts": {"recent_update": 2},
        },
    )
    write_json(
        detail_fetch_state,
        {
            "items": {
                "https://example.test/a": {"http_status": 304},
            }
        },
    )
    write_json(details_json, [{"MS名": "A_LV1"}, {"MS名": "B_LV1"}])
    details_jsonl.write_text('{"MS名":"A_LV1"}\n{"MS名":"B_LV1"}\n', encoding="utf-8")
    write_json(before, [{"MS名": "A_LV1", "HP": 100}])
    write_json(current, [{"MS名": "A_LV1", "HP": 120}, {"MS名": "B_LV1", "HP": 100}])

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
    assert report["index"]["min_age_coverage"] == 0.9
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

    write_json(
        index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    write_json(
        changed_index,
        [
            {"name": "A", "url": "https://example.test/a"},
            {"name": "B", "url": "https://example.test/b"},
        ],
    )
    write_json(changed_meta, {"candidate_count": 2})
    write_json(
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
    write_json(details_json, [])
    details_jsonl.write_text("", encoding="utf-8")
    write_json(before, [])
    write_json(current, [])

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

    write_json(index, [{"name": "A", "url": "https://example.test/a"}])
    write_json(changed_index, [{"name": "A", "url": "https://example.test/a"}])
    write_json(changed_meta, {"candidate_count": 1, "fast_path": False})
    write_json(
        detail_fetch_state,
        {
            "items": {
                "https://example.test/a": {"ok": True, "http_status": 200},
            }
        },
    )
    write_json(details_json, [{"MS名": "A_LV1"}])
    details_jsonl.write_text('{"MS名":"A_LV1"}\n', encoding="utf-8")
    write_json(before, [{"MS名": "A_LV1", "HP": 100}])
    write_json(current, [{"MS名": "A_LV1", "HP": 120}])

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


def test_build_atwiki_quality_report_embeds_fetch_stats(tmp_path):
    index = tmp_path / "cache/index.json"
    changed_index = tmp_path / "cache/index_changed.json"
    changed_meta = tmp_path / "cache/index_changed_meta.json"
    detail_fetch_state = tmp_path / "cache/detail_fetch_state.json"
    details_json = tmp_path / "cache/details.json"
    details_jsonl = tmp_path / "cache/details.jsonl"
    fetch_stats = tmp_path / "cache/fetch_stats.json"

    write_json(index, [{"name": "A", "url": "https://example.test/a"}])
    write_json(changed_index, [])
    write_json(
        changed_meta,
        {"candidate_count": 0, "mode": "revalidate", "fallback_reason": "revalidate"},
    )
    write_json(detail_fetch_state, {"items": {}})
    write_json(details_json, [])
    details_jsonl.write_text("", encoding="utf-8")
    write_json(
        fetch_stats,
        {
            "phases": {
                "index": {"network_requests": 1, "status_200": 1, "body_bytes": 100},
                "details": {"network_requests": 5, "status_200": 5, "body_bytes": 500},
            },
            "totals": {
                "network_requests": 6,
                "status_200": 6,
                "body_bytes": 600,
                "duration_seconds": 12.5,
            },
        },
    )

    report = build_report(
        report_date="20260611",
        source_run_id="12345",
        index_path=index,
        changed_index_path=changed_index,
        changed_meta_path=changed_meta,
        detail_fetch_state_path=detail_fetch_state,
        details_json_path=details_json,
        details_jsonl_path=details_jsonl,
        before_msdata_path=None,
        current_msdata_path=None,
        fetch_stats_path=fetch_stats,
    )

    assert report["index"]["mode"] == "revalidate"
    assert report["fetch"]["totals"]["network_requests"] == 6
    assert report["fetch"]["totals"]["body_bytes"] == 600
    assert set(report["fetch"]["phases"]) == {"index", "details"}


def test_build_atwiki_quality_report_handles_missing_fetch_stats(tmp_path):
    index = tmp_path / "cache/index.json"
    write_json(index, [])

    report = build_report(
        report_date="20260611",
        source_run_id="12345",
        index_path=index,
        changed_index_path=tmp_path / "missing_changed.json",
        changed_meta_path=tmp_path / "missing_meta.json",
        detail_fetch_state_path=tmp_path / "missing_state.json",
        details_json_path=tmp_path / "missing_details.json",
        details_jsonl_path=tmp_path / "missing_details.jsonl",
        before_msdata_path=None,
        current_msdata_path=None,
        fetch_stats_path=tmp_path / "missing_fetch_stats.json",
    )

    assert report["fetch"] == {"totals": {}, "phases": {}}


def test_large_diff_warning_fires_for_revalidate_mode():
    from ms_data.reporting.build_atwiki_quality_report import evaluate_quality_warnings

    report = {
        "index": {"full_update": False, "mode": "revalidate"},
        "detail_fetch": {"attempted_url_count": 0, "failed_url_count": 0},
        "details": {"jsonl_records": 0},
        "msdata_diff": {"added": 150, "removed": 0, "changed": 100},
    }

    warnings = evaluate_quality_warnings(
        report,
        max_failure_rate=0.10,
        min_detail_record_ratio=0.80,
        full_diff_warning_count=200,
    )

    assert [w["id"] for w in warnings] == ["large_full_update_diff"]


def test_large_diff_warning_not_fired_for_fast_mode():
    from ms_data.reporting.build_atwiki_quality_report import evaluate_quality_warnings

    report = {
        "index": {"full_update": False, "mode": "fast"},
        "detail_fetch": {"attempted_url_count": 0, "failed_url_count": 0},
        "details": {"jsonl_records": 0},
        "msdata_diff": {"added": 150, "removed": 0, "changed": 100},
    }

    warnings = evaluate_quality_warnings(
        report,
        max_failure_rate=0.10,
        min_detail_record_ratio=0.80,
        full_diff_warning_count=200,
    )

    assert warnings == []


def _write_minimal_inputs(tmp_path):
    index = tmp_path / "index.json"
    changed_index = tmp_path / "index_changed.json"
    changed_meta = tmp_path / "index_changed_meta.json"
    state = tmp_path / "state.json"
    details_json = tmp_path / "details.json"
    details_jsonl = tmp_path / "details.jsonl"
    current = tmp_path / "current.json"
    write_json(index, [{"name": "A", "url": "https://example.test/a"}])
    write_json(changed_index, [{"name": "A", "url": "https://example.test/a"}])
    write_json(
        changed_meta,
        {"candidate_count": 1, "fast_path": True, "reason_counts": {}},
    )
    write_json(state, {"items": {}})
    write_json(details_json, [{"MS名": "A_LV1"}])
    details_jsonl.write_text('{"MS名":"A_LV1"}\n', encoding="utf-8")
    write_json(current, [{"MS名": "A_LV1", "HP": 100}])
    return [
        "--index", str(index),
        "--changed-index", str(changed_index),
        "--changed-meta", str(changed_meta),
        "--detail-fetch-state", str(state),
        "--details-json", str(details_json),
        "--details-jsonl", str(details_jsonl),
        "--current-msdata", str(current),
        "--fetch-stats", str(tmp_path / "missing_stats.json"),
        "--overrides-dir", str(tmp_path / "no_overrides"),
    ]  # fmt: skip


def test_main_writes_report_github_output_and_step_summary(tmp_path, capsys):
    import json

    from ms_data.reporting.build_atwiki_quality_report import main

    out = tmp_path / "out/report.json"
    gh_output = tmp_path / "gh_output.txt"
    summary = tmp_path / "summary.md"
    rc = main(
        [
            "--report-date", "20260531",
            "--source-run-id", "1",
            "--out", str(out),
            "--github-output", str(gh_output),
            "--step-summary", str(summary),
            *_write_minimal_inputs(tmp_path),
        ]
    )  # fmt: skip

    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["detail_fetch"]["attempted_url_count"] >= 0
    output_lines = gh_output.read_text(encoding="utf-8").splitlines()
    assert f"warning_count={len(report['warnings'])}" in output_lines
    assert any(line.startswith("warning_summary=") for line in output_lines)
    text = summary.read_text(encoding="utf-8")
    assert "### atwiki 取得品質" in text
    assert f"- warnings: {len(report['warnings'])}" in text
    assert "msdata_diff:" in text
    assert "atwiki quality report:" in capsys.readouterr().out


def test_main_step_summary_includes_fetch_totals_and_warnings(tmp_path):
    from ms_data.reporting.build_atwiki_quality_report import main

    args = _write_minimal_inputs(tmp_path)
    stats = tmp_path / "stats.json"
    write_json(
        stats,
        {
            "phases": {},
            "totals": {
                "network_requests": 3,
                "status_200": 2,
                "status_304": 1,
                "failures": 0,
                "body_bytes": 10,
                "duration_seconds": 1.5,
            },
        },
    )
    args[args.index("--fetch-stats") + 1] = str(stats)
    summary = tmp_path / "summary.md"
    main(
        [
            "--report-date", "20260531",
            "--source-run-id", "1",
            "--out", str(tmp_path / "r.json"),
            "--step-summary", str(summary),
            "--full-diff-warning-count", "0",
            "--full-update",
            *args,
        ]
    )  # fmt: skip

    text = summary.read_text(encoding="utf-8")
    assert "- fetch: requests=" in text
    assert "- warning[" in text
