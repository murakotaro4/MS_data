"""通知メール件名の共通形式（`【状態】msData 種類 識別子（要点）`）を組み立てる。"""

from __future__ import annotations

STATUS_ACTION = "要対応"
STATUS_CHANGED = "変更あり"
STATUS_UNCHANGED = "変更なし"
STATUS_FAILED = "失敗"
STATUSES = frozenset({STATUS_ACTION, STATUS_CHANGED, STATUS_UNCHANGED, STATUS_FAILED})
MAX_DETAIL_CHARS = 40


def format_subject(status: str, kind: str, *, label: str = "", detail: str = "") -> str:
    """状態タグ・種類・日付や PR 番号などの識別子・要点から件名を作る。

    要点は空白を詰め、受信一覧で読める長さに切り詰める。カッコは全角に統一する。
    """

    if status not in STATUSES:
        raise ValueError(f"unsupported status: {status}")
    subject = " ".join(part for part in (f"【{status}】msData", kind, label) if part)
    detail = " ".join(detail.split())
    if len(detail) > MAX_DETAIL_CHARS:
        detail = detail[: MAX_DETAIL_CHARS - 1] + "…"
    if detail:
        subject += f"（{detail}）"
    return subject
