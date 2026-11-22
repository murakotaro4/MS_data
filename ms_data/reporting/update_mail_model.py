"""通知の判断・対応・監査根拠をHTMLとテキストで共有する表示モデル。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from ms_data.notify.subjects import (
    STATUS_ACTION,
    STATUS_CHANGED,
    STATUS_UNCHANGED,
    format_subject,
)
from ms_data.reporting.update_mail_audit import MailCard, build_audit_cards
from ms_data.reporting.update_mail_markdown import (
    _facts,
    _sections,
    enhancement_lines,
)

DETAIL_LABELS = {
    "追加レコード一覧": "レコード追加",
    "削除レコード一覧": "レコード削除",
    "変更レコード一覧": "変更",
}
MAIL_FIELDS = {
    "run_id": ("今回の実行ID", "", "今回のGitHub Actions実行を識別します。"),
    "source_run_id": (
        "データ更新元の実行ID",
        "",
        "取得・更新を行ったGitHub Actions実行を識別します。",
    ),
    "レコード数": (
        "レコード数",
        "",
        "1レコードは機体の1LV分。+は追加、-は削除、~は変更のレコード数です。",
    ),
}
# detect-changed の --min-age-coverage 既定値。検出時の実際の値が届かない場合だけ使う。
MIN_AGE_COVERAGE = Decimal("0.95")
NO_AUDIT_ACTION = "監査情報の添付なし。対応要否はこの通知だけでは判定できません。"
FALLBACK_REASONS = {
    "none": ("切替なし", "全件取得への切替はありません。"),
    "force_full": ("全件取得指定", "指定により全ページを再取得候補にしました。"),
    "missing_previous_provenance": (
        "前回実行情報なし",
        "前回の実行時刻が不明なため、全ページを再取得候補にしました。",
    ),
    "low_age_coverage": (
        "更新経過時間の読み取り不足",
        "一覧の更新経過時間を十分に読めず、全ページを再取得候補にしました。",
    ),
    "revalidate": (
        "週次再検証",
        "ページ更新時刻と前回取得時刻を比較して選定します。全件取得とは限りません。",
    ),
}


def _mail_field(key: str, value: str) -> str:
    """生の値を再計算せず、HTML・テキスト共通の説明を付ける。"""
    if key not in MAIL_FIELDS:
        return f"{key}: {value}"
    label, unit, description = MAIL_FIELDS[key]
    if label != key:
        label = f"{label}（{key}）"
    return f"{label}: {value}{unit} — {description}"


def _mail_line(line: str) -> str:
    if line.startswith("- ") and ": " in line:
        key, value = line[2:].split(": ", 1)
        return f"- {_mail_field(key, value)}"
    return line


@dataclass
class MailView:
    facts: dict[str, str]
    sections: dict[str, list[str]]
    action: str
    attention: list[MailCard]
    maintenance: list[MailCard]
    technical: list[str]
    evidence: list[MailCard]
    links: list[tuple[str, str]] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    condensed: bool = False


def _rate(value: str) -> tuple[str, Decimal | None]:
    """0〜1 の比率を百分率の表示と比較用の値にする。読めなければ値は None。"""
    try:
        rate = Decimal(value)
    except InvalidOperation:
        return value, None
    if rate.is_finite() and 0 <= rate <= 1:
        return f"{(rate * 100).normalize():f}%", rate
    return value, None


def _coverage(facts: dict[str, str]) -> tuple[str, Decimal | None]:
    """読み取り率の表示と、しきい値判定に使える値を返す。"""
    return _rate(facts.get("age_coverage", ""))


def _min_coverage(facts: dict[str, str]) -> tuple[str, Decimal]:
    """detect-changed が実際に使ったしきい値を返す。未指定・不正なら既定値。"""
    text, rate = _rate(facts.get("min_age_coverage", ""))
    if rate is None:
        return _rate(str(MIN_AGE_COVERAGE))[0], MIN_AGE_COVERAGE
    return text, rate


def _technical(facts: dict[str, str], *, has_detail_link: bool) -> list[str]:
    """平常時は取得の概要を1行にまとめ、選定方式の切替時だけ理由を添える。"""
    parts: list[str] = []
    if "candidate_count" in facts:
        parts.append(
            f"再取得候補 {facts['candidate_count']}ページ（URL重複排除後の選定数）"
        )
    if "age_coverage" in facts:
        parts.append(f"一覧の更新経過時間読み取り率 {_coverage(facts)[0]}")
    if "fast_path" in facts:
        value = {"true": "有効", "false": "無効"}.get(
            facts["fast_path"], facts["fast_path"]
        )
        parts.append(f"高速選定 {value}")
    items = ["取得の概要: " + "・".join(parts)] if parts else []
    if "fallback_reason" in facts:
        reason = facts["fallback_reason"]
        if reason != "none":
            label, meaning = FALLBACK_REASONS.get(
                reason, (reason, "再取得対象の選定理由です。")
            )
            items.append(f"選定方式: {label}（{reason}）。{meaning}")
    for key, value in facts.items():
        if key in {
            "実行日",
            "結果",
            "msData.json変更",
            "raw snapshot release",
            "msData.json download",
            "candidate_count",
            "fast_path",
            "age_coverage",
            "fallback_reason",
            "min_age_coverage",
        }:
            continue
        # 実行IDは詳細レポートのリンク先で分かるため、リンクがある場合は省く。
        if has_detail_link and key in {"run_id", "source_run_id"}:
            continue
        items.append(_mail_field(key, value))
    return items


def build_mail_view(body: str) -> MailView:
    sections = _sections(
        [line for line in body.splitlines() if not line.startswith("詳細: ")]
    )
    for heading in DETAIL_LABELS:
        if heading in sections:
            sections[heading] = enhancement_lines(sections[heading])
    facts = _facts(sections[""])
    audit = build_audit_cards(sections)
    attention = audit.attention
    if facts.get("msData.json変更") not in {"true", "false"}:
        attention.append(
            MailCard(
                "データ差分の有無を確認してください",
                ["差分の有無が通知にありません。詳細レポートを確認してください。"],
            )
        )
    if sections.get("既存の全体安全停止"):
        attention.append(MailCard("既存の全体安全停止", sections["既存の全体安全停止"]))
    coverage, rate = _coverage(facts)
    threshold_text, threshold = _min_coverage(facts)
    if rate is not None and rate < threshold:
        attention.append(
            MailCard(
                f"一覧の更新経過時間の読み取り率低下: {coverage}",
                [
                    f"しきい値 {threshold_text} を下回りました。"
                    "一覧ページの形式変更などで更新を見落としている可能性があります。",
                    "次の対応: 詳細レポートで一覧の取得結果と選定方式を確認してください。",
                ],
            )
        )
    # optional監査の未指定は失敗扱いにしない。安心文には監査の添付範囲を明示する。
    if attention:
        action = "対応が必要です。下の対象と次の対応を確認してください。"
    elif audit.has_summary:
        action = "今回のチェックで要確認の項目なし（添付された監査の範囲）。"
    else:
        action = NO_AUDIT_ACTION
    result = facts.get("結果", "")
    if (
        any(word in result for word in ("失敗", "エラー", "対応要", "停止"))
        and not attention
    ):
        attention.append(
            MailCard(
                "実行結果を確認してください",
                [result, "詳細レポートまたは実行ログを確認してください。"],
            )
        )
        action = "対応が必要です。実行結果と監査レポートを確認してください。"
    # msData.json は添付せず、Release アセットへのリンクで渡す。
    links = [
        (label, facts[key])
        for label, key in (
            ("msData.json（今回のデータ）", "msData.json download"),
            ("取得元・差分レポート", "raw snapshot release"),
        )
        if key in facts
    ]
    details = [
        ("詳細レポート", line[4:])
        for line in body.splitlines()
        if line.startswith("詳細: ")
    ]
    links.extend(details)
    return MailView(
        facts,
        sections,
        action,
        attention,
        audit.maintenance,
        _technical(facts, has_detail_link=bool(details)),
        audit.evidence,
        links=list(dict.fromkeys(links)),
    )


_RECORD_COUNTS = re.compile(r"レコード数: \d+ → \d+ \| \+(\d+) -(\d+) ~(\d+)")


def _attention_summary(cards: list[MailCard]) -> str:
    """件名用に、最初の対応種別と残りの種別数を短く表す。"""
    groups = [card for card in cards if card.target is None] or cards
    head = groups[0].title.replace(": ", " ")
    rest = len(groups) - 1
    return f"{head} ほか{rest}種" if rest else head


def mail_subject(view: MailView) -> str:
    """本文と同じ判定から `【状態】msData 種類 日付（要点）` の件名を作る。"""
    facts = view.facts
    result = facts.get("結果", "")
    changed = facts.get("msData.json変更")
    if "部分保留" in result:
        kind = "部分保留"
    elif result == "マージ済み":
        kind = "更新反映"
    elif changed == "false":
        kind = "定期チェック"
    else:
        kind = "定期更新"
    date = facts.get("実行日", "")
    if view.attention:
        return format_subject(
            STATUS_ACTION, kind, label=date, detail=_attention_summary(view.attention)
        )
    if view.action == NO_AUDIT_ACTION:
        # 対応要否を判定できない通知は、問題なしと読まれないよう要対応にする。
        return format_subject(
            STATUS_ACTION, kind, label=date, detail="監査情報の添付なし"
        )
    if changed == "true":
        counts = _RECORD_COUNTS.search("\n".join(view.sections.get("差分サマリ", [])))
        detail = ""
        if counts:
            added, removed, updated = counts.groups()
            detail = "・".join(
                f"{name}{value}"
                for name, value in (
                    ("追加", added),
                    ("変更", updated),
                    ("削除", removed),
                )
                if value != "0"
            )
        return format_subject(STATUS_CHANGED, kind, label=date, detail=detail)
    return format_subject(STATUS_UNCHANGED, kind, label=date)


def change_statement(facts: dict[str, str]) -> str:
    value = facts.get("msData.json変更")
    if value == "false":
        return "公開データの変更なし"
    if value == "true":
        return (
            "公開データの変更あり"
            if facts.get("結果") == "マージ済み"
            else "更新候補に差分あり"
        )
    return "データ差分の有無を確認できません"


def localize_mail_body(body: str, *, view: MailView | None = None) -> str:
    """同じ表示モデルから、結果・対応・根拠・技術情報の順のテキストを生成する。"""
    if view is None:
        # 最終HTMLのUTF-8サイズで選んだ表示を、テキストにも共有する。
        from ms_data.reporting.update_mail_html import prepare_update_mail

        view, _ = prepare_update_mail(body)
    lines = [
        "msData 定期更新の確認結果",
        "",
        f"実行日: {view.facts.get('実行日', '')}",
        f"結果: {view.facts.get('結果', '')}",
        change_statement(view.facts),
        view.action,
    ]
    lines.extend(view.notices)
    lines.extend(f"{label}: {url}" for label, url in view.links)

    def append_cards(title: str, cards: list[MailCard]) -> None:
        if view.condensed:
            from ms_data.reporting.update_mail_display import group_card_actions

            cards = group_card_actions(cards)
        if cards:
            lines.extend(["", f"## {title}"])
        for card in cards:
            lines.extend(["", f"### {card.title}", *card.lines])
            lines.extend(f"- {key}: {value}" for key, value in card.values)

    append_cards("要確認の対象と次の対応", view.attention)
    for heading in ("差分サマリ", "変更内容", *DETAIL_LABELS):
        if heading in view.sections:
            lines.extend(["", f"## {heading}", *view.sections[heading]])
    append_cards("補正値の維持と期限", view.maintenance)
    if view.technical:
        lines.extend(["", "## 技術情報", *view.technical])
    append_cards("取得証拠の詳細", view.evidence)
    used = {
        "",
        "差分サマリ",
        "変更内容",
        *DETAIL_LABELS,
        "巻き戻りガード",
        "official_overrides監査",
        "取得元スロット監査",
        "部分保留エラー・補正証拠",
        *[
            heading
            for heading in view.sections
            if heading.startswith(("ガード / ", "登録補正 / "))
        ],
    }
    for heading, section in view.sections.items():
        if heading not in used:
            lines.extend(["", f"## {heading}", *section])
    return "\n".join(lines).rstrip() + "\n"
