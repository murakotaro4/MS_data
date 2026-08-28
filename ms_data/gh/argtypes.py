"""auto-review CLI 引数の型変換と投稿者 login 定数。"""

GITHUB_ACTIONS_BOT = "github-actions[bot]"


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
