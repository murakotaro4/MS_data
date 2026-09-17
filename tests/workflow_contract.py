"""GitHub Actions ワークフローの契約テスト用ヘルパー。

ワークフロー全文のスナップショットではなく「ステップ単位の必須/禁止部分文字列」
でピン留めする方針を各テストで共有する。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github/workflows"


def workflow_text(name: str) -> str:
    """`.github/workflows/<name>` の全文を返す。"""
    return (WORKFLOWS_DIR / name).read_text(encoding="utf-8")


def step_block(text: str, *, start: str, end: str) -> str:
    """`start` から（その後最初の）`end` 直前までのブロックを切り出す。"""
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def workflow_step(name: str, *, start: str, end: str) -> str:
    """ワークフロー名とマーカーからステップブロックを直接取り出す。"""
    return step_block(workflow_text(name), start=start, end=end)


def assert_contains(block: str, needles: Iterable[str]) -> None:
    missing = [needle for needle in needles if needle not in block]
    assert not missing, f"missing in workflow block: {missing}"


def assert_absent(block: str, needles: Iterable[str]) -> None:
    present = [needle for needle in needles if needle in block]
    assert not present, f"must not appear in workflow block: {present}"
