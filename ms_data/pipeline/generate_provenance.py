#!/usr/bin/env python3
"""
msData 更新時の生成元証跡（provenance）を JSON で出力する。

例:
  uv run python -m ms_data.pipeline.generate_provenance \
    --date 20260221 \
    --index cache/index.json \
    --details-jsonl cache/details.jsonl \
    --details-json cache/details.json \
    --msdata msData.json \
    --diff reports/2026/02/diff_msdata_20260221.md \
    --html-dir cache/html \
    --out reports/2026/02/provenance_20260221.json \
    --ttl 7d --rate 1.0 --limit 0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_dir(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(path).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with p.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()


def count_json_records(path: Path) -> int:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return 1
    raise ValueError(f"Unsupported JSON type in {path}: {type(data).__name__}")


def count_jsonl_records(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def file_entry(path: Path, record_count: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
    if record_count is not None:
        out["record_count"] = record_count
    return out


def dir_entry(path: Path) -> dict[str, Any]:
    file_count = 0
    total_bytes = 0
    for p in path.rglob("*"):
        if p.is_file():
            file_count += 1
            total_bytes += p.stat().st_size
    return {
        "path": str(path),
        "sha256": sha256_dir(path),
        "file_count": file_count,
        "size_bytes": total_bytes,
    }


def require_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} が見つかりません: {path}")


def build_provenance(args: argparse.Namespace) -> dict[str, Any]:
    index_path = Path(args.index)
    details_jsonl_path = Path(args.details_jsonl)
    details_json_path = Path(args.details_json)
    msdata_path = Path(args.msdata)
    diff_path = Path(args.diff)
    html_dir = Path(args.html_dir)

    require_exists(index_path, "index")
    require_exists(details_jsonl_path, "details.jsonl")
    require_exists(details_json_path, "details.json")
    require_exists(msdata_path, "msData.json")
    require_exists(diff_path, "diff report")
    require_exists(html_dir, "cache/html")
    if not html_dir.is_dir():
        raise NotADirectoryError(f"cache/html がディレクトリではありません: {html_dir}")

    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "")
    workflow = os.getenv("GITHUB_WORKFLOW", "")
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    ref_name = os.getenv("GITHUB_REF_NAME", os.getenv("GITHUB_REF", ""))
    head_sha = os.getenv("GITHUB_SHA", "")

    artifact_name = (
        args.artifact_name
        if args.artifact_name
        else f"raw-snapshot-{args.date}-run-{run_id}"
    )
    release_tag = (
        args.release_tag
        if args.release_tag
        else f"raw-snapshot-{args.date}-run-{run_id}"
    )
    release_asset_name = (
        args.release_asset_name
        if args.release_asset_name
        else f"raw_snapshot_{args.date}_run{run_id}.tar.xz"
    )
    release_url = (
        f"https://github.com/{repo}/releases/tag/{release_tag}" if repo else ""
    )

    return {
        "schema_version": "1",
        "generated_at": now_iso(),
        "report_date": args.date,
        "git": {
            "repo": repo,
            "branch": ref_name,
            "head_sha": head_sha,
        },
        "github": {
            "run_id": run_id,
            "run_attempt": run_attempt,
            "workflow": workflow,
            "event_name": event_name,
        },
        "params": {
            "ttl": args.ttl,
            "rate": args.rate,
            "limit": args.limit,
        },
        "inputs": {
            "index": file_entry(index_path, count_json_records(index_path)),
            "details_jsonl": file_entry(
                details_jsonl_path, count_jsonl_records(details_jsonl_path)
            ),
            "details_json": file_entry(
                details_json_path, count_json_records(details_json_path)
            ),
            "html_cache": dir_entry(html_dir),
        },
        "outputs": {
            "msdata_json": file_entry(msdata_path, count_json_records(msdata_path)),
            "diff_report": file_entry(diff_path),
        },
        "artifact": {
            "name": artifact_name,
            "retention_days": args.artifact_retention_days,
        },
        "release": {
            "tag": release_tag,
            "asset_name": release_asset_name,
            "url": release_url,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True, help="レポート日付（YYYYMMDD）")
    ap.add_argument("--index", default="cache/index.json")
    ap.add_argument("--details-jsonl", default="cache/details.jsonl")
    ap.add_argument("--details-json", default="cache/details.json")
    ap.add_argument("--msdata", default="msData.json")
    ap.add_argument("--diff", required=True)
    ap.add_argument("--html-dir", default="cache/html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ttl", default="")
    ap.add_argument("--rate", default="")
    ap.add_argument("--limit", default="")
    ap.add_argument("--artifact-name", default="")
    ap.add_argument("--artifact-retention-days", type=int, default=90)
    ap.add_argument("--release-tag", default="")
    ap.add_argument("--release-asset-name", default="")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_path = Path(args.out)
    try:
        provenance = build_provenance(args)
    except Exception as e:
        print(f"Error: provenance 生成に失敗: {e}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(provenance, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"provenance written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
