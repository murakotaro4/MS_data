"""実CLI→ghプロセス境界で最新HEAD CIの停止・通常マージを検証する。"""

import json
import os
import subprocess
import sys

import pytest

from auto_review_helpers import successful_ci_runs
from workflow_contract import ROOT

HEAD = "head-sha"


def _run(tmp_path, *, payload=None, api_error=False, head_race=False):
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {"payload": payload, "api_error": api_error, "head_race": head_race}
        ),
        encoding="utf-8",
    )
    stub = tmp_path / "gh_stub.py"
    stub.write_text(
        '''import json, os, sys
from pathlib import Path
root = Path(os.environ["GH_STUB_ROOT"])
scenario = json.loads((root / "scenario.json").read_text())
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as file:
    file.write(json.dumps(args) + "\\n")
if args[:2] == ["pr", "view"]:
    merged = (root / "merged").exists()
    print(json.dumps({"state": "MERGED" if merged else "OPEN",
                     "headRefOid": "head-sha",
                     "mergeCommit": {"oid": "merge-sha"} if merged else None}))
elif args[0] == "api":
    if scenario["api_error"]:
        print("HTTP 403: CI access denied", file=sys.stderr)
        sys.exit(1)
    print(scenario["payload"])
elif args[:2] == ["pr", "merge"]:
    if scenario["head_race"]:
        print("HEAD does not match --match-head-commit", file=sys.stderr)
        sys.exit(1)
    (root / "merged").touch()
elif args[:2] != ["workflow", "run"]:
    sys.exit("unexpected gh call")
''',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["GH_STUB_ROOT"] = str(tmp_path)
    # ghの起動先だけをPythonスタブへ差し替え、Windowsでも本番run_ghの
    # subprocess/例外処理とCLI引数・出力契約をそのまま実行する。
    entrypoint = (
        "import sys; from dataclasses import replace; "
        "from ms_data.gh.auto_review_merge import main, ReviewDeps, run_gh; "
        f"runner = lambda args: run_gh([sys.executable, {str(stub)!r}, *args[1:]]); "
        "sys.exit(main(deps_factory=lambda: replace(ReviewDeps.default(), run_gh=runner)))"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            entrypoint,
            "merge",
            "--repo",
            "owner/repo",
            "--pr-number",
            "97",
            "--head-ref",
            "data/auto-update-20260531",
            "--head-sha",
            HEAD,
            "--source-run-id",
            "111",
            "--github-output",
            str(tmp_path / "output"),
            "--step-summary",
            str(tmp_path / "summary"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    calls = [
        json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()
    ]
    return result, calls


def _latest(**overrides):
    run = json.loads(successful_ci_runs(HEAD))[0]
    run.update(overrides)
    return run


def _assert_stopped(tmp_path, result, calls, reason):
    assert result.returncode == 1, result.stderr
    assert not any(call[:2] in (["pr", "merge"], ["workflow", "run"]) for call in calls)
    assert not (tmp_path / "merged").exists()
    assert f"skip_reason={reason}" in (tmp_path / "output").read_text()
    assert f"- reason: {reason}" in (tmp_path / "summary").read_text()


@pytest.mark.parametrize(
    "conclusion",
    [
        "failure",
        "cancelled",
        "timed_out",
        "neutral",
        "skipped",
        "action_required",
        None,
    ],
)
def test_latest_unsuccessful_ci_does_not_fall_back_to_old_success(tmp_path, conclusion):
    old_success = _latest(id=1, created_at="2026-10-09T00:00:00Z")
    # 一覧順に依存せず、作成日時の新しいrunを評価する。
    payload = json.dumps([old_success, _latest(conclusion=conclusion)])
    result, calls = _run(tmp_path, payload=payload)
    _assert_stopped(tmp_path, result, calls, "ci_not_success")


@pytest.mark.parametrize(
    "status", ["queued", "in_progress", "waiting", "pending", "requested", None]
)
def test_latest_incomplete_ci_is_not_success(tmp_path, status):
    # 古いrunが成功でも、最新attempt/runの未完了を隠してはいけない。
    payload = json.dumps(
        [_latest(status=status), _latest(id=1, created_at="2026-10-09T00:00:00Z")]
    )
    result, calls = _run(tmp_path, payload=payload)
    _assert_stopped(tmp_path, result, calls, "ci_incomplete")


@pytest.mark.parametrize(
    "change",
    [
        {"head_sha": "old-head"},
        {"head_branch": "other-branch"},
        {"event": "push"},
        {"path": ".github/workflows/other.yml"},
        {"path": ".github/workflows/other.yml@main"},
        {"path": ".github/workflows/ci.yml.bak@main"},
    ],
)
def test_wrong_ci_target_is_not_success(tmp_path, change):
    result, calls = _run(tmp_path, payload=json.dumps([_latest(**change)]))
    _assert_stopped(tmp_path, result, calls, "ci_target_mismatch")


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("[]", "ci_not_found"),
        ("not-json", "ci_unavailable"),
        ('{"workflow_runs": []}', "ci_unavailable"),
        ("[null]", "ci_unavailable"),
        (json.dumps([_latest(id=None)]), "ci_unavailable"),
        (json.dumps([_latest(id=True)]), "ci_unavailable"),
        (json.dumps([_latest(created_at="invalidZ")]), "ci_unavailable"),
        (json.dumps([_latest(created_at=None)]), "ci_unavailable"),
    ],
)
def test_missing_or_invalid_ci_is_not_success(tmp_path, payload, reason):
    result, calls = _run(tmp_path, payload=payload)
    _assert_stopped(tmp_path, result, calls, reason)


def test_ci_api_failure_stops_without_merge_or_notify(tmp_path):
    result, calls = _run(tmp_path, api_error=True)
    _assert_stopped(tmp_path, result, calls, "ci_unavailable")
    assert "HTTP 403" in result.stderr


@pytest.mark.parametrize(
    "workflow_path",
    [
        ".github/workflows/ci.yml",
        ".github/workflows/ci.yml@main",
        ".github/workflows/ci.yml@refs/pull/97/merge",
    ],
)
def test_successful_latest_ci_merges_with_head_match_and_notifies(
    tmp_path, workflow_path
):
    # gh --paginate のページ間JSON連結も実CLIで検証する。
    payload = (
        json.dumps(
            [_latest(conclusion="failure", id=1, created_at="2026-10-09T00:00:00Z")]
        )
        + "\n"
        + json.dumps([_latest(path=workflow_path)])
    )
    result, calls = _run(tmp_path, payload=payload)
    assert result.returncode == 0, result.stderr
    assert [call[:2] for call in calls][::2] == [
        ["pr", "view"],
        ["pr", "merge"],
        ["workflow", "run"],
    ]
    ci_call = calls[1]
    assert "head_sha=head-sha&event=pull_request" in ci_call[1]
    assert "--paginate" in ci_call
    assert "status=" not in ci_call[1]
    merge = calls[2]
    assert merge[-2:] == ["--match-head-commit", HEAD]
    assert "--admin" not in merge
    assert "merged=true" in (tmp_path / "output").read_text()


def test_head_change_after_ci_check_never_notifies(tmp_path):
    result, calls = _run(tmp_path, payload=successful_ci_runs(HEAD), head_race=True)
    assert result.returncode != 0
    assert "HEAD does not match" in result.stderr
    assert calls[-1][:2] == ["pr", "merge"]
    assert not any(call[:2] == ["workflow", "run"] for call in calls)
    assert not (tmp_path / "merged").exists()
