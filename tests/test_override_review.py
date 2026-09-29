"""期限確認の取得証拠を、候補選定から監査・品質警告まで検証する。"""

import argparse
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import httpx
import pytest

from ms_data.audit.audit_official_overrides import build_audit, render_markdown
from ms_data.core.ms_names import extract_ms_base_name
from ms_data.net.cache_http import CacheConfig, CacheHTTP
from ms_data.pipeline import update_msdata
from ms_data.pipeline.override_review import (
    due_base_names,
    include_due_items,
    load_lifecycle_metadata,
    value_evidence,
)
from ms_data.reporting.build_atwiki_quality_report import build_report
from ms_data.scraping import scrape_msdata as sm

ROOT = Path(__file__).resolve().parents[1]
URL = "https://example.test/1"
RUN = "2026-09-30T00:01:00Z"
SELECTED = "2026-09-30T00:00:00Z"
NAME = "テスト_LV1"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def make_state():
    return {
        "run_started_at": RUN,
        "items": {
            URL: {
                "attempted_at": RUN,
                "fetched_at": RUN,
                "http_status": 200,
                "ok": True,
                "network_fetched": True,
                "parse_status": "parsed",
                "override_values": {NAME: {"HP": 10000}},
            }
        },
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "available"),
        ({"attempted_at": "2026-09-29T00:00:00Z"}, "not_fetched"),
        (
            {"ok": False, "failure_stage": "fetch_failed", "http_status": 503},
            "fetch_failed",
        ),
        ({"ok": False, "failure_stage": "parse_failed"}, "parse_failed"),
        ({"parse_status": "failed"}, "parse_failed"),
        ({"parse_status": "skipped"}, "not_parsed"),
        ({"override_values": {}}, "value_missing"),
        ({"override_values": {NAME: {"HP": None}}}, "value_missing"),
        ({"override_values": {NAME: {"HP": 0}}}, "available"),
        ({"network_fetched": False}, "cached_only"),
        ({"fetched_at": "2026-09-29T00:00:00Z"}, "cached_only"),
        ({"fetched_at": "invalid"}, "cached_only"),
        ({"http_status": 500}, "cached_only"),
    ],
)
def test_evidence_requires_current_successful_fetch_and_parse(changes, expected):
    state = make_state()
    state["items"][URL].update(changes)
    result = value_evidence(
        NAME, "HP", [{"name": "テスト", "url": URL}], state, SELECTED
    )
    assert result["evidence_status"] == expected
    rows, counts, _ = build_audit(
        overrides={NAME: {"HP": {"value": 10000, "stale_value": 9000}}},
        current_records={NAME: {"HP": 10000}},
        before_records={NAME: {"HP": 10000}},
        # Even a stale raw file claiming a match must not override fetch evidence.
        raw_records={NAME: {"HP": 10000}},
        index=[{"name": "テスト", "url": URL}],
        fetch_state=state,
        selection_time=SELECTED,
        today=date(2026, 9, 30),
    )
    assert bool(counts["upstream_current"]) == (expected == "available" and not changes)
    assert rows[0]["url"] == URL


@pytest.mark.parametrize("selection", [None, "invalid", "2026-09-30T00:02:00Z"])
def test_old_run_cannot_confirm_new_selection(selection):
    result = value_evidence(
        NAME, "HP", [{"name": "テスト", "url": URL}], make_state(), selection
    )
    assert result["evidence_status"] == "not_fetched"


def test_actual_46_values_unselected_then_confirmed(tmp_path):
    # 2026-09-27の7ページ・16機体・46値を固定し、実データの撤去後も再現する。
    directory = tmp_path / "overrides"
    fixture = ROOT / "tests/fixtures/override_review"
    write_json(
        directory / "overrides.json",
        json.loads((fixture / "overrides.json").read_text(encoding="utf-8")),
    )
    overrides = update_msdata.load_official_overrides(directory)
    metadata = load_lifecycle_metadata(directory)
    index = json.loads((fixture / "index.json").read_text(encoding="utf-8"))
    current = [
        {
            "MS名": name,
            **{field: spec["value"] for field, spec in fields.items()},
            "wiki_url": next(
                item["url"]
                for item in index
                if item["name"] == extract_ms_base_name(name)
            ),
        }
        for name, fields in overrides.items()
    ]
    by_name = {row["MS名"]: row for row in current}
    meta = {"reason_counts": {}, "generated_at": SELECTED}
    selected = include_due_items(index, [], meta, directory, date(2026, 9, 30))
    assert (
        sm.cmd_detect_changed(
            argparse.Namespace(
                input=write_json(tmp_path / "source.json", index),
                out=tmp_path / "selected.json",
                meta_out=tmp_path / "selection.json",
                previous_provenance=write_json(
                    tmp_path / "previous.json", {"generated_at": "2026-09-29T00:00:00Z"}
                ),
                msdata=write_json(tmp_path / "msdata.json", current),
                now=SELECTED,
                freshness_window="1h",
                force_full=False,
                min_age_coverage=0.95,
                overrides_dir=directory,
            )
        )
        == 0
    )
    cli_selection = json.loads((tmp_path / "selected.json").read_text(encoding="utf-8"))
    assert cli_selection == selected
    assert len(selected) == 7
    assert meta["reason_counts"] == {"official_override_due": 7}
    assert all(row["change_reasons"] == ["official_override_due"] for row in selected)
    # An existing ordinary reason is kept, without fetching a URL twice.
    ordinary = [{**index[0], "change_reasons": ["recent_update"]}]
    merged = include_due_items(
        index,
        ordinary,
        {"reason_counts": {"recent_update": 1}},
        directory,
        date(2026, 9, 30),
    )
    assert len(merged) == 7
    assert merged[0]["change_reasons"] == ["recent_update", "official_override_due"]
    assert ordinary[0]["change_reasons"] == ["recent_update"]

    kwargs = {
        "overrides": overrides,
        "current_records": by_name,
        "before_records": by_name,
        "raw_records": by_name,
        "lifecycle_metadata": metadata,
        "today": date(2026, 9, 30),
        "index": index,
        "selection_time": SELECTED,
    }
    rows, counts, lifecycle = build_audit(**kwargs, fetch_state={})
    assert len(rows) == 46
    assert {row["evidence_status"] for row in rows} == {"not_fetched"}
    assert counts["upstream_current"] == 0
    assert "取得証拠不足: 46" in render_markdown(rows, counts, lifecycle)

    state = {"run_started_at": RUN, "items": {}}
    for name, fields in overrides.items():
        url = by_name[name]["wiki_url"]
        entry = state["items"].setdefault(
            url, {**deepcopy(make_state()["items"][URL]), "override_values": {}}
        )
        entry["override_values"][name] = {
            key: spec["value"] for key, spec in fields.items()
        }
    rows, counts, lifecycle = build_audit(**kwargs, fetch_state=state)
    assert counts["upstream_current"] == 46
    assert {row["evidence_status"] for row in rows} == {"match"}
    assert all(
        row["url"] and row["fetched_at"] and row["http_status"] == 200 for row in rows
    )

    paths = {
        key: tmp_path / f"{key}.json"
        for key in ["index", "changed", "meta", "state", "details", "current"]
    }
    write_json(paths["index"], index)
    write_json(paths["changed"], selected)
    write_json(paths["meta"], meta)
    write_json(paths["details"], [])
    write_json(paths["current"], current)
    for evidence, missing in [({}, 46), (state, 0)]:
        write_json(paths["state"], evidence)
        report = build_report(
            report_date="20260930",
            source_run_id="test",
            index_path=paths["index"],
            changed_index_path=paths["changed"],
            changed_meta_path=paths["meta"],
            detail_fetch_state_path=paths["state"],
            details_json_path=paths["details"],
            details_jsonl_path=tmp_path / "empty.jsonl",
            before_msdata_path=paths["current"],
            current_msdata_path=paths["current"],
            overrides_dir=directory,
        )
        assert report["official_overrides"]["missing_evidence_count"] == missing
        assert any(
            w["id"] == "official_override_evidence_missing" for w in report["warnings"]
        ) == bool(missing)


def make_overrides(tmp_path):
    directory = tmp_path / "overrides"
    write_json(
        directory / "test.json",
        {
            "schema_version": "1",
            "remove_after": "2026-01-01",
            "overrides": [
                {"MS名": NAME, "values": {"HP": 10000}, "stale_values": {"HP": 9000}}
            ],
        },
    )
    return directory


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "offline",
        "http_failure",
        "parse_failure",
        "empty",
        "missing",
        "mismatch",
    ],
)
def test_details_expiry_review_bypasses_ttl_and_semantic_skip(
    monkeypatch, tmp_path, mode
):
    directory = make_overrides(tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            503 if mode == "http_failure" else 200, text="<html>same</html>"
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = CacheHTTP(client, CacheConfig(root=tmp_path / "html", ttl_seconds=999999))
    # Seed a fresh cache; a due review must still fetch it again.
    if mode != "http_failure":
        cache.get(URL)
    calls.clear()
    cache.cfg.no_network = mode == "offline"
    monkeypatch.setattr(sm, "_build_cache", lambda *args, **kwargs: cache)

    def parse(_text, **_kwargs):
        if mode == "parse_failure":
            raise ValueError("parse error")
        if mode == "empty":
            return {}
        return {
            1: {
                "MS名": NAME,
                **(
                    {}
                    if mode == "missing"
                    else {"HP": 9500 if mode == "mismatch" else 10000}
                ),
            }
        }

    monkeypatch.setattr(sm, "parse_details", parse)
    index = [{"name": "テスト", "url": URL}]
    selected_at = sm.datetime.now(sm.timezone.utc).isoformat()
    args = argparse.Namespace(
        input=write_json(tmp_path / "index.json", index),
        out=tmp_path / "details.jsonl",
        overrides_dir=directory,
        detail_fetch_state_out=tmp_path / "state.json",
        rate=2.0,
        limit=0,
        changed_only=True,
    )
    assert sm.cmd_details(args) == 0
    assert len(calls) == (0 if mode == "offline" else 1)
    assert cache.cfg.force is False
    state = json.loads(args.detail_fetch_state_out.read_text(encoding="utf-8"))
    rows, counts, _ = build_audit(
        overrides=update_msdata.load_official_overrides(directory),
        current_records={NAME: {"HP": 10000}},
        before_records={NAME: {"HP": 10000}},
        raw_records={},
        index=index,
        fetch_state=state,
        selection_time=selected_at,
    )
    expected = {
        "success": "match",
        "offline": "cached_only",
        "http_failure": "fetch_failed",
        "parse_failure": "parse_failed",
        "empty": "parse_failed",
        "missing": "value_missing",
        "mismatch": "mismatch",
    }[mode]
    assert rows[0]["evidence_status"] == expected
    assert counts["upstream_current"] == (1 if mode == "success" else 0)
    if mode == "http_failure":
        assert rows[0]["http_status"] == 503


def test_due_dates_entry_precedence_and_inactive(tmp_path):
    directory = make_overrides(tmp_path)
    path = directory / "test.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["overrides"][0]["remove_after"] = "2027-01-01"
    write_json(path, data)
    assert due_base_names(directory, date(2026, 9, 30)) == set()
    data["overrides"][0]["review_after"] = "2026-09-30"
    write_json(path, data)
    assert due_base_names(directory, date(2026, 9, 30)) == {"テスト"}
    data["active"] = False
    write_json(path, data)
    assert due_base_names(directory, date(2026, 9, 30)) == set()


def test_snapshot_preserves_review_evidence(monkeypatch, tmp_path):
    from ms_data import tasks
    from ms_data.pipeline.restore_snapshot import restore_snapshot

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tasks, "task_provenance", lambda: 0)
    monkeypatch.setenv("RAW_SNAPSHOT_FILE", "snapshot.tar.xz")
    paths = [
        "cache/detail_fetch_state.json",
        "cache/index_changed_meta.json",
        "cache/index_changed.json",
    ]
    for path in paths:
        write_json(Path(path), {"evidence": path})
    assert tasks.task_snapshot() == 0
    restored = restore_snapshot(Path("snapshot.tar.xz"), Path("restored"))
    assert set(paths) <= set(restored)
    for path in paths:
        assert (Path("restored") / path).read_bytes() == Path(path).read_bytes()


def test_old_paired_selection_and_state_are_not_current_evidence():
    result = value_evidence(
        NAME,
        "HP",
        [{"name": "テスト", "url": URL}],
        make_state(),
        SELECTED,
        today=date(2026, 10, 1),
    )
    assert result["evidence_status"] == "not_fetched"


def test_due_review_preserves_recent_page_optimization():
    from ms_data.tasks import _can_use_changed_only

    assert _can_use_changed_only(
        [
            {"change_reasons": ["recent_update"]},
            {"change_reasons": ["official_override_due"]},
        ],
        {"fast_path": True},
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("complete", "match"),
        ("missing_hp", "value_missing"),
        ("missing_lv", "parse_failed"),
        ("third_value_incomplete", "mismatch"),
    ],
)
def test_real_parser_keeps_missing_value_evidence(
    monkeypatch, tmp_path, mode, expected
):
    directory = make_overrides(tmp_path)
    html = (ROOT / "tests/fixtures/parse_details_space_only.html").read_text(
        encoding="utf-8"
    )
    html = html.replace("14500", "10000")
    if mode == "missing_hp":
        html = html.replace("<tr><th>機体HP</th><td>10000</td></tr>", "")
    elif mode == "missing_lv":
        html = html.replace("LV1", "")
    elif mode == "third_value_incomplete":
        html = html.replace("10000", "9500").replace(
            "<tr><th>スピード</th><td>125</td></tr>", ""
        )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    )
    cache = CacheHTTP(client, CacheConfig(root=tmp_path / "html"))
    monkeypatch.setattr(sm, "_build_cache", lambda *args, **kwargs: cache)
    index = [{"name": "テスト", "url": URL}]
    selected_at = sm.datetime.now(sm.timezone.utc).isoformat()
    args = argparse.Namespace(
        input=write_json(tmp_path / "index.json", index),
        out=tmp_path / "details.jsonl",
        overrides_dir=directory,
        detail_fetch_state_out=tmp_path / "state.json",
        rate=2.0,
        limit=0,
        changed_only=True,
    )
    assert sm.cmd_details(args) == 0
    rows, counts, _ = build_audit(
        overrides=update_msdata.load_official_overrides(directory),
        current_records={NAME: {"HP": 10000}},
        before_records={},
        raw_records={},
        index=index,
        fetch_state=json.loads(args.detail_fetch_state_out.read_text(encoding="utf-8")),
        selection_time=selected_at,
    )
    assert rows[0]["evidence_status"] == expected
    assert counts["upstream_current"] == (1 if mode == "complete" else 0)
    assert bool(args.out.read_text(encoding="utf-8").strip()) == (mode == "complete")
    if mode == "third_value_incomplete":
        assert rows[0]["status"] == "source_changed"
        assert rows[0]["raw"] == 9500
        assert rows[0]["current"] == 10000
