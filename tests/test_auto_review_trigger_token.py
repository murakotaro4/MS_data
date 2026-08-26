from types import SimpleNamespace

from ms_data.gh import auto_review_merge


def test_run_gh_with_token_uses_isolated_gh_token(monkeypatch):
    captured = {}

    def run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout='{"id": 10}')

    monkeypatch.setenv("GH_TOKEN", "original-token")
    monkeypatch.setattr(auto_review_merge.subprocess, "run", run)

    assert auto_review_merge._run_gh_with_token(["gh", "api", "user"], "pat") == (
        '{"id": 10}'
    )
    assert captured["cmd"] == ["gh", "api", "user"]
    assert captured["kwargs"]["env"]["GH_TOKEN"] == "pat"
    assert captured["kwargs"]["check"] is True
    assert auto_review_merge.os.environ["GH_TOKEN"] == "original-token"


def test_post_codex_trigger_comment_uses_token_runner(monkeypatch):
    captured = {}

    def run_with_token(cmd, token):
        captured["runner"] = (cmd, token)
        return '{"id": 10}'

    def api(endpoint, **kwargs):
        captured["endpoint"] = endpoint
        captured["kwargs"] = kwargs
        return {"id": 10, "raw": kwargs["runner"](["gh", "api", endpoint])}

    monkeypatch.setenv("CODEX_TRIGGER_TOKEN", " pat-token ")
    monkeypatch.setattr(auto_review_merge, "_run_gh_with_token", run_with_token)
    monkeypatch.setattr(auto_review_merge, "gh_api_json", api)

    result = auto_review_merge.post_codex_trigger_comment(
        repo="owner/repo", pr_number="97", body="@codex review"
    )

    assert result["id"] == 10
    assert captured["endpoint"] == "repos/owner/repo/issues/97/comments"
    assert captured["kwargs"]["method"] == "POST"
    assert captured["kwargs"]["fields"] == {"body": "@codex review"}
    assert captured["runner"][1] == "pat-token"


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
