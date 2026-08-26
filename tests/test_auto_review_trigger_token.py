from types import SimpleNamespace

from ms_data.gh import auto_review_merge, gh_json


def test_run_gh_env_overrides_uses_isolated_gh_token(monkeypatch):
    captured = {}

    def run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout='{"id": 10}')

    monkeypatch.setenv("GH_TOKEN", "original-token")
    monkeypatch.setattr(gh_json.subprocess, "run", run)

    assert gh_json.run_gh(
        ["gh", "api", "user"], env_overrides={"GH_TOKEN": "pat"}
    ) == '{"id": 10}'
    assert captured["cmd"] == ["gh", "api", "user"]
    assert captured["kwargs"]["env"]["GH_TOKEN"] == "pat"
    assert captured["kwargs"]["check"] is True
    assert gh_json.os.environ["GH_TOKEN"] == "original-token"


def test_post_codex_trigger_comment_uses_token_runner(monkeypatch):
    captured = {}

    def run_gh(cmd, *, env_overrides=None):
        captured["runner"] = (cmd, env_overrides)
        return '{"id": 10}'

    def api(endpoint, **kwargs):
        captured["endpoint"] = endpoint
        captured["kwargs"] = kwargs
        return {"id": 10, "raw": kwargs["runner"](["gh", "api", endpoint])}

    monkeypatch.setenv("CODEX_TRIGGER_TOKEN", " pat-token ")
    monkeypatch.setattr(auto_review_merge, "run_gh", run_gh)
    monkeypatch.setattr(auto_review_merge, "gh_api_json", api)

    result = auto_review_merge.post_codex_trigger_comment(
        repo="owner/repo", pr_number="97", body="@codex review"
    )

    assert result["id"] == 10
    assert captured["endpoint"] == "repos/owner/repo/issues/97/comments"
    assert captured["kwargs"]["method"] == "POST"
    assert captured["kwargs"]["fields"] == {"body": "@codex review"}
    assert captured["runner"][1] == {"GH_TOKEN": "pat-token"}


def test_post_codex_trigger_comment_without_token_uses_default_runner(monkeypatch):
    captured = {}

    def api(endpoint, **kwargs):
        captured["endpoint"] = endpoint
        captured["kwargs"] = kwargs
        return {"id": 11}

    monkeypatch.delenv("CODEX_TRIGGER_TOKEN", raising=False)
    monkeypatch.setattr(auto_review_merge, "gh_api_json", api)

    assert auto_review_merge.post_codex_trigger_comment(
        repo="owner/repo", pr_number="97", body="@codex review"
    ) == {"id": 11}
    assert "runner" not in captured["kwargs"]
