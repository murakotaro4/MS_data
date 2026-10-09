"""実際のRelease公開Bashをghスタブで実行し、添付と失敗伝播を検証する。"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from workflow_contract import step_block, workflow_text

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="Ubuntu上で実行するworkflowのBashステップを検証する",
)

OPTIONAL_OUTPUTS = (
    "provenance_asset_path",
    "report_asset_path",
    "rollback_guard_asset_path",
    "official_overrides_audit_asset_path",
    "atwiki_quality_asset_path",
)


@pytest.mark.parametrize(
    ("optional_indexes", "existing_release", "upload_failure", "snapshot_exists"),
    [
        ((0, 1, 2, 3, 4), False, False, True),
        ((0, 2), False, False, True),
        ((), True, False, True),
        ((0, 1, 2, 3, 4), False, True, True),
        ((), True, False, False),
    ],
    ids=[
        "all-assets",
        "partial-assets",
        "existing-release",
        "upload-failure",
        "missing-snapshot",
    ],
)
def test_release_upload(
    tmp_path: Path,
    optional_indexes: tuple[int, ...],
    existing_release: bool,
    upload_failure: bool,
    snapshot_exists: bool,
) -> None:
    snapshot = tmp_path / "snapshot with spaces.tar.xz"
    if snapshot_exists:
        snapshot.touch()
    optional = [tmp_path / f"report {i}.json" for i in range(5)]
    for i in optional_indexes:
        optional[i].touch()

    block = step_block(
        workflow_text("post_merge_notify.yml"),
        start="- id: release",
        end="- id: mail_body",
    )
    script = textwrap.dedent(block.split("run: |\n", 1)[1])
    script = script.replace("${{ steps.report.outputs.report_date }}", "20261009")
    for name, path in zip(OPTIONAL_OUTPUTS, optional, strict=True):
        script = script.replace("${{ steps.report.outputs." + name + " }}", str(path))
    assert "${{" not in script

    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            """\
            import json, os, sys
            from pathlib import Path
            args = sys.argv[1:]
            with open(os.environ['CALLS'], 'a') as stream:
                stream.write(json.dumps(args) + '\\n')
            if args[:2] == ['release', 'view']:
                if '--json' in args:
                    print('https://example.test/release')
                else:
                    sys.exit(0 if os.environ['EXISTING'] == '1' else 1)
            elif args[:2] == ['release', 'upload']:
                paths = args[3:args.index('--repo')]
                if os.environ['FAIL_UPLOAD'] == '1' or not all(Path(p).is_file() for p in paths):
                    sys.exit(7)
            elif args[:2] != ['release', 'create']:
                sys.exit(8)
            """
        ),
        encoding="utf-8",
    )
    gh.chmod(0o755)
    calls_path = tmp_path / "calls.jsonl"
    output_path = tmp_path / "output"
    output_path.touch()
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
        "CALLS": str(calls_path),
        "EXISTING": str(int(existing_release)),
        "FAIL_UPLOAD": str(int(upload_failure)),
        "RELEASE_TAG": "test-release",
        "SOURCE_RUN_ID": "123",
        "ARTIFACT_NAME": "raw-snapshot",
        "SNAPSHOT_FILE": snapshot.name,
        "SNAPSHOT_ASSET_PATH": str(snapshot),
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(output_path),
    }
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    uploads = [args for args in calls if args[:2] == ["release", "upload"]]
    assert uploads == [
        ["release", "upload", "test-release", str(snapshot)]
        + [str(optional[i]) for i in optional_indexes]
        + ["--repo", "example/repo", "--clobber"]
    ]
    creates = [args for args in calls if args[:2] == ["release", "create"]]
    assert len(creates) == int(not existing_release)
    output = output_path.read_text()
    if upload_failure or not snapshot_exists:
        assert result.returncode == 7
        assert output == ""
        assert not any("--json" in args for args in calls)
    else:
        assert result.returncode == 0, result.stderr
        assert output == (
            "release_url=https://example.test/release\n"
            f"created={str(not existing_release).lower()}\n"
        )


def test_release_failure_does_not_force_notification() -> None:
    text = workflow_text("post_merge_notify.yml")
    notify = text[text.index("- id: mail_body") :]
    assert "always()" not in notify
    assert "failure()" not in notify
    assert notify.count("if: steps.release.outputs.created == 'true'") == 2
