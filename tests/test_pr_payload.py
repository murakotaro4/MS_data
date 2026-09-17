"""pr_payload アクセサと source_run_id 解決の一本化、PAT composite action の契約。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ms_data.gh import (
    auto_review_pr,
    auto_review_resume,
    cleanup_auto_update_prs,
    post_merge_assets,
    pr_payload,
)

REST_PULL = {
    "number": 1,
    "head": {
        "ref": "data/auto-update-20260903",
        "sha": "abc",
        "repo": {"full_name": "o/r"},
    },
    "base": {"ref": "main"},
}
GRAPHQL_PULL = {
    "number": 2,
    "headRefName": "data/auto-update-20260902",
    "headRefOid": "def",
    "baseRefName": "main",
}


def test_accessors_read_rest_keys():
    assert pr_payload.head_ref(REST_PULL) == "data/auto-update-20260903"
    assert pr_payload.head_sha(REST_PULL) == "abc"
    assert pr_payload.base_ref(REST_PULL) == "main"
    assert pr_payload.head_repo_full_name(REST_PULL) == "o/r"


def test_accessors_read_graphql_keys_and_default_to_empty():
    assert pr_payload.head_ref(GRAPHQL_PULL) == "data/auto-update-20260902"
    assert pr_payload.head_sha(GRAPHQL_PULL) == "def"
    assert pr_payload.base_ref(GRAPHQL_PULL) == "main"
    assert pr_payload.head_repo_full_name(GRAPHQL_PULL) == ""
    for fn in (pr_payload.head_ref, pr_payload.head_sha, pr_payload.base_ref):
        assert fn({}) == ""
        assert fn({"head": "not-a-dict", "headRefName": 5}) == ""


def test_rest_keys_take_precedence_over_graphql_keys():
    pull = {**REST_PULL, "headRefName": "other", "headRefOid": "zzz"}
    assert pr_payload.head_ref(pull) == "data/auto-update-20260903"
    assert pr_payload.head_sha(pull) == "abc"


def test_legacy_private_aliases_point_to_shared_accessors():
    assert auto_review_pr._head_ref is pr_payload.head_ref
    assert auto_review_pr._head_sha is pr_payload.head_sha
    assert auto_review_pr._base_ref is pr_payload.base_ref
    assert cleanup_auto_update_prs._head_ref is pr_payload.head_ref
    assert cleanup_auto_update_prs._head_oid is pr_payload.head_sha
    assert cleanup_auto_update_prs._base_ref is pr_payload.base_ref
    assert auto_review_pr.HEAD_REF_DATE_RE is pr_payload.HEAD_REF_DATE_RE
    assert post_merge_assets.HEAD_REF_RE is pr_payload.HEAD_REF_DATE_RE


def test_cleanup_head_belongs_to_repo_uses_shared_accessor():
    assert cleanup_auto_update_prs._head_belongs_to_repo(REST_PULL, "o/r") is True
    assert cleanup_auto_update_prs._head_belongs_to_repo(REST_PULL, "x/y") is False
    assert cleanup_auto_update_prs._head_belongs_to_repo(GRAPHQL_PULL, "x/y") is True


@pytest.mark.parametrize(
    ("body", "expected"),
    (
        ("<!-- source_run_id:26709410162 -->", "26709410162"),
        ("hello\nsource_run_id:1\n", "1"),
        ("no marker", ""),
        (None, ""),
        ("source_run_id=123", ""),
        ("source_run_id: 123", ""),
    ),
)
def test_source_run_id_marker_is_strict_colon_form(body, expected):
    assert pr_payload.source_run_id_from_body(body) == expected
    assert auto_review_pr.resolve_source_run_id(body or "") == expected


def test_post_merge_resolve_source_run_id_shares_marker_parser():
    assert post_merge_assets.resolve_source_run_id(" 42 ", "ignored") == "42"
    assert (
        post_merge_assets.resolve_source_run_id("", "<!-- source_run_id:7 -->") == "7"
    )
    with pytest.raises(ValueError):
        post_merge_assets.resolve_source_run_id("", "source_run_id=7")


def test_resume_params_from_args_normalizes_values():
    args = argparse.Namespace(
        run_id=123,
        retry_wait_seconds="0",
        poll_seconds="abc",
        pat_available="true",
        pat_login=" someone ",
    )
    params = auto_review_resume.ResumeParams.from_args(args)

    assert params.run_id == "123"
    assert params.retry_wait_seconds == 300
    assert params.poll_seconds == 30
    assert params.can_retrigger is True

    no_login = auto_review_resume.ResumeParams.from_args(
        argparse.Namespace(
            run_id="1",
            retry_wait_seconds="10",
            poll_seconds="5",
            pat_available="true",
            pat_login="",
        )
    )
    assert no_login.can_retrigger is False


def _workflow(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / ".github/workflows" / name).read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "workflow", ("auto_review_merge.yml", "resume_auto_review.yml")
)
def test_pat_resolution_uses_composite_action(workflow: str):
    text = _workflow(workflow)
    start = text.index("      - id: pat\n")
    end = text.index("\n      - ", start + 1)
    block = text[start:end]

    assert "uses: ./.github/actions/resolve-codex-pat" in block
    assert "pat: ${{ secrets.CODEX_TRIGGER_PAT }}" in block
    assert "gh api user" not in block
    assert "steps.pat.outputs.pat_available" in text
    assert "steps.pat.outputs.pat_login" in text


def test_resolve_codex_pat_action_declares_outputs():
    action = (
        Path(__file__).resolve().parents[1]
        / ".github/actions/resolve-codex-pat/action.yml"
    ).read_text(encoding="utf-8")

    assert "using: composite" in action
    assert "pat_available:" in action
    assert "pat_login:" in action
    assert 'gh api user --jq .login' in action
    assert "falling back without PAT" in action
