"""GitHubClient（gh_json.subprocess.run パッチ）と関数単位（FakeGitHubClient）のテスト。"""

import json
from types import SimpleNamespace

from ms_data.gh import gh_json
from ms_data.gh.auto_review_merge import (
    GITHUB_ACTIONS_BOT,
    GitHubClient,
    collect_review_metrics,
    ensure_review_comment,
    find_latest_bot_comment,
    retry_marker,
    review_marker,
)

from auto_review_helpers import (
    CODEX_BOT,
    HEAD_SHA,
    PAT_LOGIN,
    codex_review,
)

# ---------------------------------------------------------------------------
# 層A: GitHubClient（gh_json.subprocess.run パッチ）
# ---------------------------------------------------------------------------


def test_api_json_builds_get_command(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='[{"id": 1}]')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")
    result = client.api_json(
        "repos/owner/repo/pulls",
        paginate=True,
        headers=["Accept: application/vnd.github+json"],
    )

    assert captured["cmd"] == [
        "gh",
        "api",
        "repos/owner/repo/pulls",
        "--paginate",
        "-H",
        "Accept: application/vnd.github+json",
    ]
    assert result == [{"id": 1}]


def test_api_json_post_with_fields(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='{"id": 5}')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")
    result = client.post_issue_comment("97", "hello")

    assert captured["cmd"] == [
        "gh",
        "api",
        "repos/owner/repo/issues/97/comments",
        "-X",
        "POST",
        "-f",
        "body=hello",
    ]
    assert result == {"id": 5}


def test_resolved_review_comment_ids_uses_paged_graphql(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        if len(captured) == 1:
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "c1",
                                },
                                "nodes": [
                                    {
                                        "id": "t1",
                                        "isResolved": True,
                                        "comments": {
                                            "pageInfo": {
                                                "hasNextPage": False,
                                                "endCursor": None,
                                            },
                                            "nodes": [{"databaseId": 11}],
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        else:
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [
                                    {
                                        "id": "t2",
                                        "isResolved": True,
                                        "comments": {
                                            "pageInfo": {
                                                "hasNextPage": False,
                                                "endCursor": None,
                                            },
                                            "nodes": [{"databaseId": 12}],
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        return SimpleNamespace(stdout=json.dumps(payload))

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")
    assert client.resolved_review_comment_ids("231") == {"11", "12"}
    assert len(captured) == 2
    assert captured[0][:4] == ["gh", "api", "graphql", "-X"]
    first_query = captured[0][-1]
    second_query = captured[1][-1]
    assert first_query.startswith("query=")
    assert "after:" not in first_query
    assert 'after:"c1"' in second_query


def test_api_json_parses_paginated_stream(monkeypatch):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout='[{"id": 1}]\n[{"id": 2}]')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")

    assert client.issue_comments("97") == [{"id": 1}, {"id": 2}]


def test_issue_comment_fetches_detail(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout='{"id": 42}')

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    client = GitHubClient("owner/repo")

    assert client.issue_comment("42") == {"id": 42}
    assert captured["cmd"] == ["gh", "api", "repos/owner/repo/issues/comments/42"]


# ---------------------------------------------------------------------------
# 層B: 関数単位（FakeGitHubClient）
# ---------------------------------------------------------------------------


def test_ensure_review_comment_posts_when_missing(fake_gh):
    marker = review_marker(HEAD_SHA)
    comment_id, created_at, created_new = ensure_review_comment(
        client=fake_gh, pr_number="97", marker=marker
    )

    assert created_new is True
    assert comment_id == "1000"
    assert created_at == "2026-05-31T10:00:00Z"
    assert len(fake_gh.posted_comments) == 1
    body = fake_gh.posted_comments[0][1]
    assert body.startswith("@codex review")
    assert marker in body


def test_ensure_review_comment_reuses_existing(fake_gh):
    marker = review_marker(HEAD_SHA)
    fake_gh.responses["/issues/97/comments"] = [
        {
            "id": 42,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "github-actions[bot]"},
            "body": f"@codex review\n\n{marker}",
        }
    ]
    fake_gh.responses["/issues/comments/42"] = {
        "id": 42,
        "created_at": "2026-05-31T09:00:00Z",
    }

    comment_id, created_at, created_new = ensure_review_comment(
        client=fake_gh, pr_number="97", marker=marker
    )

    assert created_new is False
    assert comment_id == "42"
    assert created_at == "2026-05-31T09:00:00Z"
    assert fake_gh.posted_comments == []


def test_ensure_review_comment_reuses_pat_login_comment(fake_gh):
    marker = retry_marker(2, HEAD_SHA)
    fake_gh.responses["/issues/97/comments"] = [
        {
            "id": 77,
            "created_at": "2026-05-31T09:30:00Z",
            "user": {"login": PAT_LOGIN},
            "body": f"@codex review\n\n{marker}",
        }
    ]
    fake_gh.responses["/issues/comments/77"] = {
        "id": 77,
        "created_at": "2026-05-31T09:30:00Z",
    }

    comment_id, _, created_new = ensure_review_comment(
        client=fake_gh,
        pr_number="97",
        marker=marker,
        allowed_logins={GITHUB_ACTIONS_BOT, PAT_LOGIN},
    )

    assert created_new is False
    assert comment_id == "77"
    assert fake_gh.posted_comments == []


def test_find_latest_bot_comment_rejects_other_user_same_marker():
    marker = retry_marker(2, HEAD_SHA)
    comments = [
        {
            "id": 1,
            "created_at": "2026-05-31T09:00:00Z",
            "user": {"login": "random-user"},
            "body": f"@codex review\n\n{marker}",
        }
    ]
    assert (
        find_latest_bot_comment(comments, marker, {GITHUB_ACTIONS_BOT, PAT_LOGIN})
        is None
    )


def test_collect_review_metrics_aggregates_reactions_across_triggers(fake_gh):
    fake_gh.responses["/pulls/97/reviews"] = [codex_review()]
    fake_gh.responses["/issues/comments/10/reactions"] = [
        {"user": {"login": CODEX_BOT}, "content": "+1"}
    ]
    fake_gh.responses["/issues/comments/11/reactions"] = [
        {"user": {"login": CODEX_BOT}, "content": "+1"}
    ]

    metrics = collect_review_metrics(
        client=fake_gh,
        pr_number="97",
        head_sha=HEAD_SHA,
        trigger_comment_ids=["10", "11"],
        since="2026-05-31T10:00:00Z",
    )

    assert metrics["reaction_count"] == 2
    assert metrics["review_count"] == 1
    assert metrics["merge_ok"] is True
