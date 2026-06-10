import json
from pathlib import Path

import ms_data.tasks as tasks


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_task_update_fast_skips_followup_steps_when_no_candidates(
    monkeypatch, tmp_path: Path
):
    calls = []
    monkeypatch.chdir(tmp_path)

    def fake_run_python_module(module: str, *args: str) -> int:
        calls.append((module, args))
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "detect-changed":
            _write_json(tmp_path / "cache/index_changed.json", [])
            _write_json(
                tmp_path / "cache/index_changed_meta.json",
                {
                    "candidate_count": 0,
                    "total_count": 558,
                    "fast_path": True,
                    "fallback_reason": "",
                },
            )
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)

    rc = tasks.task_update_fast()

    assert rc == 0
    assert calls == [
        (
            "ms_data.scraping.scrape_msdata",
            (
                "index",
                "--url",
                tasks.INDEX_URL,
                "--out",
                "cache/index.json",
                "--ttl",
                "1h",
            ),
        ),
        (
            "ms_data.scraping.scrape_msdata",
            (
                "detect-changed",
                "--in",
                "cache/index.json",
                "--out",
                "cache/index_changed.json",
                "--meta-out",
                "cache/index_changed_meta.json",
                "--reports-dir",
                "reports",
                "--msdata",
                "msData.json",
                "--freshness-window",
                "1h",
                "--detail-fetch-state",
                "cache/detail_fetch_state.json",
                "--stale-detail-days",
                "14",
                "--min-age-coverage",
                "0.95",
            ),
        ),
    ]


def test_task_update_fast_runs_import_and_validate_when_candidates_exist(
    monkeypatch, tmp_path: Path
):
    calls = []
    monkeypatch.chdir(tmp_path)

    def fake_run_python_module(module: str, *args: str) -> int:
        calls.append((module, args))
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "detect-changed":
            _write_json(
                tmp_path / "cache/index_changed.json",
                [
                    {
                        "name": "A",
                        "change_reasons": ["recent_update"],
                    },
                    {
                        "name": "B",
                        "change_reasons": ["recent_update"],
                    },
                ],
            )
            _write_json(
                tmp_path / "cache/index_changed_meta.json",
                {
                    "candidate_count": 2,
                    "total_count": 558,
                    "fast_path": True,
                    "fallback_reason": "",
                },
            )
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "details":
            details = tmp_path / "cache/details.jsonl"
            details.parent.mkdir(parents=True, exist_ok=True)
            details.write_text('{"MS名":"A_LV1"}\n', encoding="utf-8")
        return 0

    import_called = {"value": False}
    validate_called = {"value": False}

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)
    monkeypatch.setattr(
        tasks,
        "task_import_details",
        lambda: import_called.__setitem__("value", True) or 0,
    )
    monkeypatch.setattr(
        tasks,
        "task_validate_strict",
        lambda: validate_called.__setitem__("value", True) or 0,
    )

    rc = tasks.task_update_fast()

    assert rc == 0
    assert import_called["value"] is True
    assert validate_called["value"] is True
    assert calls == [
        (
            "ms_data.scraping.scrape_msdata",
            (
                "index",
                "--url",
                tasks.INDEX_URL,
                "--out",
                "cache/index.json",
                "--ttl",
                "1h",
            ),
        ),
        (
            "ms_data.scraping.scrape_msdata",
            (
                "detect-changed",
                "--in",
                "cache/index.json",
                "--out",
                "cache/index_changed.json",
                "--meta-out",
                "cache/index_changed_meta.json",
                "--reports-dir",
                "reports",
                "--msdata",
                "msData.json",
                "--freshness-window",
                "1h",
                "--detail-fetch-state",
                "cache/detail_fetch_state.json",
                "--stale-detail-days",
                "14",
                "--min-age-coverage",
                "0.95",
            ),
        ),
        (
            "ms_data.scraping.scrape_msdata",
            (
                "details",
                "--in",
                "cache/index_changed.json",
                "--out",
                "cache/details.jsonl",
                "--rate",
                "2.0",
                "--limit",
                "0",
                "--ttl",
                "0s",
                "--detail-fetch-state-out",
                "cache/detail_fetch_state.json",
                "--changed-only",
            ),
        ),
    ]


def test_task_update_fast_disables_changed_only_for_index_reasoned_candidates(
    monkeypatch, tmp_path: Path
):
    calls = []
    monkeypatch.chdir(tmp_path)

    def fake_run_python_module(module: str, *args: str) -> int:
        calls.append((module, args))
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "detect-changed":
            _write_json(
                tmp_path / "cache/index_changed.json",
                [
                    {
                        "name": "New Candidate",
                        "change_reasons": ["new_name", "recent_update"],
                    }
                ],
            )
            _write_json(
                tmp_path / "cache/index_changed_meta.json",
                {
                    "candidate_count": 1,
                    "total_count": 558,
                    "fast_path": True,
                    "fallback_reason": "",
                },
            )
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "details":
            details = tmp_path / "cache/details.jsonl"
            details.parent.mkdir(parents=True, exist_ok=True)
            details.write_text('{"MS名":"A_LV1"}\n', encoding="utf-8")
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)
    monkeypatch.setattr(tasks, "task_import_details", lambda: 0)
    monkeypatch.setattr(tasks, "task_validate_strict", lambda: 0)

    rc = tasks.task_update_fast()

    assert rc == 0
    detail_call = calls[-1]
    assert detail_call[0] == "ms_data.scraping.scrape_msdata"
    assert detail_call[1][0] == "details"
    assert "--changed-only" not in detail_call[1]


def test_can_use_changed_only_rejects_stale_detail_cache_reason():
    changed_index = [
        {
            "name": "A",
            "change_reasons": ["recent_update", "stale_detail_cache"],
        }
    ]
    meta = {"fast_path": True}

    assert tasks._can_use_changed_only(changed_index, meta) is False


def test_task_update_fast_disables_changed_only_in_no_network(
    monkeypatch, tmp_path: Path
):
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NO_NET", "1")

    def fake_run_python_module(module: str, *args: str) -> int:
        calls.append((module, args))
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "detect-changed":
            _write_json(
                tmp_path / "cache/index_changed.json",
                [{"name": "A", "change_reasons": ["recent_update"]}],
            )
            _write_json(
                tmp_path / "cache/index_changed_meta.json",
                {
                    "candidate_count": 1,
                    "total_count": 558,
                    "fast_path": True,
                    "fallback_reason": "",
                },
            )
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "details":
            details = tmp_path / "cache/details.jsonl"
            details.parent.mkdir(parents=True, exist_ok=True)
            details.write_text('{"MS名":"A_LV1"}\n', encoding="utf-8")
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)
    monkeypatch.setattr(tasks, "task_import_details", lambda: 0)
    monkeypatch.setattr(tasks, "task_validate_strict", lambda: 0)

    rc = tasks.task_update_fast()

    assert rc == 0
    detail_call = calls[-1]
    assert detail_call[0] == "ms_data.scraping.scrape_msdata"
    assert detail_call[1][0] == "details"
    assert "--no-network" in detail_call[1]
    assert "--changed-only" not in detail_call[1]
    assert detail_call[1][detail_call[1].index("--ttl") + 1] == "1h"


def test_task_update_fast_fails_when_detect_changed_outputs_are_invalid(
    monkeypatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)

    def fake_run_python_module(module: str, *args: str) -> int:
        if module == "ms_data.scraping.scrape_msdata" and args[0] == "detect-changed":
            path = tmp_path / "cache/index_changed_meta.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{invalid", encoding="utf-8")
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)

    rc = tasks.task_update_fast()

    assert rc == 1


def test_task_detect_changed_passes_revalidate_flag(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REVALIDATE", "1")
    calls = []

    def fake_run_python_module(module: str, *args: str) -> int:
        calls.append((module, args))
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)

    rc = tasks.task_detect_changed()

    assert rc == 0
    assert calls[0][0] == "ms_data.scraping.scrape_msdata"
    assert "--revalidate" in calls[0][1]
    assert "--force-full" not in calls[0][1]


def test_task_detect_changed_omits_revalidate_flag_by_default(
    monkeypatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REVALIDATE", raising=False)
    calls = []

    def fake_run_python_module(module: str, *args: str) -> int:
        calls.append((module, args))
        return 0

    monkeypatch.setattr(tasks, "_run_python_module", fake_run_python_module)

    rc = tasks.task_detect_changed()

    assert rc == 0
    assert "--revalidate" not in calls[0][1]
