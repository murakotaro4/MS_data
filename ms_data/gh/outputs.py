"""GitHub Actions の出力チャネル（GITHUB_OUTPUT / GITHUB_STEP_SUMMARY）への書き込み。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from collections.abc import Iterable


def write_github_output(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={'' if value is None else value}\n")


def append_step_summary(lines: Iterable[str], path: Path | None = None) -> None:
    summary_path = path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    target = Path(summary_path)
    with target.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(f"{line}\n")
