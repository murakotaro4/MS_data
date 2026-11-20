"""自動レビュー〜CI承認〜マージの状態遷移モデル検証（Hypothesis ステートマシン）。

実コード（auto_review_gate.evaluate / auto_review_merge.merge_pull_request /
auto_ci_approval.approve_and_wait_ci）を仮想 GitHub 環境上でランダム遷移させ、
ゲート未達でのマージ・非信頼 PR への CI 承認・二重マージが絶対に起きないことを
全探索的に検証する。
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from hypothesis import event, settings
from hypothesis import strategies as st
from hypothesis.errors import InvalidArgument
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from ms_data.gh.argtypes import GITHUB_ACTIONS_BOT, ReviewDeps
from ms_data.gh.auto_review_gate import (
    DISCONNECT_PREFIX,
    NO_ISSUES_PREFIX,
    evaluate,
)
from ms_data.gh.auto_review_merge import merge_pull_request

_REPO = "owner/repo"
_PR_NUMBER = "97"
_HEAD_REF = "data/auto-update-20261120"
_CODEX_BOT = "chatgpt-codex-connector[bot]"
_BASE_TIME = datetime(2026, 11, 20, 9, 0, 0, tzinfo=timezone.utc)


class _SilentClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class AutoReviewMergeStateMachine(RuleBasedStateMachine):
    """PR ライフサイクル全体に対する自動レビュー・CI 承認・マージゲートの状態機械。"""

    def __init__(self) -> None:
        super().__init__()
        self.tick = 1
        self.pr_state = "OPEN"
        self.head_index = 1
        self.head_sha = self._make_sha(self.head_index)
        self.since = self._iso(self.tick)
        self.merge_commit_sha = ""

        self.reviews: list[dict[str, Any]] = []
        self.file_comments: list[dict[str, Any]] = []
        self.resolved_comment_ids: set[str] = set()
        self.issue_comments: list[dict[str, Any]] = []
        self.next_comment_id = 1

        self.ci_runs: list[dict[str, Any]] = []
        self.next_run_id = 100
        self.pr_files_trusted = True
        self.approval_result = "success"  # success / failure / action_required
        self.approval_denied = False

        # 監査カウンタ（不変条件の検証に使用）
        self.merge_api_calls = 0
        self.approved_while_untrusted = False
        self.merged_without_valid_gate = False
        self.last_merge_head_sha = ""

    @staticmethod
    def _make_sha(index: int) -> str:
        return f"{index:040x}"

    def _iso(self, tick: int) -> str:
        return (_BASE_TIME + timedelta(seconds=tick)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _next_iso(self) -> str:
        self.tick += 1
        return self._iso(self.tick)

    def _latest_ci_for_head(self) -> dict[str, Any] | None:
        candidates = [r for r in self.ci_runs if r["head_sha"] == self.head_sha]
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r["created_at"], r["id"]))

    def _make_deps(self) -> ReviewDeps:
        def runner(args: list[str]) -> str:
            if args[1:3] == ["pr", "view"]:
                return json.dumps(
                    {
                        "state": self.pr_state,
                        "headRefOid": self.head_sha,
                        "mergeCommit": (
                            {"oid": self.merge_commit_sha}
                            if self.pr_state == "MERGED"
                            else None
                        ),
                    }
                )
            if args[1:3] == ["pr", "merge"]:
                self.merge_api_calls += 1
                self.last_merge_head_sha = args[-1]
                # 実世界と同じく --match-head-commit が一致すればマージ確定
                assert args[-2] == "--match-head-commit"
                assert args[-1] == self.head_sha
                self.pr_state = "MERGED"
                self.merge_commit_sha = self._make_sha(9000 + self.merge_api_calls)
                return ""

            endpoint = args[2]
            if endpoint.endswith("/approve"):
                if not self.pr_files_trusted:
                    self.approved_while_untrusted = True
                if self.approval_denied:
                    raise subprocess.CalledProcessError(1, args, stderr="HTTP 403")
                run_id = int(endpoint.split("/")[-2])
                for run in self.ci_runs:
                    if run["id"] == run_id:
                        run["conclusion"] = self.approval_result
                        run["status"] = "completed"
                return ""

            if "/actions/workflows/ci.yml/runs?" in endpoint:
                if "head_sha=" in endpoint:
                    visible = [
                        self._public_run(r)
                        for r in self.ci_runs
                        if r["head_sha"] == self.head_sha and r["visible_in_filtered"]
                    ]
                    return json.dumps(visible)
                return json.dumps([self._public_run(r) for r in self.ci_runs])

            if endpoint.endswith(f"/pulls/{_PR_NUMBER}"):
                return json.dumps(
                    {
                        "state": self.pr_state.lower(),
                        "draft": False,
                        "user": {"login": GITHUB_ACTIONS_BOT},
                        "base": {"ref": "main"},
                        "head": {
                            "ref": _HEAD_REF,
                            "sha": self.head_sha,
                            "repo": {"full_name": _REPO},
                        },
                        "body": "<!-- source_run_id:50 -->",
                        "changed_files": 1,
                    }
                )

            if endpoint.endswith(f"/pulls/{_PR_NUMBER}/files"):
                filename = (
                    "msData.json" if self.pr_files_trusted else "ms_data/tasks.py"
                )
                return json.dumps([{"filename": filename, "status": "modified"}])

            if endpoint.endswith("/actions/runs/50"):
                return json.dumps(
                    {
                        "id": 50,
                        "path": ".github/workflows/data_update.yml",
                        "event": "schedule",
                        "head_branch": "main",
                        "status": "completed",
                        "conclusion": "success",
                        "repository": {"full_name": _REPO},
                    }
                )

            if endpoint.endswith("/jobs"):
                return json.dumps({"total_count": 0, "jobs": []})

            if "/actions/runs/" in endpoint:
                run_id = int(endpoint.rsplit("/", 1)[-1])
                for run in self.ci_runs:
                    if run["id"] == run_id:
                        return json.dumps(self._public_run(run))
                raise subprocess.CalledProcessError(1, args, stderr="HTTP 404")

            raise AssertionError(f"unexpected gh command: {args}")

        return replace(ReviewDeps.default(), clock=_SilentClock(), run_gh=runner)

    @staticmethod
    def _public_run(run: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in run.items() if k != "visible_in_filtered"}

    # --- 状態遷移ルール ---

    @rule()
    def push_new_commit(self) -> None:
        """新 HEAD を push。GitHub 仕様どおり未解決指摘の commit_id を新 HEAD へ持ち越す。"""
        if self.pr_state != "OPEN":
            return
        self.head_index += 1
        self.head_sha = self._make_sha(self.head_index)
        self.since = self._next_iso()
        for comment in self.file_comments:
            if str(comment["id"]) not in self.resolved_comment_ids:
                comment["commit_id"] = self.head_sha

    @rule()
    def codex_post_finding(self) -> None:
        if self.pr_state != "OPEN":
            return
        cid = self.next_comment_id
        self.next_comment_id += 1
        self.file_comments.append(
            {
                "id": cid,
                "user": {"login": _CODEX_BOT},
                "commit_id": self.head_sha,
                "original_commit_id": self.head_sha,
                "body": f"P1 finding #{cid}",
            }
        )

    @rule()
    def resolve_oldest_finding(self) -> None:
        for comment in self.file_comments:
            cid = str(comment["id"])
            if cid not in self.resolved_comment_ids:
                self.resolved_comment_ids.add(cid)
                break

    @rule()
    def codex_post_no_issue(self) -> None:
        if self.pr_state != "OPEN":
            return
        self.issue_comments.append(
            {
                "id": self.next_comment_id,
                "user": {"login": _CODEX_BOT},
                "created_at": self._next_iso(),
                "body": f"<!-- codex-review-receipt:v1 -->\n\n{NO_ISSUES_PREFIX}",
            }
        )
        self.next_comment_id += 1

    @rule()
    def codex_post_review(self) -> None:
        if self.pr_state != "OPEN":
            return
        self.reviews.append(
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self.head_sha,
                "submitted_at": self._next_iso(),
            }
        )

    @rule()
    def codex_post_disconnect(self) -> None:
        if self.pr_state != "OPEN":
            return
        self.issue_comments.append(
            {
                "id": self.next_comment_id,
                "user": {"login": _CODEX_BOT},
                "created_at": self._next_iso(),
                "body": f"{DISCONNECT_PREFIX} please reconnect",
            }
        )
        self.next_comment_id += 1

    @rule(
        status=st.sampled_from(["in_progress", "completed"]),
        conclusion=st.sampled_from(["success", "failure", "action_required"]),
        visible_in_filtered=st.booleans(),
    )
    def ci_event_for_head(
        self, status: str, conclusion: str, visible_in_filtered: bool
    ) -> None:
        if self.pr_state != "OPEN":
            return
        run_id = self.next_run_id
        self.next_run_id += 1
        # GitHub API の実測（Issue #411）に合わせて、絞り込み一覧から欠落し得るのは
        # 同一 HEAD の実行承認待ち（completed / action_required）run が初回で出るときのみとする。
        is_action_required = status == "completed" and conclusion == "action_required"
        has_visible_run_for_head = any(
            r["head_sha"] == self.head_sha and r["visible_in_filtered"]
            for r in self.ci_runs
        )
        effective_visible = (
            visible_in_filtered
            if (is_action_required and not has_visible_run_for_head)
            else True
        )
        self.ci_runs.append(
            {
                "id": run_id,
                "created_at": self._next_iso(),
                "event": "pull_request",
                "head_sha": self.head_sha,
                "head_branch": _HEAD_REF,
                "path": ".github/workflows/ci.yml",
                "status": status,
                "conclusion": conclusion if status == "completed" else None,
                "actor": {"login": GITHUB_ACTIONS_BOT},
                "repository": {"full_name": _REPO},
                "head_repository": {"full_name": _REPO},
                "visible_in_filtered": effective_visible,
            }
        )

    @rule(
        trusted=st.booleans(),
        approval_result=st.sampled_from(["success", "failure", "action_required"]),
        approval_denied=st.booleans(),
    )
    def configure_ci_approval_env(
        self, trusted: bool, approval_result: str, approval_denied: bool
    ) -> None:
        if self.pr_state != "OPEN":
            return
        self.pr_files_trusted = trusted
        self.approval_result = approval_result
        self.approval_denied = approval_denied

    @rule()
    def close_pr(self) -> None:
        if self.pr_state == "OPEN":
            self.pr_state = "CLOSED"

    @staticmethod
    def _record_event(name: str) -> None:
        with contextlib.suppress(InvalidArgument):
            event(name)

    @rule()
    def attempt_auto_merge(self) -> None:
        """実ゲート（evaluate -> merge_pull_request）を実行し安全性を検証する。"""
        was_state = self.pr_state
        evaluated_sha = self.head_sha
        metrics = evaluate(
            reviews=self.reviews,
            file_comments=self.file_comments,
            issue_comments=self.issue_comments,
            reactions=[],
            head_sha=evaluated_sha,
            since=self.since,
            resolved_comment_ids=self.resolved_comment_ids,
        )
        if not metrics["merge_ok"]:
            self._record_event(f"gate_stopped:{metrics['stop_reason']}")
            return

        before_merges = self.merge_api_calls
        result = merge_pull_request(
            repo=_REPO,
            pr_number=_PR_NUMBER,
            head_ref=_HEAD_REF,
            head_sha=evaluated_sha,
            deps=self._make_deps(),
        )
        if result.merged:
            self._record_event(f"merge_ok:{result.skip_reason or 'fresh'}")
        else:
            self._record_event(f"merge_blocked:{result.skip_reason}")

        # 新規マージが成立した瞬間の厳格な事後条件
        if self.merge_api_calls > before_merges:
            latest_ci = self._latest_ci_for_head()
            ci_ok = (
                latest_ci is not None
                and latest_ci["status"] == "completed"
                and latest_ci["conclusion"] == "success"
            )
            if was_state != "OPEN" or not ci_ok or not result.merged:
                self.merged_without_valid_gate = True

    # --- 全状態で常に成り立つべき不変条件 ---

    @invariant()
    def never_approves_untrusted_pr(self) -> None:
        assert not self.approved_while_untrusted

    @invariant()
    def never_merges_without_valid_gate(self) -> None:
        assert not self.merged_without_valid_gate

    @invariant()
    def never_double_merges(self) -> None:
        assert self.merge_api_calls <= 1
        if self.merge_api_calls == 1:
            assert self.pr_state == "MERGED"
            assert self.last_merge_head_sha == self.head_sha


TestAutoReviewMergeStateMachine = AutoReviewMergeStateMachine.TestCase
TestAutoReviewMergeStateMachine.settings = settings(
    max_examples=150,
    stateful_step_count=25,
    deadline=None,
)


def test_state_machine_liveness_reaches_approval_and_merge_paths() -> None:
    """安全性だけでなく、正当な経路（絞り込み非表示の承認待ち CI → 自動承認 → マージ）が到達可能であることを確認。"""
    sm = AutoReviewMergeStateMachine()
    try:
        # 1. 旧 HEAD で指摘を出したまま新 HEAD を push（持ち越し指摘が発生）
        sm.codex_post_finding()
        sm.push_new_commit()
        # 2. 新 HEAD に絞り込み非表示の action_required CI を発生させる（PR #410 相当）
        sm.ci_event_for_head(
            status="completed", conclusion="action_required", visible_in_filtered=False
        )
        # 3. まだ現 HEAD の終端シグナルが無いのでマージ不可
        sm.attempt_auto_merge()
        assert sm.pr_state == "OPEN"
        assert sm.merge_api_calls == 0

        # 4. 非信頼 PR のまま終端シグナルが出ても承認・マージは拒否される
        sm.configure_ci_approval_env(
            trusted=False, approval_result="success", approval_denied=False
        )
        sm.codex_post_no_issue()
        sm.attempt_auto_merge()
        assert sm.pr_state == "OPEN"
        assert sm.approved_while_untrusted is False
        assert sm.merge_api_calls == 0

        # 5. 信頼済み PR であれば自動承認 → CI 成功 → マージまで到達する
        sm.configure_ci_approval_env(
            trusted=True, approval_result="success", approval_denied=False
        )
        sm.attempt_auto_merge()
        assert sm.pr_state == "MERGED"
        assert sm.merge_api_calls == 1

        # 6. マージ後に再度試行しても二重マージされない
        sm.attempt_auto_merge()
        assert sm.merge_api_calls == 1
    finally:
        sm.teardown()
