"""post_merge_notify workflow の成果物パスを解決する。"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


HEAD_REF_RE = re.compile(r"^data/auto-update-(\d{8})$")
SOURCE_RUN_RE = re.compile(r"source_run_id[:=\s]*([0-9]+)")


@dataclass(frozen=True)
class PostMergeAssets:
    report_date: str
    source_run_id: str
    report_path: str
    provenance_path: str
    rollback_guard_path: str
    official_overrides_audit_path: str
    artifact_name: str
    snapshot_file: str
    release_tag: str
    snapshot_asset_path: str
    provenance_asset_path: str
    report_asset_path: str
    rollback_guard_asset_path: str
    official_overrides_audit_asset_path: str


def resolve_source_run_id(source_run_id_input: str, pr_body: str) -> str:
    if source_run_id_input.strip():
        return source_run_id_input.strip()
    match = SOURCE_RUN_RE.search(pr_body)
    if not match:
        raise ValueError(
            "source_run_id を解決できません。PR本文または workflow_dispatch 入力に指定してください。"
        )
    return match.group(1)


def resolve_assets(
    *,
    head_ref: str,
    source_run_id_input: str,
    pr_body: str,
    root: Path = Path("."),
    release_assets_dir: str = "release_assets",
    require_files: bool = False,
) -> PostMergeAssets:
    match = HEAD_REF_RE.match(head_ref)
    if not match:
        raise ValueError(f"head_ref から report_date を解決できません: {head_ref}")
    report_date = match.group(1)
    source_run_id = resolve_source_run_id(source_run_id_input, pr_body)
    report_path = f"reports/diff_msdata_{report_date}.md"
    provenance_path = f"reports/provenance_{report_date}.json"
    rollback_guard_path = f"reports/rollback_guard_{report_date}.md"
    official_overrides_audit_path = f"reports/official_overrides_audit_{report_date}.md"
    artifact_name = f"raw-snapshot-{report_date}-run-{source_run_id}"
    snapshot_file = f"raw_snapshot_{report_date}_run{source_run_id}.tar.xz"
    release_tag = f"raw-snapshot-{report_date}-run-{source_run_id}"
    snapshot_asset_path = f"{release_assets_dir}/{snapshot_file}"

    if require_files:
        for label, rel_path in (
            ("差分レポート", report_path),
            ("provenance", provenance_path),
        ):
            if not (root / rel_path).is_file():
                raise FileNotFoundError(f"{label}が見つかりません: {rel_path}")

    return PostMergeAssets(
        report_date=report_date,
        source_run_id=source_run_id,
        report_path=report_path,
        provenance_path=provenance_path,
        rollback_guard_path=rollback_guard_path,
        official_overrides_audit_path=official_overrides_audit_path,
        artifact_name=artifact_name,
        snapshot_file=snapshot_file,
        release_tag=release_tag,
        snapshot_asset_path=snapshot_asset_path,
        provenance_asset_path=provenance_path,
        report_asset_path=report_path,
        rollback_guard_asset_path=rollback_guard_path,
        official_overrides_audit_asset_path=official_overrides_audit_path,
    )


def write_github_output(path: Path, assets: PostMergeAssets) -> None:
    with path.open("a", encoding="utf-8") as f:
        for key, value in asdict(assets).items():
            f.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--pr-body", default="")
    parser.add_argument("--pr-body-env", default="")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--release-assets-dir", default="release_assets")
    parser.add_argument("--require-files", action="store_true")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args(argv)

    pr_body = args.pr_body
    if args.pr_body_env:
        pr_body = os.getenv(args.pr_body_env, "")

    assets = resolve_assets(
        head_ref=args.head_ref,
        source_run_id_input=args.source_run_id,
        pr_body=pr_body,
        root=args.root,
        release_assets_dir=args.release_assets_dir,
        require_files=args.require_files,
    )
    if args.github_output is not None:
        write_github_output(args.github_output, assets)
    else:
        print(json.dumps(asdict(assets), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
