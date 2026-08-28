from pathlib import Path

import pytest

from ms_data.pipeline import prepare_update_env


@pytest.mark.parametrize(
    ("event_name", "schedule_cron", "input_mode", "force_full", "today", "expected"),
    [
        ("workflow_dispatch", "", "auto", "true", "20260829", "full"),
        ("workflow_dispatch", "", "full", "true", "20260829", "full"),
        ("workflow_dispatch", "", "revalidate", "true", "20260829", "full"),
        ("workflow_dispatch", "", "full", "false", "20260829", "full"),
        (
            "workflow_dispatch",
            "",
            "revalidate",
            "false",
            "20260829",
            "revalidate",
        ),
        ("workflow_dispatch", "", "auto", "false", "20260829", "fast"),
        ("schedule", prepare_update_env.SUNDAY_CRON, "", "", "20260802", "full"),
        (
            "schedule",
            prepare_update_env.SUNDAY_CRON,
            "",
            "",
            "20260809",
            "revalidate",
        ),
        ("schedule", "0 9 * * 1-6", "", "", "20260803", "fast"),
        ("push", "", "", "", "20260829", "fast"),
    ],
)
def test_update_mode_priority(
    event_name: str,
    schedule_cron: str,
    input_mode: str,
    force_full: str,
    today: str,
    expected: str,
):
    assert (
        prepare_update_env.determine_update_mode(
            event_name=event_name,
            schedule_cron=schedule_cron,
            input_mode=input_mode,
            input_force_full=force_full,
            report_date=today,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        ("20260301", "full"),  # 月初が日曜
        ("20260308", "revalidate"),
        ("20260802", "full"),  # 月初が日曜以外
        ("20260830", "revalidate"),
        ("20260906", "full"),  # 月替わりで第1日曜へ戻る
        ("20260913", "revalidate"),
    ],
)
def test_first_sunday_boundaries(today: str, expected: str):
    assert (
        prepare_update_env.determine_update_mode(
            event_name="schedule",
            schedule_cron=prepare_update_env.SUNDAY_CRON,
            input_mode="",
            input_force_full="",
            report_date=today,
        )
        == expected
    )


def test_build_env_has_exact_compatible_keys_and_values():
    values = prepare_update_env.build_env(
        event_name="workflow_dispatch",
        schedule_cron="",
        input_mode="full",
        input_force_full="false",
        input_dry_run="true",
        run_id="12345",
        report_date="20260829",
    )

    assert values == {
        "UPDATE_MODE": "full",
        "REPORT_DATE": "20260829",
        "HEAD_REF": "data/auto-update-20260829",
        "DRY_RUN": "true",
        "FULL_UPDATE": "true",
        "REPORTS_MONTH_DIR": "reports/2026/08",
        "DIFF_FILE": "reports/2026/08/diff_msdata_20260829.md",
        "PROVENANCE_FILE": "reports/2026/08/provenance_20260829.json",
        "ROLLBACK_FILE": "reports/2026/08/rollback_guard_20260829.md",
        "OVERRIDES_AUDIT_FILE": (
            "reports/2026/08/official_overrides_audit_20260829.md"
        ),
        "QUALITY_FILE": "reports/2026/08/atwiki_quality_20260829.json",
        "FIELD_COMPLETENESS_FILE": ("reports/2026/08/field_completeness_20260829.md"),
        "RAW_ARTIFACT_NAME": "raw-snapshot-20260829-run-12345",
        "RAW_SNAPSHOT_FILE": "raw_snapshot_20260829_run12345.tar.xz",
        "RELEASE_TAG": "raw-snapshot-20260829-run-12345",
    }
    assert len(values) == 15


def test_main_writes_github_env_with_injected_today(tmp_path: Path):
    github_env = tmp_path / "github-env"

    code = prepare_update_env.main(
        [
            "--event-name",
            "schedule",
            "--schedule-cron",
            prepare_update_env.SUNDAY_CRON,
            "--input-mode",
            "",
            "--input-force-full",
            "",
            "--input-dry-run",
            "",
            "--run-id",
            "987",
            "--github-env",
            str(github_env),
            "--today",
            "20260906",
        ]
    )

    assert code == 0
    lines = github_env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "UPDATE_MODE=full"
    assert "REPORT_DATE=20260906" in lines
    assert "RAW_SNAPSHOT_FILE=raw_snapshot_20260906_run987.tar.xz" in lines
    assert len(lines) == 15


def test_dry_run_is_only_enabled_for_workflow_dispatch():
    scheduled = prepare_update_env.build_env(
        event_name="schedule",
        schedule_cron=prepare_update_env.SUNDAY_CRON,
        input_mode="",
        input_force_full="",
        input_dry_run="true",
        run_id="1",
        report_date="20260802",
    )

    assert scheduled["DRY_RUN"] == "false"


def test_data_update_prepare_uses_module_without_legacy_bash():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/data_update.yml"
    ).read_text(encoding="utf-8")
    start = workflow.index("      - name: Prepare\n")
    end = workflow.index("\n      - name: Validate report contract", start)
    block = workflow[start:end]

    assert "uv run python -m ms_data.pipeline.prepare_update_env" in block
    assert '--event-name "${{ github.event_name }}"' in block
    assert '--schedule-cron "${{ github.event.schedule }}"' in block
    assert '--run-id "${{ github.run_id }}"' in block
    assert '--github-env "$GITHUB_ENV"' in block
    assert "date +%Y%m%d" not in block
    assert "update_mode=" not in block
    assert 'echo "UPDATE_MODE=' not in block
