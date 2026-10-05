"""自動更新パイプラインが使う GitHub ラベル定義の SSOT と、冪等な作成 CLI。

ワークフロー内の `gh label create` 連打を置き換える。名前・説明・色は
ここだけで管理し、Issue 通知モジュールも同じ定義を参照する。
"""

from __future__ import annotations

import argparse
import os
import sys

from ms_data.gh.gh_json import run_gh
from ms_data.gh.issue_upsert import LabelSpec, ensure_labels

LABEL_SPECS: dict[str, LabelSpec] = {
    spec.name: spec
    for spec in (
        LabelSpec("data-update", "msData automated data update", "1D76DB"),
        LabelSpec("rollback-guard", "Includes rollback guard report", "D93F0B"),
        LabelSpec(
            "official-overrides", "Touches official override audit path", "5319E7"
        ),
        LabelSpec(
            "override-due", "official_overrides review/remove date reached", "B60205"
        ),
        LabelSpec("atwiki-quality", "Includes atwiki fetch quality report", "0E8A16"),
        LabelSpec(
            "pipeline-failure", "Automatic pipeline failure notification", "B60205"
        ),
    )
}

# 自動更新 PR に付与するラベル（data_update.yml の create-pull-request と同期）
DATA_UPDATE_PR_LABELS: tuple[str, ...] = (
    "data-update",
    "rollback-guard",
    "official-overrides",
    "atwiki-quality",
)


def specs_for(names: list[str]) -> list[LabelSpec]:
    """名前列からラベル定義を返す。未定義名は ValueError。"""

    unknown = [name for name in names if name not in LABEL_SPECS]
    if unknown:
        raise ValueError(f"unknown label(s): {', '.join(unknown)}")
    return [LABEL_SPECS[name] for name in names]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument(
        "labels",
        nargs="*",
        help="作成するラベル名（省略時は自動更新 PR 用ラベル一式）",
    )
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo または GITHUB_REPOSITORY が必要です")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    names = list(args.labels) or list(DATA_UPDATE_PR_LABELS)
    try:
        specs = specs_for(names)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    ensure_labels(args.repo, specs, runner=run_gh)
    for spec in specs:
        print(f"label ensured: {spec.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
