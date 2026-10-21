from ms_data.gh.auto_review_gate import evaluate

HEAD_SHA = "abc123"
SINCE = "2026-05-31T08:45:23Z"
CODEX_USER = {"login": "chatgpt-codex-connector"}


def test_no_issue_comment_is_terminal_and_mergeable():
    result = evaluate(
        reviews=[],
        file_comments=[],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": "Codex Review: Didn't find any major issues. 確認済みです。",
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["review_complete"] is True
    assert result["merge_ok"] is True
    assert result["stop_reason"] == "none"


def test_no_issue_comment_with_leading_receipt_marker_is_mergeable():
    # 2026-10-17 以降の Codex 受領コメント形式（PR #336 / #337 で誤停止した実例）
    result = evaluate(
        reviews=[],
        file_comments=[],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": (
                    "<!-- codex-review-receipt:v1 -->\n\n"
                    "Codex Review: Didn't find any major issues. Hooray!\n\n"
                    "**Reviewed commit:** `abc123`"
                ),
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["no_issue_comment_count"] == 1
    assert result["merge_ok"] is True
    assert result["stop_reason"] == "none"


def test_review_summary_comment_is_not_terminal():
    result = evaluate(
        reviews=[],
        file_comments=[],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": (
                    "<!-- codex-pull-request-review-summary -->\n"
                    "<!-- codex-review-state:v1 {} -->\n\n"
                    "## Codex Review Summary\n"
                    "Codex Review: Didn't find any major issues."
                ),
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["no_issue_comment_count"] == 0
    assert result["merge_ok"] is False
    assert result["stop_reason"] == "no_response"


def test_generic_codex_comment_does_not_make_review_complete():
    result = evaluate(
        reviews=[],
        file_comments=[],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": "I'll take a look.",
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["issue_comment_count"] == 1
    assert result["review_complete"] is False
    assert result["merge_ok"] is False
    assert result["stop_reason"] == "no_response"


def test_codex_reaction_is_activity_but_not_review_complete():
    result = evaluate(
        reviews=[],
        file_comments=[],
        issue_comments=[],
        reactions=[
            {
                "user": CODEX_USER,
                "content": "+1",
            }
        ],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["reaction_count"] == 1
    assert result["terminal_count"] == 0
    assert result["review_complete"] is False
    assert result["merge_ok"] is False
    assert result["stop_reason"] == "no_response"


def test_file_comment_blocks_merge_even_without_review_body():
    result = evaluate(
        reviews=[],
        file_comments=[
            {
                "user": CODEX_USER,
                "commit_id": HEAD_SHA,
                "body": "Please fix this.",
            }
        ],
        issue_comments=[],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["review_complete"] is True
    assert result["merge_ok"] is False
    assert result["stop_reason"] == "findings"


def test_resolved_file_comment_does_not_block_merge():
    result = evaluate(
        reviews=[{"user": CODEX_USER, "commit_id": HEAD_SHA}],
        file_comments=[
            {
                "id": 3820325517,
                "user": CODEX_USER,
                "commit_id": HEAD_SHA,
                "body": "Please fix this.",
            }
        ],
        issue_comments=[],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
        resolved_comment_ids={"3820325517"},
    )

    assert result["finding_count"] == 0
    assert result["review_complete"] is True
    assert result["merge_ok"] is True
    assert result["stop_reason"] == "none"


def test_review_is_filtered_by_head_sha():
    result = evaluate(
        reviews=[
            {"user": CODEX_USER, "commit_id": "old"},
            {"user": CODEX_USER, "commit_id": HEAD_SHA},
        ],
        file_comments=[],
        issue_comments=[],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["review_count"] == 1
    assert result["review_complete"] is True
    assert result["merge_ok"] is True


def test_late_finding_wins_over_no_issue_comment():
    result = evaluate(
        reviews=[],
        file_comments=[
            {
                "user": CODEX_USER,
                "commit_id": HEAD_SHA,
                "body": "Please fix this.",
            }
        ],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": "Codex Review: Didn't find any major issues. 確認済みです。",
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["review_complete"] is True
    assert result["merge_ok"] is False
    assert result["stop_reason"] == "findings"


def test_disconnect_comment_sets_disconnected_without_terminal():
    result = evaluate(
        reviews=[],
        file_comments=[],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": (
                    "To use Codex here, create a Codex account and connect to github"
                ),
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["disconnect_count"] == 1
    assert result["terminal_count"] == 0
    assert result["review_complete"] is False
    assert result["merge_ok"] is False
    assert result["stop_reason"] == "disconnected"


def test_disconnect_comment_before_since_is_ignored():
    result = evaluate(
        reviews=[],
        file_comments=[],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:00:00Z",
                "body": "To use Codex here, create a Codex account and connect to github",
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["disconnect_count"] == 0
    assert result["issue_comment_count"] == 0
    assert result["stop_reason"] == "no_response"


def test_findings_win_over_disconnect():
    result = evaluate(
        reviews=[],
        file_comments=[
            {
                "user": CODEX_USER,
                "commit_id": HEAD_SHA,
                "body": "Please fix this.",
            }
        ],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": "To use Codex here, create a Codex account and connect to github",
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["disconnect_count"] == 1
    assert result["stop_reason"] == "findings"


def _carried_finding() -> dict:
    # 旧 HEAD で投稿され、行が変わらず現 HEAD へ付け替えられた指摘（PR #339 の実例）
    return {
        "id": 4316414488,
        "user": CODEX_USER,
        "commit_id": HEAD_SHA,
        "original_commit_id": "old123",
        "body": "中スロット値を取得元の29に戻す",
    }


def test_carried_finding_alone_waits_for_current_head_review():
    result = evaluate(
        reviews=[],
        file_comments=[_carried_finding()],
        issue_comments=[],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["carried_finding_count"] == 1
    assert result["review_complete"] is False
    assert result["merge_ok"] is False
    # 応答が無いまま打ち切られた場合は従来どおり findings で停止する
    assert result["finding_count"] == 1
    assert result["stop_reason"] == "findings"


def test_carried_finding_is_ignored_after_current_head_no_issue_comment():
    result = evaluate(
        reviews=[],
        file_comments=[_carried_finding()],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": (
                    "<!-- codex-review-receipt:v1 -->\n\n"
                    "Codex Review: Didn't find any major issues. Hooray!"
                ),
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["carried_finding_count"] == 1
    assert result["finding_count"] == 0
    assert result["review_complete"] is True
    assert result["merge_ok"] is True
    assert result["stop_reason"] == "none"


def test_current_head_finding_wins_even_with_original_commit_id():
    finding = _carried_finding() | {"original_commit_id": HEAD_SHA}
    result = evaluate(
        reviews=[],
        file_comments=[finding],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": "Codex Review: Didn't find any major issues.",
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["carried_finding_count"] == 0
    assert result["finding_count"] == 1
    assert result["merge_ok"] is False
    assert result["stop_reason"] == "findings"


def test_carried_finding_with_disconnect_still_stops_as_findings():
    result = evaluate(
        reviews=[],
        file_comments=[_carried_finding()],
        issue_comments=[
            {
                "user": CODEX_USER,
                "created_at": "2026-05-31T08:47:49Z",
                "body": "To use Codex here, create a Codex account and connect to github",
            }
        ],
        reactions=[],
        head_sha=HEAD_SHA,
        since=SINCE,
    )

    assert result["review_complete"] is False
    assert result["stop_reason"] == "findings"
