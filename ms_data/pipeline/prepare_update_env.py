"""data update の Prepare 環境変数を生成する。

UPDATE_MODE の優先順位:

1. workflow_dispatch で force_full=true または mode=full なら ``full``。
2. workflow_dispatch で mode=revalidate なら ``revalidate``。
3. 日曜 schedule（cron ``0 9 * * 0``）は、第1日曜なら ``full``、
   それ以外なら ``revalidate``。
4. 上記以外は ``fast``。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ms_data.core.dates import parse_yyyymmdd_jst, today_jst
from ms_data.core.paths import reports_month_dir

SUNDAY_CRON = "0 9 * * 0"


def determine_update_mode(
    *,
    event_name: str,
    schedule_cron: str,
    input_mode: str,
    input_force_full: str,
    report_date: str,
) -> str:
    """現行 workflow と同じ優先順位で UPDATE_MODE を返す。"""
    if event_name == "workflow_dispatch":
        if input_force_full == "true" or input_mode == "full":
            return "full"
        if input_mode == "revalidate":
            return "revalidate"

    if event_name == "schedule" and schedule_cron == SUNDAY_CRON:
        return "full" if parse_yyyymmdd_jst(report_date).day <= 7 else "revalidate"

    return "fast"


def build_env(
    *,
    event_name: str,
    schedule_cron: str,
    input_mode: str,
    input_force_full: str,
    input_dry_run: str,
    run_id: str,
    report_date: str,
) -> dict[str, str]:
    """Prepare ステップが公開する15個の環境変数を構築する。"""
    update_mode = determine_update_mode(
        event_name=event_name,
        schedule_cron=schedule_cron,
        input_mode=input_mode,
        input_force_full=input_force_full,
        report_date=report_date,
    )
    month_dir = reports_month_dir(report_date)
    dry_run = str(event_name == "workflow_dispatch" and input_dry_run == "true").lower()

    return {
        "UPDATE_MODE": update_mode,
        "REPORT_DATE": report_date,
        "HEAD_REF": f"data/auto-update-{report_date}",
        "DRY_RUN": dry_run,
        "FULL_UPDATE": str(update_mode == "full").lower(),
        "REPORTS_MONTH_DIR": month_dir,
        "DIFF_FILE": f"{month_dir}/diff_msdata_{report_date}.md",
        "PROVENANCE_FILE": f"{month_dir}/provenance_{report_date}.json",
        "ROLLBACK_FILE": f"{month_dir}/rollback_guard_{report_date}.md",
        "OVERRIDES_AUDIT_FILE": (
            f"{month_dir}/official_overrides_audit_{report_date}.md"
        ),
        "QUALITY_FILE": f"{month_dir}/atwiki_quality_{report_date}.json",
        "FIELD_COMPLETENESS_FILE": (f"{month_dir}/field_completeness_{report_date}.md"),
        "RAW_ARTIFACT_NAME": f"raw-snapshot-{report_date}-run-{run_id}",
        "RAW_SNAPSHOT_FILE": f"raw_snapshot_{report_date}_run{run_id}.tar.xz",
        "RELEASE_TAG": f"raw-snapshot-{report_date}-run-{run_id}",
    }


def write_github_env(path: Path, values: dict[str, str]) -> None:
    """GitHub Actions の GITHUB_ENV ファイルへ key=value 形式で追記する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as github_env:
        for key, value in values.items():
            github_env.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--schedule-cron", required=True)
    parser.add_argument("--input-mode", required=True)
    parser.add_argument("--input-force-full", required=True)
    parser.add_argument("--input-dry-run", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    parser.add_argument("--today", help="JST の実行日 (YYYYMMDD)。省略時は現在日")
    args = parser.parse_args(argv)

    report_date = args.today or today_jst()
    parse_yyyymmdd_jst(report_date)
    values = build_env(
        event_name=args.event_name,
        schedule_cron=args.schedule_cron,
        input_mode=args.input_mode,
        input_force_full=args.input_force_full,
        input_dry_run=args.input_dry_run,
        run_id=args.run_id,
        report_date=report_date,
    )
    write_github_env(args.github_env, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
