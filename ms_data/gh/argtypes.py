"""auto-review CLI 引数の型変換と IO 依存。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

GITHUB_ACTIONS_BOT = "github-actions[bot]"


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class ReviewDeps:
    """auto-review フローの差し替え可能な IO seam。"""

    client: Callable[[str], Any]
    clock: Clock
    run_gh: Callable[..., str]
    collect_metrics: Callable[..., dict[str, Any]]
    ensure_comment: Callable[..., tuple[str, str, bool]]
    notify_stop: Callable[..., int]
    run_url: Callable[[], str]

    @classmethod
    def default(cls) -> ReviewDeps:
        """本番実装を遅延 import し、循環 import を避けて構成する。"""
        from ms_data.gh import auto_review_merge

        return cls(
            client=auto_review_merge.GitHubClient,
            clock=auto_review_merge.time,
            run_gh=auto_review_merge.run_gh,
            collect_metrics=auto_review_merge.collect_review_metrics,
            ensure_comment=auto_review_merge.ensure_review_comment,
            notify_stop=auto_review_merge.notify_review_stop,
            run_url=auto_review_merge.github_run_url,
        )


def _positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _bool_text(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_or_none(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _allowed_trigger_logins(pat_login: str) -> set[str]:
    logins = {GITHUB_ACTIONS_BOT}
    login = pat_login.strip()
    if login:
        logins.add(login)
    return logins
