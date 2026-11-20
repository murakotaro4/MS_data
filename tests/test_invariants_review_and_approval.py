"""自動レビュー・CI承認ゲートの安全性不変条件（プロパティベーステスト）。"""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given
from hypothesis import strategies as st

from ms_data.gh.argtypes import GITHUB_ACTIONS_BOT
from ms_data.gh.auto_ci_approval import (
    EXTRA_DATA_FILES,
    _data_files_only,
    _trusted_pull,
)
from ms_data.gh.auto_review_gate import (
    CODEX_LOGINS,
    DISCONNECT_PREFIX,
    NO_ISSUES_PREFIX,
    evaluate,
)

_HEAD_SHA = "a" * 40
_OLD_SHA = "b" * 40
_SINCE = "2026-11-20T09:00:00Z"
_CODEX_LOGIN = st.sampled_from(sorted(CODEX_LOGINS))
_NON_CODEX_LOGIN = st.sampled_from(["murakotaro4", "github-actions[bot]", "reviewer"])
_ANY_LOGIN = st.one_of(_CODEX_LOGIN, _NON_CODEX_LOGIN)
_SHA = st.sampled_from([_HEAD_SHA, _OLD_SHA, "c" * 40])
_TIMESTAMP = st.sampled_from(
    ["2026-11-20T08:00:00Z", _SINCE, "2026-11-20T10:00:00Z", ""]
)


def _review_st():
    return st.fixed_dictionaries(
        {
            "user": st.fixed_dictionaries({"login": _ANY_LOGIN}),
            "commit_id": _SHA,
            "submitted_at": _TIMESTAMP,
        }
    )


def _file_comment_st():
    return st.fixed_dictionaries(
        {
            "id": st.integers(min_value=1, max_value=30),
            "user": st.fixed_dictionaries({"login": _ANY_LOGIN}),
            "commit_id": _SHA,
            "original_commit_id": st.one_of(st.none(), _SHA),
            "body": st.sampled_from(["P1 finding", "P2 finding", "note"]),
        }
    )


def _issue_comment_st():
    return st.fixed_dictionaries(
        {
            "id": st.integers(min_value=100, max_value=150),
            "user": st.fixed_dictionaries({"login": _ANY_LOGIN}),
            "created_at": _TIMESTAMP,
            "body": st.sampled_from(
                [
                    NO_ISSUES_PREFIX,
                    f"<!-- codex-review-receipt:v1 -->\n\n{NO_ISSUES_PREFIX}",
                    f"{DISCONNECT_PREFIX} please reconnect",
                    "generic comment",
                ]
            ),
        }
    )


def _reaction_st():
    return st.fixed_dictionaries(
        {
            "user": st.fixed_dictionaries({"login": _ANY_LOGIN}),
            "content": st.sampled_from(["+1", "eyes", "rocket"]),
        }
    )


@given(
    reviews=st.lists(_review_st(), max_size=6),
    file_comments=st.lists(_file_comment_st(), max_size=8),
    issue_comments=st.lists(_issue_comment_st(), max_size=6),
    reactions=st.lists(_reaction_st(), max_size=6),
    resolved_ids=st.sets(st.integers(min_value=1, max_value=30).map(str), max_size=10),
)
def test_review_gate_safety_and_consistency_invariants(
    reviews, file_comments, issue_comments, reactions, resolved_ids
):
    result = evaluate(
        reviews=reviews,
        file_comments=file_comments,
        issue_comments=issue_comments,
        reactions=reactions,
        head_sha=_HEAD_SHA,
        since=_SINCE,
        resolved_comment_ids=resolved_ids,
    )

    assert result["stop_reason"] in {"none", "findings", "disconnected", "no_response"}
    assert result["merge_ok"] is (result["stop_reason"] == "none")

    # 安全性: 未解決の現 HEAD 指摘が1件でもあれば絶対にマージ不可
    has_unresolved_current_finding = any(
        c["user"]["login"] in CODEX_LOGINS
        and c["commit_id"] == _HEAD_SHA
        and str(c["id"]) not in resolved_ids
        and (
            not isinstance(c["original_commit_id"], str)
            or not c["original_commit_id"]
            or c["original_commit_id"] == _HEAD_SHA
        )
        for c in file_comments
    )
    if has_unresolved_current_finding:
        assert result["merge_ok"] is False
        assert result["stop_reason"] == "findings"
        assert result["review_complete"] is True

    # 終端シグナル必須性: merge_ok=True なら必ず終端シグナルあり・指摘 0・完了済み
    if result["merge_ok"]:
        assert result["terminal_count"] > 0
        assert result["finding_count"] == 0
        assert result["review_complete"] is True

    # 持ち越し指摘のみのときは現 HEAD 終端シグナルを待つ（単独では完了しない）
    if (
        result["carried_finding_count"] > 0
        and result["terminal_count"] == 0
        and not has_unresolved_current_finding
    ):
        assert result["merge_ok"] is False
        assert result["review_complete"] is False
        assert result["stop_reason"] == "findings"


@given(
    reviews=st.lists(_review_st(), max_size=5),
    file_comments=st.lists(_file_comment_st(), max_size=5),
    issue_comments=st.lists(_issue_comment_st(), max_size=5),
    extra_non_codex_login=_NON_CODEX_LOGIN,
)
def test_review_gate_is_invariant_to_non_codex_activity(
    reviews, file_comments, issue_comments, extra_non_codex_login
):
    base = evaluate(
        reviews=reviews,
        file_comments=file_comments,
        issue_comments=issue_comments,
        reactions=[],
        head_sha=_HEAD_SHA,
        since=_SINCE,
    )
    with_noise = evaluate(
        reviews=reviews
        + [{"user": {"login": extra_non_codex_login}, "commit_id": _HEAD_SHA}],
        file_comments=file_comments
        + [
            {
                "id": 999,
                "user": {"login": extra_non_codex_login},
                "commit_id": _HEAD_SHA,
                "original_commit_id": _HEAD_SHA,
                "body": "human comment",
            }
        ],
        issue_comments=issue_comments
        + [
            {
                "id": 998,
                "user": {"login": extra_non_codex_login},
                "created_at": "2026-11-20T10:00:00Z",
                "body": NO_ISSUES_PREFIX,
            }
        ],
        reactions=[{"user": {"login": extra_non_codex_login}, "content": "+1"}],
        head_sha=_HEAD_SHA,
        since=_SINCE,
    )
    assert with_noise == base


@given(
    day_offset=st.integers(min_value=0, max_value=365),
    extra_files=st.lists(
        st.sampled_from(
            sorted(EXTRA_DATA_FILES)
            + [
                "ms_data/tasks.py",
                ".github/workflows/ci.yml",
                "tests/test_invariants_review_and_approval.py",
                "AGENTS.md",
                "data/other.json",
            ]
        ),
        max_size=5,
    ),
    statuses=st.lists(
        st.sampled_from(["added", "modified", "removed", "renamed"]),
        min_size=1,
        max_size=6,
    ),
    include_msdata=st.booleans(),
)
def test_ci_approval_data_files_only_safety_invariants(
    day_offset, extra_files, statuses, include_msdata
):
    d = (date(2026, 1, 1) + timedelta(days=day_offset)).strftime("%Y%m%d")
    names = (["msData.json"] if include_msdata else []) + extra_files
    files = [
        {"filename": name, "status": statuses[i % len(statuses)]}
        for i, name in enumerate(names)
    ]

    approved = _data_files_only(files, d)

    # msData.json が無ければ絶対に不可
    if not include_msdata:
        assert approved is False
    # 1件でも削除・リネームがあれば絶対に不可
    if any(f["status"] not in {"added", "modified"} for f in files):
        assert approved is False
    # 1件でも許可外パスがあれば絶対に不可
    allowed_base = {"msData.json"} | set(EXTRA_DATA_FILES)
    if any(f["filename"] not in allowed_base for f in files):
        assert approved is False


@given(
    state=st.sampled_from(["open", "closed"]),
    draft=st.booleans(),
    login=st.sampled_from([GITHUB_ACTIONS_BOT, "murakotaro4", "other-bot"]),
    base=st.sampled_from(["main", "develop"]),
    head_repo=st.sampled_from(["owner/repo", "fork/repo"]),
    ref_matches=st.booleans(),
    sha_matches=st.booleans(),
)
def test_trusted_pull_requires_all_security_conditions(
    state, draft, login, base, head_repo, ref_matches, sha_matches
):
    repo = "owner/repo"
    ref = "data/auto-update-20261120"
    sha = _HEAD_SHA
    pull = {
        "state": state,
        "draft": draft,
        "user": {"login": login},
        "base": {"ref": base},
        "head": {
            "ref": ref if ref_matches else "feature/other",
            "sha": sha if sha_matches else _OLD_SHA,
            "repo": {"full_name": head_repo},
        },
    }
    expected = (
        state == "open"
        and draft is False
        and login == GITHUB_ACTIONS_BOT
        and base == "main"
        and head_repo == repo
        and ref_matches
        and sha_matches
    )
    assert _trusted_pull(pull, repo, ref, sha) is expected
