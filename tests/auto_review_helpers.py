"""auto_review_merge の cmd_* テストが共有する定数・スタブ・main ラッパー。

各 test_auto_review_*_commands.py から import する（pytest が tests/ を
sys.path に載せる前提。conftest の fake_gh / fake_time fixture と併用）。
"""

from dataclasses import replace

from ms_data.gh.auto_review_merge import ReviewDeps, main

CODEX_BOT = "chatgpt-codex-connector[bot]"
HEAD_SHA = "abc123"
PAT_LOGIN = "codex-trigger-user"
BASELINE = "2026-05-31T09:10:00Z"


def run_main(argv, fake_gh=None, fake_time=None, **changes):
    """ReviewDeps を差し替えて auto_review_merge.main を実行する。"""
    deps = ReviewDeps.default()
    if fake_gh is not None:
        deps = replace(deps, client=lambda _: fake_gh)
    if fake_time is not None:
        deps = replace(deps, clock=fake_time)
    if changes:
        deps = replace(deps, **changes)
    return main(argv, deps_factory=lambda: deps)


def codex_review(commit_id: str = HEAD_SHA) -> dict:
    return {"user": {"login": CODEX_BOT}, "commit_id": commit_id}


def codex_finding(commit_id: str = HEAD_SHA) -> dict:
    return {
        "user": {"login": CODEX_BOT},
        "commit_id": commit_id,
        "path": "msData.json",
        "line": 12,
        "body": "ここにバグがあります",
    }


def metrics(**overrides) -> dict:
    base = {
        "review_count": 0,
        "finding_count": 0,
        "reaction_count": 0,
        "issue_comment_count": 0,
        "no_issue_comment_count": 0,
        "disconnect_count": 0,
        "terminal_count": 0,
        "review_complete": False,
        "merge_ok": False,
        "stop_reason": "no_response",
    }
    base.update(overrides)
    return base


def script_metrics(script: list[dict]):
    """collect_review_metrics を呼び出し回数で返値を切り替えるスタブに差し替える。"""
    calls: list[dict] = []

    def fake(**kwargs):
        index = min(len(calls), len(script) - 1)
        calls.append(kwargs)
        return script[index]

    return calls, fake
