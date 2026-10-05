from workflow_contract import step_block, workflow_text


def test_post_merge_notify_builds_mail_body_from_diff_and_guard_reports():
    text = workflow_text("post_merge_notify.yml")
    block = step_block(
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
    assert '--html-out "$html_path"' in block
    send = text[text.index("- name: Send merged msData mail") :]
    assert '--html-body "${{ steps.mail_body.outputs.html_path }}"' in send
    assert '--attach "msData.json"' in send


def test_data_update_no_change_mail_keeps_detection_and_guard_context_only():
    text = workflow_text("data_update.yml")
    block = step_block(
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
    assert '--html-out "$html_path"' in block
    send = step_block(
        text,
        start="- name: Send no-change mail",
        end="- name: Ensure pull request labels",
    )
    assert '--html-body "${{ steps.no_change_mail.outputs.html_path }}"' in send


def test_no_change_success_mail_runs_after_snapshot_and_uploads():
    text = workflow_text("data_update.yml")
    send = text.index("- name: Send no-change mail")
    for step in (
        "Generate reports and snapshot",
        "Validate generated update reports",
        "Upload raw snapshot artifact",
        "Upload operational reports",
        "Upload atwiki quality report",
    ):
        assert text.index(f"- name: {step}") < send
    # 先行処理の失敗時はGitHub Actionsの暗黙のsuccess()で送信を抑止する。
    block = text[send : text.index("- name: Ensure pull request labels", send)]
    assert "always()" not in block
    assert "failure()" not in block
    assert "env.DRY_RUN != 'true'" in block
