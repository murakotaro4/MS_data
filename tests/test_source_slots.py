"""取得元異常の隔離境界、条件付き補正、従来の全体安全停止の回帰。"""

import json
import tarfile
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

import ms_data.tasks as tasks
from ms_data.audit import audit_official_overrides, source_slots
from ms_data.pipeline import official_overrides, update_msdata
from ms_data.reporting import build_update_mail_body
from ms_data.validation.validate_generated_reports import validate_reports

from helpers import make_ms_record, write_json
from workflow_contract import step_block, workflow_text

TODAY = date(2026, 10, 5)
EXPIRED = date(2026, 10, 20)
NAME = "ガブスレイ_LV2"
ROOT = Path(__file__).resolve().parents[1]


def levels(middle: int = 22) -> dict:
    slots = [(19, 20, 11), (21, middle, 13), (23, 24, 15)]
    return {
        f"ガブスレイ_LV{lv}": make_ms_record(
            f"ガブスレイ_LV{lv}",
            コスト=550 + lv * 50,
            近スロット=near,
            中スロット=mid,
            遠スロット=far,
        )
        for lv, (near, mid, far) in enumerate(slots, 1)
    }


def approval() -> dict:
    return {
        NAME: {
            "中スロット": {
                "value": 22,
                "stale_value": 12,
                "source_error_confirmed": True,
                "expires_after": "2026-10-19",
            }
        }
    }


def test_quarantine_rejects_entire_lv_and_continues_other_machine_and_level():
    before = levels()
    before["別機_LV1"] = make_ms_record("別機_LV1")
    incoming = deepcopy(before)
    incoming[NAME].update(中スロット=12, HP=15000)
    incoming["別機_LV1"]["HP"] = 16000
    incoming["ガブスレイ_LV3"]["HP"] = 17000
    preserved = deepcopy((before, incoming))

    adopted, audit = source_slots.quarantine_sources(before, incoming, {}, today=TODAY)

    assert adopted[NAME] == before[NAME]
    assert adopted["別機_LV1"]["HP"] == 16000
    assert adopted["ガブスレイ_LV3"]["HP"] == 17000
    assert audit["status"] == "partial_hold"
    assert audit["held_record_count"] == 1
    assert audit["findings"][0]["action"] == "retained_previous"
    assert (before, incoming) == preserved


def test_new_anomalous_lv_is_skipped_without_dropping_good_new_record():
    before = levels()
    del before[NAME]
    incoming = {NAME: levels(12)[NAME], "新機_LV1": make_ms_record("新機_LV1")}
    adopted, audit = source_slots.quarantine_sources(before, incoming, {}, today=TODAY)
    assert NAME not in adopted
    assert "新機_LV1" in adopted
    row = audit["findings"][0]
    assert (row["action"], row["previous_state"], row["adopted"]) == (
        "skipped_new_record",
        "missing",
        None,
    )


def test_previous_suspicious_value_is_not_presented_as_trusted_fallback():
    before = levels(12)
    incoming = deepcopy(before)
    incoming[NAME]["HP"] = 15000
    adopted, audit = source_slots.quarantine_sources(before, incoming, {}, today=TODAY)
    assert adopted[NAME] == before[NAME]
    assert audit["previous_unverified_count"] == 1
    assert audit["findings"][0]["action"] == "previous_unverified_retained"
    assert audit["findings"][0]["previous_state"] == "unverified"
    assert "正常な前値なし・既存値も未確認／要対応" in source_slots.render_markdown(
        audit
    )


def test_newly_available_neighbors_reveal_unverified_previous_valley():
    before = {NAME: levels(12)[NAME]}
    adopted, audit = source_slots.quarantine_sources(
        before, levels(11), {}, today=TODAY
    )
    assert adopted[NAME] == before[NAME]
    assert audit["previous_unverified_count"] == 1
    assert audit["findings"][0]["action"] == "previous_unverified_retained"
    assert audit["findings"][0]["previous_state"] == "unverified"


def test_holding_candidate_reports_authorized_repair_of_known_bad_previous():
    before = levels(12)
    raw = deepcopy(before)
    raw[NAME].update(近スロット=0, HP=15000)
    adopted, audit = source_slots.quarantine_sources(
        before, raw, approval(), today=TODAY
    )
    assert adopted[NAME] == {**before[NAME], "中スロット": 22}
    assert audit["held_record_count"] == audit["fallback_corrected_record_count"] == 1
    for row in audit["findings"]:
        assert row["action"] == "retained_previous_with_approved_correction"
        assert row["fallback_corrections"]["中スロット"] == {
            "previous": 12,
            "adopted": 22,
            "expires_after": "2026-10-19",
        }
    assert "前値の承認修復" in source_slots.render_markdown(audit)


def test_expired_unverified_hold_continues_through_downstream_override_audit(tmp_path):
    before, raw = levels(12), levels(12)
    raw["新機_LV1"] = make_ms_record("新機_LV1")
    adopted, source_audit = source_slots.quarantine_sources(
        before, raw, approval(), today=EXPIRED
    )
    assert "新機_LV1" in adopted
    rows, counts, _ = audit_official_overrides.build_audit(
        overrides=approval(),
        current_records=adopted,
        before_records=before,
        raw_records=raw,
        source_slot_audit=source_audit,
        today=EXPIRED,
    )
    assert counts["protected_rollback"] == 0
    assert rows[0]["status"] == "source_hold_unverified_previous"
    for path, records in [
        ("before.json", before),
        ("raw.json", raw),
        ("current.json", adopted),
    ]:
        write_json(tmp_path / path, list(records.values()))
    write_json(tmp_path / "source.json", source_audit)
    override_dir = tmp_path / "overrides"
    write_json(
        override_dir / "temporary.json",
        {
            "overrides": [
                {
                    "MS名": NAME,
                    "values": {"中スロット": 22},
                    "stale_values": {"中スロット": 12},
                    "source_error_confirmed": True,
                    "expires_after": "2026-10-19",
                }
            ]
        },
    )
    assert (
        audit_official_overrides.main(
            [
                "--overrides-dir",
                str(override_dir),
                "--before",
                str(tmp_path / "before.json"),
                "--raw",
                str(tmp_path / "raw.json"),
                "--current",
                str(tmp_path / "current.json"),
                "--source-slot-audit",
                str(tmp_path / "source.json"),
                "--today",
                "2026-10-20",
                "--out",
                str(tmp_path / "official.md"),
                "--fail-on-protected-rollback",
            ]
        )
        == 0
    )
    assert "source_hold_unverified_previous" in (tmp_path / "official.md").read_text()


@pytest.mark.parametrize(
    "unsafe",
    [
        "old_override",
        "real_rollback",
        "record_modified",
        "missing_audit",
        "global_error",
    ],
)
def test_source_hold_classification_preserves_existing_protected_rollback(unsafe):
    before, raw = levels(12), levels(12)
    adopted, source_audit = source_slots.quarantine_sources(
        before, raw, approval(), today=EXPIRED
    )
    specs = approval()
    if unsafe == "old_override":
        del specs[NAME]["中スロット"]["source_error_confirmed"]
    elif unsafe == "real_rollback":
        before[NAME]["中スロット"] = 22
    elif unsafe == "record_modified":
        adopted[NAME]["HP"] += 1000
    elif unsafe == "missing_audit":
        source_audit = None
    else:
        source_audit["global_errors"] = ["schema failure"]
    _, counts, _ = audit_official_overrides.build_audit(
        overrides=specs,
        current_records=adopted,
        before_records=before,
        raw_records=raw,
        source_slot_audit=source_audit,
        today=EXPIRED,
    )
    assert counts["protected_rollback"] == 1


def test_expired_known_bad_prior_held_for_another_slot_still_is_not_a_rollback():
    raw = levels()
    raw[NAME]["近スロット"] = 0
    before = levels(12)
    adopted, audit = source_slots.quarantine_sources(
        before, raw, approval(), today=EXPIRED
    )
    assert adopted[NAME] == before[NAME]
    assert audit["findings"][0]["field"] == "近スロット"
    _, counts, _ = audit_official_overrides.build_audit(
        overrides=approval(),
        current_records=adopted,
        before_records=before,
        raw_records=raw,
        source_slot_audit=audit,
        today=EXPIRED,
    )
    assert counts["protected_rollback"] == 0


def test_owner_confirmed_correction_preserves_raw_and_replaces_known_bad_prior():
    before = levels(12)
    raw = deepcopy(before)
    raw[NAME]["HP"] = 15000
    adopted, audit = source_slots.quarantine_sources(
        before, raw, approval(), today=TODAY
    )
    assert adopted[NAME]["中スロット"] == 22
    assert adopted[NAME]["HP"] == 15000
    assert before[NAME]["中スロット"] == raw[NAME]["中スロット"] == 12
    assert audit["held_record_count"] == 0
    assert audit["approved_record_count"] == 1
    row = audit["findings"][0]
    assert (row["observed"], row["previous"], row["adopted"]) == (12, 12, 22)
    assert row["previous_state"] == "known_invalid"
    assert row["comparison"] == {"ガブスレイ_LV1": 20, "ガブスレイ_LV3": 24}
    assert row["slot_totals"] == [50, 46, 62]


@pytest.mark.parametrize(
    "context", ["complete", "missing_neighbors", "changed_neighbor_cost"]
)
def test_expired_known_bad_source_never_re_adopted_without_valley_context(context):
    before = levels()
    raw = levels(12)
    if context == "missing_neighbors":
        before = {NAME: before[NAME]}
        raw = {NAME: raw[NAME]}
    elif context == "changed_neighbor_cost":
        raw["ガブスレイ_LV1"]["コスト"] = 500
    raw[NAME]["HP"] = 15000
    raw["新機_LV1"] = make_ms_record("新機_LV1", HP=16000)
    adopted, audit = source_slots.quarantine_sources(
        before, raw, approval(), today=EXPIRED
    )
    assert adopted[NAME] == before[NAME]
    assert "新機_LV1" in adopted
    row = audit["findings"][0]
    assert row["action"] == "retained_previous"
    assert row["override_expired"] is True
    assert row["observed"] == 12 and row["adopted"] == 22
    assert audit["approved_record_count"] == 0


def test_expired_correction_cannot_trust_the_original_known_bad_twelve():
    before = levels(12)
    adopted, audit = source_slots.quarantine_sources(
        before, before, approval(), today=EXPIRED
    )
    assert adopted[NAME]["中スロット"] == 12
    assert audit["previous_unverified_count"] == 1
    assert audit["findings"][0]["previous_state"] == "known_invalid"
    assert audit["findings"][0]["action"] == "previous_unverified_retained"


@pytest.mark.parametrize("value", [22, 23])
@pytest.mark.parametrize("today", [TODAY, EXPIRED])
def test_upstream_correction_or_third_value_is_imported_without_forcing_22(
    value, today
):
    raw = levels(value)
    raw[NAME]["HP"] = 15000
    adopted, audit = source_slots.quarantine_sources(
        levels(), raw, approval(), today=today
    )
    assert adopted[NAME]["中スロット"] == value
    assert adopted[NAME]["HP"] == 15000
    assert audit["status"] == "ok" and audit["findings"] == []


def test_expiry_is_inclusive_and_old_lifecycle_dates_do_not_change_application():
    spec = approval()[NAME]["中スロット"]
    assert official_overrides.override_is_active(spec, date(2026, 10, 19))
    assert not official_overrides.override_is_active(spec, EXPIRED)
    old_spec = {NAME: {"中スロット": {"value": 22, "stale_value": 12}}}
    records = levels(12)
    assert (
        official_overrides.apply_official_overrides(records, old_spec, today=EXPIRED)
        == 1
    )


def test_legitimate_redistribution_with_increasing_total_is_not_quarantined():
    raw = levels(12)
    raw[NAME]["近スロット"] = 36
    assert source_slots.detect_anomalies(raw) == []
    adopted, audit = source_slots.quarantine_sources(levels(), raw, {}, today=TODAY)
    assert adopted[NAME] == raw[NAME]
    assert audit["held_record_count"] == 0


def test_explicit_temporary_exception_accepts_legitimate_valley_only_for_exact_value():
    specs = {
        NAME: {
            "中スロット": {
                "value": 12,
                "stale_value": 12,
                "allow_source_anomaly": True,
                "expires_after": "2026-10-19",
            }
        }
    }
    raw = levels(12)
    adopted, audit = source_slots.quarantine_sources({}, raw, specs, today=TODAY)
    assert adopted[NAME] == raw[NAME]
    assert audit["approved_record_count"] == 1
    changed = levels(11)
    adopted, audit = source_slots.quarantine_sources({}, changed, specs, today=TODAY)
    assert NAME not in adopted and audit["held_record_count"] == 1
    adopted, audit = source_slots.quarantine_sources({}, raw, specs, today=EXPIRED)
    assert NAME not in adopted and audit["held_record_count"] == 1


@pytest.mark.parametrize(
    "difference",
    ["form", "attribute", "url", "cost", "missing_slot", "boolean_slot", "level_gap"],
)
def test_heuristic_requires_complete_comparable_consecutive_levels(difference):
    raw = levels(12)
    other = raw["ガブスレイ_LV3"]
    if difference == "form":
        del raw["ガブスレイ_LV3"]
        other["MS名"] = "ガブスレイ［別形態］_LV3"
        raw[other["MS名"]] = other
    elif difference == "attribute":
        other["属性"] = "支援"
    elif difference == "url":
        other["wiki_url"] = "https://example.com/other"
    elif difference == "cost":
        other["コスト"] += 50
    elif difference == "missing_slot":
        del other["遠スロット"]
    elif difference == "boolean_slot":
        other["遠スロット"] = True
    else:
        del raw["ガブスレイ_LV3"]
        other["MS名"] = "ガブスレイ_LV4"
        raw[other["MS名"]] = other
    assert source_slots.detect_anomalies(raw) == []


@pytest.mark.parametrize("invalid", ["schema", "semantic", "legacy_protected_rollback"])
def test_quarantine_cannot_mask_existing_global_safety_failures(invalid):
    raw = levels(12)
    specs = {}
    if invalid == "schema":
        raw[NAME]["HP"] = "malformed"
    elif invalid == "semantic":
        raw[NAME]["fullst"] = [
            {"name": "A", "level": 1, "points": 100},
            {"name": "B", "level": 1, "points": 50},
        ]
    else:
        specs = {
            NAME: {
                "HP": {
                    "value": 15000,
                    "stale_value": 12000,
                    "expires_after": "2026-10-04",
                }
            }
        }
    adopted, audit = source_slots.quarantine_sources(levels(), raw, specs, today=TODAY)
    assert adopted[NAME] == raw[NAME]
    assert audit["status"] == "global_validation_error"
    assert audit["global_errors"] and audit["held_record_count"] == 0
    assert audit["findings"][0]["action"] == "global_safety_stop_not_quarantined"


def test_cli_keeps_raw_array_fetch_evidence_and_only_updates_healthy_records(
    tmp_path, monkeypatch
):
    before_path, raw_path = tmp_path / "msData.json", tmp_path / "details.json"
    audit_path, snapshot = tmp_path / "audit.json", tmp_path / "raw.json"
    raw = levels(12)
    raw["ガブスレイ_LV3"]["HP"] = 16000
    write_json(before_path, list(levels().values()))
    write_json(raw_path, list(raw.values()))
    state_path = tmp_path / "fetch.json"
    url = raw[NAME]["wiki_url"]
    write_json(
        state_path,
        {
            "items": {
                url: {
                    "fetched_at": "2026-10-04T14:37:53Z",
                    "attempted_at": "2026-10-04T14:37:52Z",
                    "http_status": 200,
                    "network_fetched": True,
                    "parse_status": "success",
                }
            }
        },
    )
    monkeypatch.setenv("DETAIL_FETCH_STATE", str(state_path))
    assert (
        update_msdata.main(
            [
                str(raw_path),
                "--in-place",
                "--output",
                str(before_path),
                "--no-official-overrides",
                "--source-slot-audit-out",
                str(audit_path),
                "--official-overrides-raw-out",
                str(snapshot),
            ]
        )
        == 0
    )
    adopted = {r["MS名"]: r for r in json.loads(before_path.read_text())}
    original = {r["MS名"]: r for r in json.loads(snapshot.read_text())}
    assert adopted[NAME]["中スロット"] == 22
    assert adopted["ガブスレイ_LV3"]["HP"] == 16000
    assert original[NAME]["中スロット"] == 12
    row = json.loads(audit_path.read_text())["findings"][0]
    assert row["fetched_at"] == "2026-10-04T14:37:53Z"
    assert row["fetch_evidence"]["http_status"] == 200


@pytest.mark.parametrize("zero", ["candidates", "details"])
def test_fast_task_clears_previous_partial_error_even_on_empty_runs(
    tmp_path, monkeypatch, zero
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOURCE_SLOT_AUDIT_OUT", "cache/source_slot_audit.json")
    monkeypatch.setenv("OFFICIAL_OVERRIDE_RAW_OUT", "cache/raw.json")
    write_json(
        Path("cache/source_slot_audit.json"),
        {"status": "old_error", "held_record_count": 4},
    )
    write_json(Path("cache/raw.json"), [{"old": "evidence"}])

    def run(module, *args):
        assert module == "ms_data.scraping.scrape_msdata"
        if args[0] == "detect-changed":
            candidates = [] if zero == "candidates" else [{"name": "対象"}]
            write_json(Path("cache/index_changed.json"), candidates)
            write_json(
                Path("cache/index_changed_meta.json"),
                {"candidate_count": len(candidates)},
            )
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", run)
    monkeypatch.setattr(
        tasks, "task_import_details", lambda: pytest.fail("empty import")
    )
    assert tasks.task_update_fast() == 0
    assert (
        json.loads(Path("cache/source_slot_audit.json").read_text())
        == source_slots.empty_audit()
    )
    assert json.loads(Path("cache/raw.json").read_text()) == []


def test_snapshot_keeps_raw_and_quarantine_evidence_without_data_changes(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tasks, "task_provenance", lambda: 0)
    monkeypatch.setenv("RAW_SNAPSHOT_FILE", "snapshot.tar.xz")
    for variable, path in [
        ("SOURCE_SLOT_AUDIT_OUT", "cache/source.json"),
        ("SOURCE_SLOT_REPORT_OUT", "reports/2026/10/source.md"),
        ("OFFICIAL_OVERRIDE_RAW_OUT", "cache/raw.json"),
    ]:
        monkeypatch.setenv(variable, path)
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(path, encoding="utf-8")
    assert tasks.task_snapshot() == 0
    with tarfile.open("snapshot.tar.xz") as archive:
        for path in (
            "cache/source.json",
            "reports/2026/10/source.md",
            "cache/raw.json",
        ):
            assert archive.extractfile(path).read().decode() == path


@pytest.mark.parametrize(
    "metadata",
    [
        {"expires_after": "20261019"},
        {"expires_after": "2026-02-30"},
        {"expires_after": 20261019},
        {"source_error_confirmed": "yes"},
        {"allow_source_anomaly": "yes"},
        {"source_error_confirmed": True},
        {"allow_source_anomaly": True},
    ],
)
def test_new_approval_metadata_requires_valid_date_boolean_and_expiry(
    tmp_path, metadata
):
    entry = {
        "MS名": NAME,
        "values": {"中スロット": 22},
        "stale_values": {"中スロット": 12},
        **metadata,
    }
    write_json(tmp_path / "override.json", {"overrides": [entry]})
    with pytest.raises(ValueError):
        update_msdata.load_official_overrides(tmp_path)


def test_expired_spec_is_loaded_for_known_error_guard_but_not_applied(tmp_path):
    entry = {
        "MS名": NAME,
        "values": {"中スロット": 22},
        "stale_values": {"中スロット": 12},
        "source_error_confirmed": True,
    }
    write_json(
        tmp_path / "override.json",
        {"expires_after": "2026-10-19", "overrides": [entry]},
    )
    specs = update_msdata.load_official_overrides(tmp_path)
    assert specs[NAME]["中スロット"]["expires_after"] == "2026-10-19"
    records = levels(12)
    assert (
        official_overrides.apply_official_overrides(records, specs, today=EXPIRED) == 0
    )
    assert records[NAME]["中スロット"] == 12


def test_partial_error_report_mail_and_html_keep_evidence_and_warning(tmp_path):
    _, audit = source_slots.quarantine_sources(
        levels(), levels(12), approval(), today=EXPIRED
    )
    audit["findings"][0]["fetched_at"] = "2026-10-04T14:37:53Z"
    audit_json = tmp_path / "cache/source.json"
    report = tmp_path / "reports/2026/10/source_slot_audit_20261005.md"
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    write_json(audit_json, audit)
    assert (
        source_slots.main(
            [
                "--audit-json",
                str(audit_json),
                "--report-out",
                str(report),
                "--github-output",
                str(output),
                "--step-summary",
                str(summary),
            ]
        )
        == 0
    )
    assert "held_record_count=1" in output.read_text()
    assert "finding_count=1" in output.read_text()
    assert "partial_hold" in summary.read_text()
    assert validate_reports(tmp_path / "reports", ROOT / "schema/reports") == []
    plain, html = tmp_path / "mail.txt", tmp_path / "mail.html"
    assert (
        build_update_mail_body.main(
            [
                "--report-date",
                "20261005",
                "--result",
                "部分保留エラー（対応要）",
                "--changed",
                "false",
                "--source-slot-audit-path",
                str(report),
                "--out",
                str(plain),
                "--html-out",
                str(html),
            ]
        )
        == 0
    )
    for path in (plain, html):
        text = path.read_text()
        for evidence in (
            NAME,
            "12",
            "22",
            "retained_previous",
            "2026-10-19",
            "失効",
            "2026-10-04T14:37:53Z",
            "https://example.com/ms/test",
        ):
            assert evidence in text
    assert "LV単位の部分保留（要対応）: 1件" in html.read_text()


def test_generated_report_validation_rejects_incomplete_source_report(tmp_path):
    report = tmp_path / "source_slot_audit_20261005.md"
    report.write_text("# 取得元スロット監査\n", encoding="utf-8")
    assert any(
        "held_record_count" in message
        for message in validate_reports(tmp_path, ROOT / "schema/reports")
    )


def test_workflow_partial_error_archives_without_diff_and_owner_mail_follows_pr():
    text = workflow_text("data_update.yml")
    for start, end in [
        (
            "name: Generate reports and snapshot",
            "name: Validate generated update reports",
        ),
        ("name: Upload raw snapshot artifact", "name: Upload dry-run reports"),
    ]:
        block = step_block(text, start=start, end=end)
        assert "steps.source_slots.outputs.finding_count > 0" in block
    no_change = step_block(
        text,
        start="name: Build no-change mail body",
        end="name: Ensure pull request labels",
    )
    assert "steps.source_slots.outputs.held_record_count == '0'" in no_change
    notification = text[text.index("- id: partial_hold_body") :]
    assert text.index("name: Create pull request") < text.index(
        "- id: partial_hold_body"
    )
    assert "env.DRY_RUN != 'true'" in notification
    assert 'GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}' in notification
    assert 'GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}' in notification
    assert '--to "$GMAIL_ADDRESS"' in notification
    assert "GMAIL_TO" not in notification and "vars.GMAIL" not in notification
    assert notification.count("continue-on-error: true") == 2
    assert "steps.partial_hold_body.outcome == 'success'" in notification
    assert "exit 1" in step_block(
        text,
        start="name: Fail on protected official override rollback",
        end="- id: changes",
    )
