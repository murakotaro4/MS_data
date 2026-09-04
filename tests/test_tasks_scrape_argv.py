"""tasks.py の scrape 系 argv 組み立てと CI ターゲット表の契約テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

import ms_data.tasks as tasks


@pytest.fixture
def capture(monkeypatch):
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_run_python_module(module: str, *args: str) -> int:
        calls.append((module, args))
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)
    for name in ("NO_NET", "FORCE", "CHANGED_ONLY", "RATE", "LIMIT", "TTL"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_scrape_index_argv_order(capture):
    assert tasks.task_scrape_index() == 0
    assert capture == [
        (
            tasks.SCRAPE_MODULE,
            (
                "index",
                "--url",
                tasks.INDEX_URL,
                "--out",
                "cache/index.json",
                "--ttl",
                tasks.DEFAULT_TTL,
            ),
        )
    ]


def test_scrape_details_argv_order_with_flags(capture, monkeypatch):
    monkeypatch.setenv("CHANGED_ONLY", "1")
    monkeypatch.setenv("NO_NET", "1")
    monkeypatch.setenv("FORCE", "1")
    monkeypatch.setenv("RATE", "1.5")
    monkeypatch.setenv("LIMIT", "3")

    assert tasks.task_scrape_details() == 0
    assert capture[0][1] == (
        "details",
        "--in",
        "cache/index.json",
        "--out",
        "cache/details.jsonl",
        "--rate",
        "1.5",
        "--limit",
        "3",
        "--ttl",
        tasks.DEFAULT_TTL,
        "--detail-fetch-state-out",
        "cache/detail_fetch_state.json",
        "--no-network",
        "--force",
        "--changed-only",
    )


def test_scrape_all_argv_has_no_input_and_shares_shape(capture):
    assert tasks.task_scrape_all() == 0
    module, args = capture[0]
    assert module == tasks.SCRAPE_MODULE
    assert args == (
        "all",
        "--out",
        "cache/details.jsonl",
        "--rate",
        str(tasks.DEFAULT_RATE),
        "--limit",
        "0",
        "--ttl",
        tasks.DEFAULT_TTL,
        "--detail-fetch-state-out",
        "cache/detail_fetch_state.json",
    )
    assert "--changed-only" not in args


def test_labels_argv_order(capture):
    assert tasks.task_labels() == 0
    assert capture[0][1] == (
        "labels",
        "--in",
        "cache/index.json",
        "--out",
        "cache/labels_raw.jsonl",
        "--rate",
        str(tasks.DEFAULT_RATE),
        "--limit",
        "0",
        "--ttl",
        tasks.DEFAULT_TTL,
    )


def test_details_argv_helper_is_shared_by_details_and_all():
    details = tasks._details_argv(input_path="x.json", ttl="0s", changed_only=True)
    everything = tasks._details_argv(input_path=None, ttl="0s", changed_only=False)

    assert details[:3] == ["details", "--in", "x.json"]
    assert everything[0] == "all"
    # `--in` 以降は同じ形
    assert details[3:-1] == everything[1:]
    assert details[-1] == "--changed-only"


def test_ci_targets_are_registered_tasks():
    assert tasks.CI_TARGETS
    for name in tasks.CI_TARGETS:
        assert name in tasks.TASKS
    assert tasks.CI_TARGETS[-1] == "validate-strict"


def test_field_completeness_out_uses_report_out_convention(capture, monkeypatch):
    monkeypatch.setenv("REPORT_DATE", "20260903")
    monkeypatch.setenv("REPORTS_DIR", "custom_reports")

    assert tasks.task_audit_field_completeness() == 0
    module, args = capture[0]
    assert module == "ms_data.audit.audit_field_completeness"
    assert (
        args[args.index("--out") + 1]
        == "custom_reports/2026/09/field_completeness_20260903.md"
    )

    monkeypatch.setenv("FIELD_COMPLETENESS_OUT", "override.md")
    assert tasks.task_audit_field_completeness() == 0
    args = capture[1][1]
    assert args[args.index("--out") + 1] == "override.md"


def test_load_detect_changed_outputs_reports_invalid_shape(
    monkeypatch, tmp_path: Path, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache/index_changed.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cache/index_changed_meta.json").write_text("[]", encoding="utf-8")

    assert tasks._load_detect_changed_outputs() is None
    assert "invalid detect-changed output shape" in capsys.readouterr().err

    (tmp_path / "cache/index_changed.json").write_text("{not json", encoding="utf-8")
    assert tasks._load_detect_changed_outputs() is None
    assert "failed to read detect-changed outputs" in capsys.readouterr().err
