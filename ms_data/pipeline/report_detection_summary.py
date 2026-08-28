"""変更検出メタデータを GitHub Actions の出力へ転記する。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ms_data.gh.outputs import append_step_summary, write_github_output


def _load_meta(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"meta file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON in meta file {path}: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})"
        ) from None
    if not isinstance(data, dict):
        raise ValueError(f"meta file must contain a JSON object: {path}")
    return data


def _outputs(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_count": int(meta.get("candidate_count", 0)),
        "fast_path": str(bool(meta.get("fast_path", False))).lower(),
        "age_coverage": meta.get("age_coverage", 0.0),
        "fallback_reason": meta.get("fallback_reason") or "none",
    }


def _summary_lines(meta: dict[str, Any], update_mode: str) -> list[str]:
    outputs = _outputs(meta)
    return [
        "### Change Detection",
        f"- update_mode: {update_mode}",
        f"- mode: {meta.get('mode') or 'fast'}",
        f"- candidate_count: {outputs['candidate_count']}",
        f"- fast_path: {outputs['fast_path']}",
        f"- age_coverage: {outputs['age_coverage']}",
        f"- fallback_reason: {outputs['fallback_reason']}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--update-mode", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--step-summary", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        meta = _load_meta(args.meta)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    write_github_output(args.github_output, _outputs(meta))
    append_step_summary(_summary_lines(meta, args.update_mode), args.step_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
