from pathlib import Path

from ms_data.pipeline import report_detection_summary


def _args(
    meta: Path, github_output: Path, step_summary: Path, *, update_mode: str = "fast"
) -> list[str]:
    return [
        "--meta",
        str(meta),
        "--update-mode",
        update_mode,
        "--github-output",
        str(github_output),
        "--step-summary",
        str(step_summary),
    ]


def test_writes_compatible_outputs_and_summary(tmp_path: Path):
    meta = tmp_path / "index_changed_meta.json"
    meta.write_text(
        '{"candidate_count": 12, "fast_path": true, "age_coverage": 0.75, '
        '"fallback_reason": "stale_details", "mode": "revalidate"}',
        encoding="utf-8",
    )
    github_output = tmp_path / "github-output.txt"
    step_summary = tmp_path / "step-summary.md"

    code = report_detection_summary.main(
        _args(meta, github_output, step_summary, update_mode="revalidate")
    )

    assert code == 0
    assert github_output.read_text(encoding="utf-8") == (
        "candidate_count=12\n"
        "fast_path=true\n"
        "age_coverage=0.75\n"
        "fallback_reason=stale_details\n"
    )
    assert step_summary.read_text(encoding="utf-8") == (
        "### Change Detection\n"
        "- update_mode: revalidate\n"
        "- mode: revalidate\n"
        "- candidate_count: 12\n"
        "- fast_path: true\n"
        "- age_coverage: 0.75\n"
        "- fallback_reason: stale_details\n"
    )


def test_missing_meta_returns_nonzero_with_explicit_error(tmp_path: Path, capsys):
    meta = tmp_path / "missing.json"

    code = report_detection_summary.main(
        _args(meta, tmp_path / "output", tmp_path / "summary")
    )

    assert code != 0
    assert f"error: meta file not found: {meta}" in capsys.readouterr().err


def test_invalid_json_returns_nonzero_with_explicit_error(tmp_path: Path, capsys):
    meta = tmp_path / "invalid.json"
    meta.write_text("{not-json", encoding="utf-8")

    code = report_detection_summary.main(
        _args(meta, tmp_path / "output", tmp_path / "summary")
    )

    assert code != 0
    error = capsys.readouterr().err
    assert f"error: invalid JSON in meta file {meta}" in error
    assert "line 1, column 2" in error


def test_data_update_uses_detection_summary_module_without_inline_python():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/data_update.yml"
    ).read_text(encoding="utf-8")
    start = workflow.index("      - id: detection\n")
    end = workflow.index("\n      - id: quality\n", start)
    block = workflow[start:end]

    assert "uv run python -m ms_data.pipeline.report_detection_summary" in block
    assert "--meta cache/index_changed_meta.json" in block
    assert '--update-mode "${UPDATE_MODE}"' in block
    assert '--github-output "$GITHUB_OUTPUT"' in block
    assert '--step-summary "$GITHUB_STEP_SUMMARY"' in block
    assert "python - <<'PY'" not in block
    assert "json.loads" not in block
