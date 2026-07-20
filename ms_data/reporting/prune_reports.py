"""reports_manifest.json の prune 設定に基づき、期限切れレポートを削除する。

- 対象: manifest の entries のうち `prune` を持つエントリの path_patterns
- ファイル名の `_YYYYMMDD` から日付を判定。日付を持たないファイルは対象外
- 新しい順に `keep_min` 件は期限に関係なく保持
- 既定は dry-run（計画の表示のみ）。実際に削除するには --apply を指定

使用例:
  uv run python -m ms_data.reporting.prune_reports --manifest reports_manifest.json
  uv run python -m ms_data.reporting.prune_reports --manifest reports_manifest.json --apply
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ms_data.core.dates import parse_yyyymmdd_jst, today_jst
from ms_data.core.json_io import load_json
from ms_data.gh.outputs import append_step_summary

REPORT_DATE_RE = re.compile(r"_(\d{8})\.[A-Za-z0-9.]+$")


@dataclass(frozen=True)
class PruneAction:
    entry_id: str
    path: Path
    report_date: str
    age_days: int
    action: str  # "delete" | "keep"
    reason: str


def extract_report_date(path: Path) -> str | None:
    match = REPORT_DATE_RE.search(path.name)
    return match.group(1) if match else None


def plan_prune_entry(
    entry: dict[str, Any],
    *,
    root: Path,
    today: str,
) -> list[PruneAction]:
    prune = entry.get("prune")
    if not isinstance(prune, dict):
        return []
    max_age_days = int(prune["max_age_days"])
    keep_min = int(prune.get("keep_min", 0))
    entry_id = str(entry.get("id", ""))
    today_dt = parse_yyyymmdd_jst(today)

    # 複数パターンに重複マッチしても1件として扱う（keep_min の二重消費と二重削除を防ぐ）
    seen: set[Path] = set()
    dated: list[tuple[str, Path]] = []
    for pattern in entry.get("path_patterns", []):
        for path in sorted(root.glob(str(pattern))):
            if path in seen:
                continue
            seen.add(path)
            report_date = extract_report_date(path)
            if report_date is None:
                continue
            dated.append((report_date, path))

    # 新しい順。keep_min 件は無条件で保持
    dated.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    actions: list[PruneAction] = []
    for index, (report_date, path) in enumerate(dated):
        age_days = (today_dt - parse_yyyymmdd_jst(report_date)).days
        if index < keep_min:
            action, reason = "keep", f"keep_min:{keep_min}"
        elif age_days > max_age_days:
            action, reason = (
                "delete",
                f"expired:{age_days}d>max_age_days:{max_age_days}",
            )
        else:
            action, reason = "keep", f"within:{max_age_days}d"
        actions.append(
            PruneAction(
                entry_id=entry_id,
                path=path,
                report_date=report_date,
                age_days=age_days,
                action=action,
                reason=reason,
            )
        )
    return actions


def plan_prune(
    manifest: dict[str, Any], *, root: Path, today: str
) -> list[PruneAction]:
    actions: list[PruneAction] = []
    for entry in manifest.get("entries", []):
        actions.extend(plan_prune_entry(entry, root=root, today=today))
    return actions


def render_summary(actions: list[PruneAction], *, applied: bool) -> str:
    deletes = [item for item in actions if item.action == "delete"]
    lines = [
        "### Reports Prune",
        f"- applied: {str(applied).lower()}",
        f"- scanned: {len(actions)}",
        f"- delete: {len(deletes)}",
        "",
        "| entry | path | report_date | age_days | reason |",
        "| --- | --- | --- | ---: | --- |",
    ]
    if not deletes:
        lines.append("| なし |  |  |  |  |")
    for item in deletes:
        lines.append(
            f"| {item.entry_id} | {item.path} | {item.report_date} | "
            f"{item.age_days} | {item.reason} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("reports_manifest.json"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--today", default=today_jst())
    parser.add_argument(
        "--apply",
        action="store_true",
        help="実際に削除する（指定しない場合は dry-run）",
    )
    parser.add_argument("--step-summary", type=Path, default=None)
    args = parser.parse_args(argv)

    manifest = load_json(args.manifest)
    actions = plan_prune(manifest, root=args.root, today=args.today)

    for item in actions:
        if item.action != "delete":
            continue
        prefix = "" if args.apply else "[dry-run] "
        print(f"{prefix}delete {item.path} ({item.entry_id}, {item.reason})")
        if args.apply:
            item.path.unlink()

    summary = render_summary(actions, applied=args.apply)
    print(summary, end="")
    if args.step_summary is not None:
        append_step_summary(summary.splitlines(), args.step_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
