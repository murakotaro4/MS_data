import pytest

from ms_data.gh import repo_labels
from ms_data.gh.repo_labels import (
    DATA_UPDATE_PR_LABELS,
    LABEL_SPECS,
    specs_for,
)


def test_pr_labels_are_all_defined():
    for name in DATA_UPDATE_PR_LABELS:
        assert name in LABEL_SPECS


def test_specs_for_rejects_unknown_label():
    with pytest.raises(ValueError, match="unknown label"):
        specs_for(["data-update", "nope"])


def test_main_defaults_to_pr_labels_and_uses_force(monkeypatch, capsys):
    calls = []

    def fake_run_gh(cmd):
        calls.append(cmd)
        return ""

    monkeypatch.setattr(repo_labels, "run_gh", fake_run_gh)

    assert repo_labels.main(["--repo", "owner/repo"]) == 0

    assert [cmd[3] for cmd in calls] == list(DATA_UPDATE_PR_LABELS)
    for cmd in calls:
        assert cmd[:3] == ["gh", "label", "create"]
        assert cmd[-1] == "--force"
        assert "--repo" in cmd and "owner/repo" in cmd
    assert "label ensured: atwiki-quality" in capsys.readouterr().out


def test_main_with_explicit_names_and_unknown_returns_two(monkeypatch, capsys):
    monkeypatch.setattr(repo_labels, "run_gh", lambda cmd: "")

    assert repo_labels.main(["--repo", "owner/repo", "override-due"]) == 0
    assert repo_labels.main(["--repo", "owner/repo", "typo"]) == 2
    assert "unknown label" in capsys.readouterr().err


def test_main_requires_repo(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with pytest.raises(SystemExit):
        repo_labels.main([])
