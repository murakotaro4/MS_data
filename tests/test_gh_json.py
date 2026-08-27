import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from ms_data.gh import gh_json


def test_run_gh_uses_existing_subprocess_contract(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="output\n")

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)

    assert gh_json.run_gh(["gh", "pr", "view", "1"]) == "output\n"
    assert captured == {
        "args": ["gh", "pr", "view", "1"],
        "kwargs": {
            "check": True,
            "text": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        },
    }


def test_run_gh_merges_env_overrides(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["env"] = kwargs["env"]
        return SimpleNamespace(stdout="output\n")

    monkeypatch.setenv("EXISTING_KEY", "existing")
    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)

    assert (
        gh_json.run_gh(["gh", "api", "user"], env_overrides={"GH_TOKEN": "token"})
        == "output\n"
    )
    assert captured["env"]["EXISTING_KEY"] == "existing"
    assert captured["env"]["GH_TOKEN"] == "token"
    assert captured["env"] is not os.environ


def test_run_gh_reprints_captured_stderr_before_reraising(monkeypatch, capsys):
    error = subprocess.CalledProcessError(
        1,
        ["gh", "api", "user"],
        stderr="gh: authentication failed\n",
    )

    def fake_run(args, **kwargs):
        raise error

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as raised:
        gh_json.run_gh(["gh", "api", "user"])

    assert raised.value is error
    assert capsys.readouterr().err == "gh: authentication failed\n"


def test_run_gh_get_retries_transient_error_then_succeeds(monkeypatch):
    error = subprocess.CalledProcessError(
        1,
        ["gh", "api", "user"],
        stderr="gh: HTTP 502 bad gateway",
    )
    outcomes = iter([error, '{"login": "octocat"}'])
    calls = []

    def fake_run_gh(args, *, env_overrides=None):
        calls.append((args, env_overrides))
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(gh_json, "run_gh", fake_run_gh)

    assert (
        gh_json.run_gh_get(
            ["gh", "api", "user"],
            env_overrides={"GH_TOKEN": "token"},
            sleeper=lambda delay: None,
        )
        == '{"login": "octocat"}'
    )
    assert calls == [
        (["gh", "api", "user"], {"GH_TOKEN": "token"}),
        (["gh", "api", "user"], {"GH_TOKEN": "token"}),
    ]


def test_run_gh_get_raises_last_error_after_four_transient_failures(monkeypatch):
    errors = [
        subprocess.CalledProcessError(
            1,
            ["gh", "api", "user"],
            stderr=f"connection reset attempt {attempt}",
        )
        for attempt in range(4)
    ]

    def fake_run_gh(args, *, env_overrides=None):
        raise errors.pop(0)

    monkeypatch.setattr(gh_json, "run_gh", fake_run_gh)
    last_error = errors[-1]

    with pytest.raises(subprocess.CalledProcessError) as raised:
        gh_json.run_gh_get(["gh", "api", "user"], sleeper=lambda delay: None)

    assert raised.value is last_error
    assert errors == []


def test_run_gh_get_does_not_retry_non_transient_error(monkeypatch):
    error = subprocess.CalledProcessError(
        1,
        ["gh", "api", "user"],
        stderr="gh: authentication failed",
    )
    calls = 0

    def fake_run_gh(args, *, env_overrides=None):
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(gh_json, "run_gh", fake_run_gh)

    with pytest.raises(subprocess.CalledProcessError) as raised:
        gh_json.run_gh_get(["gh", "api", "user"], sleeper=lambda delay: None)

    assert raised.value is error
    assert calls == 1


def test_run_gh_get_uses_exponential_retry_delays(monkeypatch):
    error = subprocess.CalledProcessError(
        1,
        ["gh", "api", "user"],
        stderr="request timed out",
    )
    sleeps = []

    def fake_run_gh(args, *, env_overrides=None):
        raise error

    monkeypatch.setattr(gh_json, "run_gh", fake_run_gh)

    with pytest.raises(subprocess.CalledProcessError):
        gh_json.run_gh_get(["gh", "api", "user"], sleeper=sleeps.append)

    assert sleeps == [2, 4, 8]


@pytest.mark.parametrize(
    "stderr",
    [
        "gh: http 500 internal server error",
        "gh: TiMeOuT",
        "gh: TIMED OUT",
        "gh: CoNnEcTiOn reset",
        "gh: COULD NOT RESOLVE host",
    ],
)
def test_run_gh_get_matches_all_transient_patterns_case_insensitively(
    monkeypatch, stderr
):
    error = subprocess.CalledProcessError(
        1,
        ["gh", "api", "user"],
        stderr=stderr,
    )
    calls = 0

    def fake_run_gh(args, *, env_overrides=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return "[]"

    monkeypatch.setattr(gh_json, "run_gh", fake_run_gh)

    assert gh_json.run_gh_get(["gh", "api", "user"], sleeper=lambda delay: None) == "[]"
    assert calls == 2


def test_run_gh_itself_does_not_retry(monkeypatch):
    error = subprocess.CalledProcessError(
        1,
        ["gh", "pr", "merge", "1"],
        stderr="HTTP 503 service unavailable",
    )
    calls = 0

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as raised:
        gh_json.run_gh(["gh", "pr", "merge", "1"])

    assert raised.value is error
    assert calls == 1


def test_gh_api_json_builds_command_and_parses_json():
    captured = {}

    def fake_runner(args):
        captured["args"] = args
        return '{"id": 5}'

    result = gh_json.gh_api_json(
        "repos/owner/repo/issues/1/comments",
        method="POST",
        fields={"body": "hello"},
        headers=["Accept: application/vnd.github+json"],
        runner=fake_runner,
    )

    assert captured["args"] == [
        "gh",
        "api",
        "repos/owner/repo/issues/1/comments",
        "-X",
        "POST",
        "-H",
        "Accept: application/vnd.github+json",
        "-f",
        "body=hello",
    ]
    assert result == {"id": 5}


def test_gh_api_json_returns_empty_list_for_empty_output():
    assert gh_json.gh_api_json("endpoint", runner=lambda args: "") == []


def test_gh_api_json_raises_for_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        gh_json.gh_api_json("endpoint", runner=lambda args: "not json")


def test_gh_api_json_flattens_paginated_json_documents():
    captured = {}

    def fake_runner(args):
        captured["args"] = args
        return '[{"id": 1}]\n[{"id": 2}]'

    result = gh_json.gh_api_json(
        "repos/owner/repo/issues/1/comments",
        paginate=True,
        runner=fake_runner,
    )

    assert captured["args"] == [
        "gh",
        "api",
        "repos/owner/repo/issues/1/comments",
        "--paginate",
    ]
    assert result == [{"id": 1}, {"id": 2}]


def test_gh_api_json_standard_get_uses_retry_runner(monkeypatch):
    captured = {}

    def fake_run_gh_get(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return '{"id": 5}'

    monkeypatch.setattr(gh_json, "run_gh_get", fake_run_gh_get)

    assert gh_json.gh_api_json("repos/owner/repo") == {"id": 5}
    assert captured == {
        "args": ["gh", "api", "repos/owner/repo"],
        "kwargs": {},
    }


def test_gh_api_json_explicit_runner_retries_transient_get(monkeypatch):
    calls = 0
    sleeps = []
    error = subprocess.CalledProcessError(
        1,
        ["gh", "api", "endpoint"],
        stderr="HTTP 503 service unavailable",
    )

    def fake_runner(args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return '{"id": 5}'

    retry_helper = gh_json._run_gh_get_with_runner

    def retry_without_wait(args, *, runner):
        return retry_helper(args, runner=runner, sleeper=sleeps.append)

    monkeypatch.setattr(gh_json, "_run_gh_get_with_runner", retry_without_wait)

    assert gh_json.gh_api_json("endpoint", runner=fake_runner) == {"id": 5}
    assert calls == 2
    assert sleeps == [2]


@pytest.mark.parametrize(
    ("method", "fields"),
    [
        ("POST", {"body": "hello"}),
        ("PATCH", {"body": "hello"}),
        ("GET", {"body": "hello"}),
    ],
)
def test_gh_api_json_mutating_calls_do_not_use_retry_runner(
    monkeypatch, method, fields
):
    calls = 0
    error = subprocess.CalledProcessError(
        1,
        ["gh", "api", "endpoint"],
        stderr="HTTP 503 service unavailable",
    )

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        raise error

    def fail_if_retried(args, **kwargs):
        raise AssertionError("mutating gh api call must not use run_gh_get")

    monkeypatch.setattr(gh_json.subprocess, "run", fake_run)
    monkeypatch.setattr(gh_json, "run_gh_get", fail_if_retried)

    with pytest.raises(subprocess.CalledProcessError) as raised:
        gh_json.gh_api_json("endpoint", method=method, fields=fields)

    assert raised.value is error
    assert calls == 1
