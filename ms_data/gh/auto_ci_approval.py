"""定期データ PR の CI 実行承認。レビュー・CI 成功判定は緩和しない。"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ms_data.gh.argtypes import GITHUB_ACTIONS_BOT, ReviewDeps
from ms_data.gh.gh_json import gh_api_json
from ms_data.gh.outputs import write_github_output
from ms_data.gh.pr_payload import (
    HEAD_REF_DATE_RE,
    base_ref,
    head_ref,
    head_repo_full_name,
    head_sha,
    source_run_id_from_body,
)


def _get(endpoint: str, deps: ReviewDeps, *, paginate: bool = False) -> Any:
    return gh_api_json(endpoint, runner=deps.run_gh, paginate=paginate)


def _trusted_pull(pull: Any, repo: str, ref: str, sha: str) -> bool:
    if not isinstance(pull, dict):
        return False
    return (
        pull.get("state") == "open"
        and pull.get("draft") is False
        and ((pull.get("user") or {}).get("login") == GITHUB_ACTIONS_BOT)
        and (base_ref(pull) == "main")
        and (head_repo_full_name(pull) == repo)
        and (head_ref(pull) == ref)
        and (head_sha(pull) == sha)
    )


def _data_files_only(files: Any, date: str) -> bool:
    if not isinstance(files, list) or not files:
        return False
    prefix = f"reports/{date[:4]}/{date[4:6]}/"
    extensions = {
        "diff_msdata": "md",
        "provenance": "json",
        "rollback_guard": "md",
        "field_completeness": "md",
        "official_overrides_audit": "md",
        "atwiki_quality": "json",
        "source_slot_audit": "md",
    }
    allowed = {"msData.json"} | {
        f"{prefix}{stem}_{date}.{extension}" for stem, extension in extensions.items()
    }
    has_data = any(
        (isinstance(f, dict) and f.get("filename") == "msData.json" for f in files)
    )
    return has_data and all(
        (
            isinstance(f, dict)
            and f.get("filename") in allowed
            and (f.get("status") in {"added", "modified"})
            for f in files
        )
    )


def approve_and_wait_ci(
    *,
    repo: str,
    pr_number: str,
    ref: str,
    sha: str,
    run: dict[str, Any],
    deps: ReviewDeps,
    check_only: bool = False,
) -> str:
    """厳格な対象検証後に一度だけ承認し、最大5分CI成功を待つ。"""
    match = HEAD_REF_DATE_RE.fullmatch(ref)
    if not match or not pr_number.isdecimal():
        return "ci_not_success"
    date = match.group(1)
    try:
        datetime.strptime(date, "%Y%m%d")
        pull = _get(f"repos/{repo}/pulls/{pr_number}", deps)
        if not _trusted_pull(pull, repo, ref, sha):
            return "ci_approval_untrusted"
        files = _get(f"repos/{repo}/pulls/{pr_number}/files", deps, paginate=True)
        if not _data_files_only(files, date) or len(files) != pull.get("changed_files"):
            return "ci_approval_untrusted"
        source_id = source_run_id_from_body(pull.get("body"))
        if not source_id:
            return "ci_approval_untrusted"
        source_paths = {
            ".github/workflows/data_update.yml",
            ".github/workflows/data_update.yml@main",
            ".github/workflows/data_update.yml@refs/heads/main",
        }
        for attempt in range(9):
            source = _get(f"repos/{repo}/actions/runs/{source_id}", deps)
            if (
                not isinstance(source, dict)
                or str(source.get("id")) != source_id
                or source.get("path") not in source_paths
                or source.get("event") not in {"schedule", "workflow_dispatch"}
                or source.get("head_branch") != "main"
                or (source.get("repository") or {}).get("full_name") != repo
            ):
                return "ci_approval_untrusted"
            if source.get("status") == "completed":
                if source.get("conclusion") != "success":
                    return "ci_approval_untrusted"
                break
            if source.get("status") not in {"queued", "in_progress", "waiting"}:
                return "ci_approval_untrusted"
            if attempt == 8:
                return "ci_source_incomplete"
            deps.clock.sleep(15)
        run_id = run["id"]
        endpoint = f"repos/{repo}/actions/runs/{run_id}"
        current = _get(endpoint, deps)
        if not _same_ci(current, repo, ref, sha) or current.get("id") != run_id:
            return "ci_target_mismatch"
        if (
            current.get("status") != "completed"
            or current.get("conclusion") != "action_required"
        ):
            return "ci_incomplete"
        jobs = _get(f"{endpoint}/jobs", deps)
        if not isinstance(jobs, dict) or jobs.get("total_count") != 0:
            return "ci_approval_untrusted"
        fresh_pull = _get(f"repos/{repo}/pulls/{pr_number}", deps)
        if not _trusted_pull(fresh_pull, repo, ref, sha):
            return "head_sha_mismatch"
        if check_only:
            return ""
        print(f"Approving data PR CI: pr={pr_number} run_id={run_id}")
        try:
            deps.run_gh(["gh", "api", f"{endpoint}/approve", "-X", "POST"])
        except subprocess.CalledProcessError:
            print(
                f"CI approval denied: https://github.com/{repo}/actions/runs/{run_id}. Approval API requires Actions write and GitHub permission to approve this run; a repository writer must approve workflows if the token is rejected."
            )
            return "ci_approval_denied"
        for _ in range(20):
            deps.clock.sleep(15)
            current = _get(endpoint, deps)
            if not _same_ci(current, repo, ref, sha) or current.get("id") != run_id:
                return "ci_target_mismatch"
            if current.get("status") == "completed":
                conclusion = current.get("conclusion")
                if conclusion == "success":
                    return ""
                if conclusion != "action_required":
                    return "ci_not_success"
        return "ci_approval_timeout"
    except (
        subprocess.CalledProcessError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ):
        return "ci_unavailable"


def _same_ci(run: Any, repo: str, ref: str, sha: str) -> bool:
    return (
        isinstance(run, dict)
        and run.get("event") == "pull_request"
        and (run.get("head_sha") == sha)
        and (run.get("head_branch") == ref)
        and isinstance(run.get("path"), str)
        and (run["path"].split("@", 1)[0] == ".github/workflows/ci.yml")
        and ((run.get("head_repository") or {}).get("full_name") == repo)
        and ((run.get("repository") or {}).get("full_name") == repo)
        and ((run.get("actor") or {}).get("login") == GITHUB_ACTIONS_BOT)
    )


def main(argv: list[str] | None = None, *, deps: ReviewDeps | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.github_output is not None:
        write_github_output(args.github_output, {"eligible": "false"})
    deps = deps or ReviewDeps.default()
    try:
        run = _get(f"repos/{args.repo}/actions/runs/{args.run_id}", deps)
        if not isinstance(run, dict) or run.get("id") != args.run_id:
            return 1
        ref, sha = (run.get("head_branch"), run.get("head_sha"))
        if not isinstance(ref, str) or not isinstance(sha, str):
            return 1
        if not _same_ci(run, args.repo, ref, sha):
            print("CI approval skipped: target is not a same-repository bot CI")
            return 0
        if (
            run.get("status") != "completed"
            or run.get("conclusion") != "action_required"
        ):
            print("CI approval skipped: run is no longer awaiting approval")
            return 0
        query = urlencode({"state": "open", "head": f"{args.repo.split('/')[0]}:{ref}"})
        pulls = _get(f"repos/{args.repo}/pulls?{query}", deps, paginate=True)
        if not isinstance(pulls, list):
            return 1
        targets = [p for p in pulls if _trusted_pull(p, args.repo, ref, sha)]
        if len(targets) != 1 or type(targets[0].get("number")) is not int:
            print("CI approval skipped: no unique eligible data PR")
            return 0
        reason = approve_and_wait_ci(
            repo=args.repo,
            pr_number=str(targets[0]["number"]),
            ref=ref,
            sha=sha,
            run=run,
            deps=deps,
            check_only=args.check_only,
        )
        if args.check_only and args.github_output is not None:
            write_github_output(
                args.github_output, {"eligible": "true" if not reason else "false"}
            )
        print(
            f"CI approval result: run_id={args.run_id} reason={reason or 'ci_success'}"
        )
        return 1 if reason else 0
    except (
        subprocess.CalledProcessError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ):
        print("CI approval failed: could not validate GitHub API response")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
