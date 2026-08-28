import tarfile
from pathlib import Path

import ms_data.tasks as tasks

REPORT_DATE = "20260827"
REPORT_OUTPUT_ENVS = (
    "PROVENANCE_OUT",
    "DIFF_OUT",
    "ATWIKI_QUALITY_OUT",
    "AUDIT_LABELS_OUT",
    "AUDIT_INDEX_OUT",
    "ROLLBACK_GUARD_OUT",
    "OFFICIAL_OVERRIDES_AUDIT_OUT",
)


def _out_arg(args: tuple[str, ...]) -> str:
    return args[args.index("--out") + 1]


def _collect_report_outputs(
    monkeypatch, tmp_path: Path, expected_snapshot_diff: str
) -> dict[str, str]:
    calls: dict[str, tuple[str, ...]] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OLD", "old.json")
    monkeypatch.setenv("NEW", "new.json")
    monkeypatch.setenv("RAW_SNAPSHOT_FILE", str(tmp_path / "snapshot.tar.xz"))

    def fake_run_python_module(module: str, *args: str) -> int:
        calls[module] = args
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)

    outputs = {"provenance": tasks._provenance_out()}
    assert tasks.task_provenance() == 0
    outputs["provenance_diff"] = calls["ms_data.pipeline.generate_provenance"][
        calls["ms_data.pipeline.generate_provenance"].index("--diff") + 1
    ]

    diff_path = tmp_path / expected_snapshot_diff
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("diff", encoding="utf-8")
    monkeypatch.setattr(tasks, "task_provenance", lambda: 0)
    assert tasks.task_snapshot() == 0
    with tarfile.open(tmp_path / "snapshot.tar.xz", "r:xz") as archive:
        snapshot_members = archive.getnames()
    assert expected_snapshot_diff in snapshot_members
    outputs["snapshot_diff"] = expected_snapshot_diff

    assert tasks.task_atwiki_quality_report() == 0
    outputs["atwiki_quality"] = _out_arg(
        calls["ms_data.reporting.build_atwiki_quality_report"]
    )
    assert tasks.task_audit_labels() == 0
    outputs["audit_labels"] = _out_arg(calls["ms_data.audit.audit_labels"])
    assert tasks.task_audit_index() == 0
    outputs["audit_index"] = _out_arg(calls["ms_data.audit.audit_index_vs_msdata"])
    assert tasks.task_rollback_guard() == 0
    outputs["rollback_guard"] = _out_arg(calls["ms_data.audit.detect_msdata_rollbacks"])
    assert tasks.task_audit_official_overrides() == 0
    outputs["audit_official_overrides"] = _out_arg(
        calls["ms_data.audit.audit_official_overrides"]
    )
    return outputs


def _expected_outputs(base_dir: str) -> dict[str, str]:
    month_dir = f"{base_dir}/2026/08"
    return {
        "provenance": f"{month_dir}/provenance_{REPORT_DATE}.json",
        "provenance_diff": f"{month_dir}/diff_msdata_{REPORT_DATE}.md",
        "snapshot_diff": f"{month_dir}/diff_msdata_{REPORT_DATE}.md",
        "atwiki_quality": f"{month_dir}/atwiki_quality_{REPORT_DATE}.json",
        "audit_labels": f"{month_dir}/label_audit_{REPORT_DATE}.md",
        "audit_index": f"{month_dir}/index_ms_audit_{REPORT_DATE}.md",
        "rollback_guard": f"{month_dir}/rollback_guard_{REPORT_DATE}.md",
        "audit_official_overrides": (
            f"{month_dir}/official_overrides_audit_{REPORT_DATE}.md"
        ),
    }


def _clear_report_output_envs(monkeypatch) -> None:
    for env_name in REPORT_OUTPUT_ENVS:
        monkeypatch.delenv(env_name, raising=False)


def test_report_outputs_keep_default_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REPORT_DATE", REPORT_DATE)
    monkeypatch.delenv("REPORTS_DIR", raising=False)
    _clear_report_output_envs(monkeypatch)
    expected = _expected_outputs("reports")

    assert (
        _collect_report_outputs(monkeypatch, tmp_path, expected["snapshot_diff"])
        == expected
    )


def test_report_outputs_honor_reports_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REPORT_DATE", REPORT_DATE)
    monkeypatch.setenv("REPORTS_DIR", "custom_dir")
    _clear_report_output_envs(monkeypatch)
    expected = _expected_outputs("custom_dir")

    assert (
        _collect_report_outputs(monkeypatch, tmp_path, expected["snapshot_diff"])
        == expected
    )


def test_explicit_report_output_envs_take_priority(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REPORT_DATE", REPORT_DATE)
    monkeypatch.setenv("REPORTS_DIR", "custom_dir")
    explicit = {
        "PROVENANCE_OUT": "explicit/provenance.json",
        "DIFF_OUT": "explicit/diff.md",
        "ATWIKI_QUALITY_OUT": "explicit/atwiki_quality.json",
        "AUDIT_LABELS_OUT": "explicit/label_audit.md",
        "AUDIT_INDEX_OUT": "explicit/index_audit.md",
        "ROLLBACK_GUARD_OUT": "explicit/rollback_guard.md",
        "OFFICIAL_OVERRIDES_AUDIT_OUT": "explicit/overrides_audit.md",
    }
    for env_name, path in explicit.items():
        monkeypatch.setenv(env_name, path)
    expected = {
        "provenance": explicit["PROVENANCE_OUT"],
        "provenance_diff": explicit["DIFF_OUT"],
        "snapshot_diff": explicit["DIFF_OUT"],
        "atwiki_quality": explicit["ATWIKI_QUALITY_OUT"],
        "audit_labels": explicit["AUDIT_LABELS_OUT"],
        "audit_index": explicit["AUDIT_INDEX_OUT"],
        "rollback_guard": explicit["ROLLBACK_GUARD_OUT"],
        "audit_official_overrides": explicit["OFFICIAL_OVERRIDES_AUDIT_OUT"],
    }

    assert (
        _collect_report_outputs(monkeypatch, tmp_path, expected["snapshot_diff"])
        == expected
    )
