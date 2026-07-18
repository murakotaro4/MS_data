import json
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
