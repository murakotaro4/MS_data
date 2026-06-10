from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _workflow_text(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def _step_block(text: str, *, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def test_post_merge_notify_builds_mail_body_from_diff_and_guard_reports():
    text = _workflow_text("post_merge_notify.yml")
    block = _step_block(
        text,
        start="- id: mail_body",
        end="- name: Send merged msData mail",
    )

    assert "uv run python -m ms_data.reporting.build_update_mail_body" in block
    assert '--changed "true"' in block
    assert "--source-run-id" in block
    assert "--release-url" in block
    assert "--diff-path" in block
    assert "--rollback-guard-path" in block
    assert "--official-overrides-audit-path" in block


def test_data_update_no_change_mail_keeps_detection_and_guard_context_only():
    text = _workflow_text("data_update.yml")
    block = _step_block(
        text,
        start="- id: no_change_mail",
        end="- name: Send no-change mail",
    )

    assert "uv run python -m ms_data.reporting.build_update_mail_body" in block
    assert '--changed "false"' in block
    assert "--candidate-count" in block
    assert "--fast-path" in block
    assert "--age-coverage" in block
    assert "--fallback-reason" in block
    assert "--run-id" in block
    assert "--rollback-guard-path" in block
    assert "--official-overrides-audit-path" in block
    assert "--diff-path" not in block
