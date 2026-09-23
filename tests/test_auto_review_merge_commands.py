"""auto_review_merge の ReviewDeps 既定値と CLI エントリの smoke テスト。

cmd_* 個別の網羅テストは test_auto_review_*_commands.py に分割済み。
"""

import pytest

from ms_data.gh import auto_review_merge
from ms_data.gh.auto_review_merge import (
    ReviewDeps,
    main,
)


def test_review_deps_default_points_to_production_implementations():
    deps = ReviewDeps.default()

    assert deps.client is auto_review_merge.GitHubClient
    assert deps.clock is auto_review_merge.time
    assert deps.run_gh is auto_review_merge.run_gh
    assert deps.collect_metrics is auto_review_merge.collect_review_metrics
    assert deps.ensure_comment is auto_review_merge.ensure_review_comment
    assert deps.notify_stop is auto_review_merge.notify_review_stop
    assert deps.run_url is auto_review_merge.github_run_url


def test_cli_help_smoke():
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0


def test_cli_default_factory_resolve_target_pr_smoke(
    monkeypatch, tmp_path, read_github_output
):
    calls: list[list[str]] = []

    def fake_run_gh(command, **_):
        calls.append(command)
        return "[]"

    monkeypatch.setattr(auto_review_merge, "run_gh", fake_run_gh)
    out = tmp_path / "output.txt"

    assert (
        main(
            [
                "resolve-target-pr",
                "--repo",
                "owner/repo",
                "--run-id",
                "111",
                "--run-created-at",
                "2026-05-31T09:00:25Z",
                "--github-output",
                str(out),
            ]
        )
        == 0
    )
    assert calls[0][0:3] == [
        "gh",
        "api",
        "repos/owner/repo/pulls?state=open&base=main&per_page=100",
    ]
    assert read_github_output(out)["skip"] == "true"
