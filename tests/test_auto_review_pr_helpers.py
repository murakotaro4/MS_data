"""auto_review_pr の純関数ヘルパー（日時・GraphQL ページング・再開候補選定）の異常系テスト。"""

import pytest

from ms_data.gh import auto_review_pr as mod
from ms_data.gh.auto_review_markers import stop_marker

SHA = "a" * 40


def test_later_iso8601_returns_latest_and_falls_back_to_text():
    assert mod.later_iso8601("2026-05-31T01:00:00Z", "2026-05-31T02:00:00Z") == (
        "2026-05-31T02:00:00Z"
    )
    # 解釈できない値のみなら最初の非空文字列、全て空なら空文字
    assert mod.later_iso8601("", "  not-a-date ") == "not-a-date"
    assert mod.later_iso8601("", " ") == ""


@pytest.mark.parametrize(
    "payload",
    [{}, {"commit": "x"}, {"commit": {}}, {"commit": {"committer": "x"}}],
)
def test_extract_commit_committer_date_returns_empty_for_malformed(payload):
    assert mod.extract_commit_committer_date(payload) == ""


def test_extract_codex_findings_keeps_url_only_when_string():
    base = {
        "path": "a.py",
        "line": "bad",
        "body": "x",
        "user": {"login": "chatgpt-codex-connector[bot]"},
        "commit_id": SHA,
    }
    with_url = {**base, "id": 1, "html_url": "https://example.test/c/1"}
    bad_url = {**base, "id": 2, "html_url": 123}
    resolved = {**base, "id": 3}
    findings = mod.extract_codex_findings([with_url, bad_url, resolved], SHA, {"3"})
    assert findings == [
        {"path": "a.py", "line": None, "body": "x", "url": "https://example.test/c/1"},
        {"path": "a.py", "line": None, "body": "x"},
    ]


def test_payload_helpers_tolerate_non_dict_values():
    assert mod._payload_data("x") is None
    assert mod._payload_data({"data": {"a": 1}}) == {"a": 1}
    assert mod._payload_data({"a": 1}) == {"a": 1}
    mod._raise_graphql_errors("x")  # 例外なし
    mod._raise_graphql_errors({"errors": []})
    with pytest.raises(RuntimeError, match="boom"):
        mod._raise_graphql_errors({"errors": [{"message": "boom"}, "x"]})
    assert mod._page_info(None) == (False, None)
    assert mod._page_info({"pageInfo": {"hasNextPage": True, "endCursor": ""}}) == (
        False,
        None,
    )
    assert mod._comment_ids("x") == set()
    assert mod._comment_ids(["x", {"databaseId": None}, {"databaseId": 5}]) == {"5"}


def _thread_payload(*, has_next: bool, nodes=None):
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": nodes or [],
                        "pageInfo": {"hasNextPage": has_next, "endCursor": "c"},
                    }
                }
            }
        }
    }


def test_fetch_resolved_ids_raises_when_threads_pagination_never_ends():
    calls = []

    def graphql(query):
        calls.append(query)
        return _thread_payload(has_next=True)

    with pytest.raises(RuntimeError, match="MAX_REVIEW_THREAD_PAGES"):
        mod.fetch_resolved_review_comment_ids(
            owner="o", name="r", pr_number=1, graphql=graphql
        )
    assert len(calls) == mod.MAX_REVIEW_THREAD_PAGES


def test_fetch_resolved_ids_raises_when_thread_comments_pagination_never_ends():
    thread = {
        "id": "T1",
        "isResolved": True,
        "comments": {
            "nodes": [{"databaseId": 1}],
            "pageInfo": {"hasNextPage": True, "endCursor": "x"},
        },
    }

    def graphql(query):
        if "T1" in query:
            return {
                "data": {
                    "node": {
                        "comments": {
                            "nodes": [{"databaseId": 2}],
                            "pageInfo": {"hasNextPage": True, "endCursor": "y"},
                        }
                    }
                }
            }
        return _thread_payload(has_next=False, nodes=[thread])

    with pytest.raises(RuntimeError, match="MAX_THREAD_COMMENT_PAGES"):
        mod.fetch_resolved_review_comment_ids(
            owner="o", name="r", pr_number=1, graphql=graphql
        )


def _pr(**overrides):
    pr = {
        "number": 1,
        "created_at": "2026-05-31T00:00:00Z",
        "user": {"login": "github-actions[bot]"},
        "base": {"ref": "main"},
        "head": {
            "ref": "data/auto-update-20260531",
            "sha": SHA,
            "repo": {"full_name": "o/r"},
        },
        "body": "",
    }
    pr.update(overrides)
    return pr


def _stop_comment(sha=SHA, reason="codex_no_response"):
    return {
        "user": {"login": "github-actions[bot]"},
        "body": stop_marker(reason, "9", sha),
        "created_at": "2026-05-31T01:00:00Z",
    }


def _select(pr, comments):
    return mod.select_resume_candidates(
        pulls=[pr], comments_by_pr={"1": comments}, repo="o/r"
    )


def test_select_resume_candidates_accepts_baseline_case():
    assert len(_select(_pr(), [_stop_comment()])) == 1


@pytest.mark.parametrize(
    "pr",
    [
        _pr(user={"login": "someone"}),
        _pr(head={"ref": "claude/x", "sha": SHA, "repo": {"full_name": "o/r"}}),
        _pr(base={"ref": "develop"}),
        _pr(
            head={
                "ref": "data/auto-update-20260531",
                "sha": SHA,
                "repo": {"full_name": "fork/r"},
            }
        ),
        _pr(number=None),
        _pr(
            head={
                "ref": "data/auto-update-x",
                "sha": SHA,
                "repo": {"full_name": "o/r"},
            }
        ),
    ],
)
def test_select_resume_candidates_rejects_ineligible_pr(pr):
    assert _select(pr, [_stop_comment()]) == []


def test_select_resume_candidates_ignores_unusable_comments():
    other_author = {**_stop_comment(), "user": {"login": "x"}}
    no_marker = {**_stop_comment(), "body": "hello"}
    assert _select(_pr(), [other_author, no_marker, _stop_comment("b" * 40)]) == []
