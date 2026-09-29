from workflow_contract import assert_absent, assert_contains, workflow_step


def test_post_merge_notify_builds_mail_body_from_diff_and_guard_reports():
    block = workflow_step(
        "post_merge_notify.yml",
        start="- id: mail_body",
        end="- name: Send merged msData mail",
    )

    assert_contains(
        block,
        [
            "uv run python -m ms_data.reporting.build_update_mail_body",
            '--changed "true"',
            "--source-run-id",
            "--release-url",
            "--diff-path",
            "--rollback-guard-path",
            "--official-overrides-audit-path",
        ],
    )


def test_data_update_no_change_mail_keeps_detection_and_guard_context_only():
    block = workflow_step(
        "data_update.yml",
        start="- id: no_change_mail",
        end="- name: Send no-change mail",
    )

    assert_contains(
        block,
        [
            "uv run python -m ms_data.reporting.build_update_mail_body",
            '--changed "false"',
            "--candidate-count",
            "--fast-path",
            "--age-coverage",
            "--fallback-reason",
            "--run-id",
            "--rollback-guard-path",
            "--official-overrides-audit-path",
        ],
    )
    assert_absent(block, ["--diff-path"])
