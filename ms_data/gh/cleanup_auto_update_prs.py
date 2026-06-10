"""古い data/auto-update-* PR を整理する。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


HEAD_REF_RE = re.compile(r"^data/auto-update-(\d{8})$")
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class CleanupAction:
    number: int
    head_ref: str
    report_date: str
    age_days: int
    action: str
    reason: str


def today_jst() -> str:
    return datetime.now(JST).strftime("%Y%m%d")


def parse_report_date(head_ref: str) -> str | None:
    match = HEAD_REF_RE.match(head_ref)
    return match.group(1) if match else None


def _date_value(yyyymmdd: str) -> datetime:
    return datetime.strptime(yyyymmdd, "%Y%m%d").replace(tzinfo=JST)


def plan_cleanup(
    pulls: list[dict[str, Any]],
    *,
    today: str,
    keep_days: int,
) -> list[CleanupAction]:
    today_dt = _date_value(today)
    actions: list[CleanupAction] = []

    for item in pulls:
        head = item.get("head") if isinstance(item.get("head"), dict) else {}
        head_ref = str(head.get("ref") or "")
        report_date = parse_report_date(head_ref)
        if report_date is None:
            continue

        age_days = (today_dt - _date_value(report_date)).days
        number = int(item.get("number") or 0)
        if report_date == today:
            action = "keep"
            reason = "today"
        elif age_days <= keep_days:
            action = "keep"
            reason = f"within_keep_days:{keep_days}"
        else:
            action = "close"
            reason = f"stale_open_pr:{age_days}d"
        actions.append(
            CleanupAction(
                number=number,
                head_ref=head_ref,
                report_date=report_date,
                age_days=age_days,
                action=action,
                reason=reason,
            )
        )
    return sorted(actions, key=lambda item: (item.report_date, item.number))


def _run(cmd: list[str]) -> str:
    result = subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _gh_json(endpoint: str) -> Any:
    text = _run(["gh", "api", endpoint])
    return json.loads(text) if text.strip() else []


def fetch_open_pulls(repo: str) -> list[dict[str, Any]]:
    data = _gh_json(f"repos/{repo}/pulls?state=open&base=main&per_page=100")
    if not isinstance(data, list):
        raise ValueError("GitHub pulls response must be a list")
    return data


def close_pr(repo: str, action: CleanupAction) -> None:
    message = (
        "古い自動更新PRを整理します。\n\n"
        f"- head_ref: {action.head_ref}\n"
        f"- report_date: {action.report_date}\n"
        f"- reason: {action.reason}\n\n"
        f"<!-- auto-update-cleanup reason:{action.reason} head_ref:{action.head_ref} -->"
    )
    _run(
        [
            "gh",
            "pr",
            "close",
            str(action.number),
            "--repo",
            repo,
            "--comment",
            message,
            "--delete-branch",
        ]
    )


def render_summary(actions: list[CleanupAction], *, dry_run: bool) -> str:
    close_count = sum(1 for item in actions if item.action == "close")
    keep_count = sum(1 for item in actions if item.action == "keep")
    lines = [
        "### Auto Update PR Cleanup",
        f"- dry_run: {str(dry_run).lower()}",
        f"- keep: {keep_count}",
        f"- close: {close_count}",
        "",
        "| PR | head_ref | report_date | age_days | action | reason |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    if not actions:
        lines.append("| なし |  |  |  |  |  |")
    for item in actions:
        lines.append(
            f"| #{item.number} | {item.head_ref} | {item.report_date} | "
            f"{item.age_days} | {item.action} | {item.reason} |"
        )
    return "\n".join(lines) + "\n"


def write_step_summary(text: str, path: Path | None = None) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--today", default=today_jst())
    parser.add_argument("--keep-days", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--step-summary", type=Path, default=None)
    args = parser.parse_args(argv)

    pulls = fetch_open_pulls(args.repo)
    actions = plan_cleanup(pulls, today=args.today, keep_days=args.keep_days)
    for action in actions:
        if action.action == "close":
            print(
                f"{'[dry-run] ' if args.dry_run else ''}"
                f"close PR #{action.number} {action.head_ref}: {action.reason}"
            )
            if not args.dry_run:
                close_pr(args.repo, action)
        else:
            print(f"keep PR #{action.number} {action.head_ref}: {action.reason}")

    summary = render_summary(actions, dry_run=args.dry_run)
    print(summary, end="")
    write_step_summary(summary, args.step_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
