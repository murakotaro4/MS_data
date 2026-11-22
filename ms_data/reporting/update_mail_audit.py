"""通知に添付された監査サマリ・明細を照合し、対応カードへ変換する。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ms_data.reporting.update_mail_markdown import _cells, _count, _facts, _plain

AUDIT_SUMMARY_HEADINGS = (
    "巻き戻りガード",
    "official_overrides監査",
    "取得元スロット監査",
)
SOURCE_EVIDENCE_HEADING = "登録補正 / 取得証拠"
SOURCE_HOLD_HEADING = "部分保留エラー・補正証拠"


@dataclass
class MailCard:
    title: str
    lines: list[str] = field(default_factory=list)
    values: list[tuple[str, str]] = field(default_factory=list)
    compact: bool = False
    target: tuple[str, str] | None = None


_STATUS_ACTIONS = {
    "protected_rollback": "更新停止対象です。監査の変更前・取得値と登録補正を照合してください。",
    "numeric_decrease": "監視対象の整数項目（機体＋LV＋項目）の確認候補です。数値低下だけでは誤りと確定できません。取得元と変更前後を確認してください。",
    "mixed_level_change": "機体＋項目の組数です。他の項目数と合計せず、LV別の増減を確認してください。",
    "source_changed": "採用値または取得値が登録補正の想定と異なります。取得証拠を照合して登録補正を見直してください。",
    "upstream_current": "登録補正の撤去対象です。取得証拠と独立した次回確認結果を確認して撤去してください。",
    "review_due": "再確認期限に到達しました（撤去判断期限の対象を除く）。取得元を再確認してください。確認完了数ではありません。",
    "remove_due": "撤去判断期限に到達しました。取得証拠と次回確認結果を照合して存続・撤去を判断してください。撤去完了数ではありません。",
    "missing_current": "採用値が監査で見つかりません。公開データと登録補正を確認してください。",
    "source_hold_unverified_previous": "未確認の公開済み値を保持しています。取得元と監査証拠を確認してください。",
    "held_record_count": "機体＋LV全体の更新候補を保留しました。取得元と監査の原値・比較値を確認してください。他の正常候補は通常レビューを継続します。",
    "previous_unverified_count": "正常な前値がなく、未確認の公開済み値を保持しています。監査証拠を確認してください。",
    "期限到達値の取得証拠不足": "今回の取得証拠が不足しています。再取得・解析結果を確認してから撤去を判断してください。",
}
_STATUS_LABELS = {
    "protected_rollback": ("更新停止対象の巻き戻り", "項目"),
    "numeric_decrease": ("数値低下の確認候補", "項目"),
    "mixed_level_change": ("LV間で増減が混在する候補", "組"),
    "protected_by_override": ("補正値を維持した項目", "項目"),
    "upstream_current": ("取得元が補正値と一致した項目", "項目"),
    "source_changed": ("補正の想定と異なる項目", "項目"),
    "review_due": ("登録補正の再確認期限到達", "項目"),
    "remove_due": ("登録補正の撤去判断期限到達", "項目"),
    "missing_current": ("採用値が見つからない項目", "項目"),
    "source_hold_unverified_previous": ("未確認の公開済み値を保持した項目", "項目"),
    "held_record_count": ("LV単位の部分保留", "レコード"),
    "previous_unverified_count": ("未確認の前値を保持した数", "レコード"),
    "approved_record_count": ("承認済み補正を採用した数", "レコード"),
    "fallback_corrected_record_count": (
        "前値を承認済み補正で修復して保持した数",
        "レコード",
    ),
    "already_protected": ("今回の取得証拠なし・既存の補正値を維持", "項目"),
    "current_matches_override": ("今回の取得証拠なし・採用値が登録補正と一致", "項目"),
    "期限到達値の取得証拠不足": ("期限対象の取得証拠不足", "項目"),
}
_OVERRIDE_STATUSES = {
    "protected_rollback",
    "source_changed",
    "upstream_current",
    "protected_by_override",
    "already_protected",
    "current_matches_override",
    "missing_current",
    "source_hold_unverified_previous",
}
_EVIDENCE_STATES = {
    "not_fetched": "今回未取得",
    "fetch_failed": "取得失敗",
    "parse_failed": "解析失敗",
    "value_missing": "解析後の値欠損",
    "cached_only": "キャッシュのみ",
    "not_parsed": "未解析",
    "match": "今回取得・補正値と一致",
    "mismatch": "今回取得・補正値と不一致",
}
_SOURCE_ACTIONS = {
    "retained_previous": "更新候補を保留し、前値を保持",
    "retained_previous_with_approved_correction": "更新候補を保留し、承認済み補正で前値を修復して保持",
    "previous_unverified_retained": "正常な前値なし・未確認の公開済み値を保持（要対応）",
    "skipped_new_record": "新規レコードの追加を保留",
    "approved_override": "承認済み補正を採用",
    "global_safety_stop_not_quarantined": "既存の全体安全停止（部分保留処理なし）",
}
_SOURCE_OK = {"ok", "approved_correction"}
_SOURCE_COUNT_ACTIONS = {
    "held_record_count": {
        "retained_previous",
        "retained_previous_with_approved_correction",
        "previous_unverified_retained",
        "skipped_new_record",
    },
    "approved_record_count": {"approved_override"},
    "fallback_corrected_record_count": {"retained_previous_with_approved_correction"},
    "previous_unverified_count": {"previous_unverified_retained"},
}
_DETAIL_FOR_STATUS = {
    "protected_rollback": ("ガード / ブロック対象", "登録補正 / 要確認"),
    "numeric_decrease": ("ガード / 数値低下の注意候補",),
    "mixed_level_change": ("ガード / LV間で増減が混在した候補",),
    "source_changed": ("登録補正 / 要確認",),
    "upstream_current": ("登録補正 / 撤去候補",),
    "review_due": ("登録補正 / 期限確認",),
    "remove_due": ("登録補正 / 期限確認",),
    "missing_current": ("登録補正 / 要確認",),
    "source_hold_unverified_previous": ("登録補正 / 要確認",),
    "held_record_count": ("部分保留エラー・補正証拠",),
    "previous_unverified_count": ("部分保留エラー・補正証拠",),
    "期限到達値の取得証拠不足": ("登録補正 / 期限確認",),
}
_DETAIL_COUNTS = {
    "巻き戻りガード": {
        "protected_rollback": ("ガード / ブロック対象", "種別"),
        "numeric_decrease": ("ガード / 数値低下の注意候補", "種別"),
        "mixed_level_change": ("ガード / LV間で増減が混在した候補", ""),
    },
    "official_overrides監査": {
        "protected_by_override": ("登録補正 / 適用中", "状態"),
        "upstream_current": ("登録補正 / 撤去候補", "状態"),
        "protected_rollback": ("登録補正 / 要確認", "状態"),
        "source_changed": ("登録補正 / 要確認", "状態"),
        "missing_current": ("登録補正 / 要確認", "状態"),
        "source_hold_unverified_previous": ("登録補正 / 要確認", "状態"),
        "review_due": ("登録補正 / 期限確認", "期限状態"),
        "remove_due": ("登録補正 / 期限確認", "期限状態"),
    },
}


def _source_summary_issue(
    summary: dict[str, str], rows: list[dict[str, str]]
) -> MailCard | None:
    """機体＋LV単位の件数・状態・明細を照合し、欠損を正常と見なさない。"""
    counts = {key: _count(summary.get(key)) for key in _SOURCE_COUNT_ACTIONS}
    status = summary.get("status")
    if status not in _SOURCE_OK | {"partial_hold"} or any(
        count is None for count in counts.values()
    ):
        # 未知状態・欠損・不正な数値はサマリ項目の表示時に別途警告する。
        return None
    expected_status = (
        "partial_hold"
        if counts["held_record_count"]
        else "approved_correction"
        if counts["approved_record_count"]
        else "ok"
    )
    issues = []
    if status != expected_status:
        issues.append(f"状態: {status} / 件数から期待される状態: {expected_status}")
    actions_by_record: dict[str, set[str]] = {}
    for row in rows:
        name, action = row.get("MS名", ""), row.get("処置", "")
        if not name or action not in (
            _SOURCE_COUNT_ACTIONS["held_record_count"] | {"approved_override"}
        ):
            issues.append("対象名または処置が読み取れない明細があります。")
            break
        actions_by_record.setdefault(name, set()).add(action)
    if any(len(actions) != 1 for actions in actions_by_record.values()):
        issues.append("同じ機体＋LVに複数の処置が記録されています。")
    for key, actions in _SOURCE_COUNT_ACTIONS.items():
        actual = sum(
            bool(record_actions & actions)
            for record_actions in actions_by_record.values()
        )
        if counts[key] != actual:
            issues.append(
                f"{_STATUS_LABELS[key][0]}: サマリ {counts[key]} / 明細 {actual}"
            )
    if issues:
        return MailCard(
            "取得元スロット監査の整合性を確認",
            [
                "監査の状態・件数・対象明細が整合していません。監査レポートを確認してください。",
                *issues,
            ],
        )
    return None


def _detail_count_issues(
    summaries: dict[str, dict[str, str]],
    parsed: dict[str, list[dict[str, str]]],
    sections: dict[str, list[str]],
) -> list[MailCard]:
    issues = []
    for summary_heading, specs in _DETAIL_COUNTS.items():
        summary = summaries.get(summary_heading, {})
        has_evidence = summary_heading == "official_overrides監査" and (
            "対象値" in summary or "登録補正 / 取得証拠" in sections
        )
        evidence_targets = {
            (row.get("MS名"), row.get("項目"))
            for row in parsed.get("登録補正 / 取得証拠", [])
        }
        # 旧通知のサマリだけの場合、明細未添付を維持欄で明示する。
        # 明細または対象総数のある監査では、各状態の対象をすべて照合する。
        if "対象値" not in summary and not any(
            heading in sections for heading, _ in specs.values()
        ):
            continue
        for status, (heading, column) in specs.items():
            count = _count(summary.get(status))
            if count is None:
                continue
            rows = [
                row
                for row in parsed.get(heading, [])
                if not column or row.get(column) == status
            ]
            targets = {(row.get("MS名"), row.get("項目")) for row in rows}
            valid = all(name and field for name, field in targets)
            actual = len(targets)
            if status == "mixed_level_change":
                groups = {row.get("機体・項目の組", "") for row in rows}
                valid = valid and all(groups)
                actual = len(groups)
            omitted = 0
            if status == "numeric_decrease":
                omitted = sum(
                    int(match[1])
                    for line in sections.get(heading, [])
                    if (match := re.fullmatch(r"- 省略: (\d+) 件", line))
                )
            if not valid or len(targets) != len(rows) or actual + omitted != count:
                label, unit = _STATUS_LABELS[status]
                issues.append(
                    MailCard(
                        f"{heading}: 明細を確認",
                        [
                            f"{label}: サマリ {count}{unit} / 一意な明細 {actual}{unit}。",
                            "状態別の件数・対象明細が整合していません。重複・不足・対象名を監査レポートで確認してください。",
                        ],
                    )
                )
            if has_evidence and not targets <= evidence_targets:
                issues.append(
                    MailCard(
                        f"{heading}: 取得証拠の対象を確認",
                        [
                            "対象明細と取得証拠の対象が一致しません。この通知では対象の今回取得値を確認できません。",
                            "監査レポートの機体・LV・項目と取得証拠を照合してください。",
                        ],
                    )
                )
        if summary_heading == "official_overrides監査":
            issues.extend(_override_target_issues(summary, parsed, has_evidence))
    return issues


def _override_target_issues(
    summary: dict[str, str],
    parsed: dict[str, list[dict[str, str]]],
    has_evidence: bool,
) -> list[MailCard]:
    """状態表は相互排他。通常未取得の2状態には専用明細がない。"""
    counts_by_target: dict[tuple[str, str], int] = {}
    for heading in ("登録補正 / 適用中", "登録補正 / 撤去候補", "登録補正 / 要確認"):
        for row in parsed.get(heading, []):
            target = (row.get("MS名", ""), row.get("項目", ""))
            counts_by_target[target] = counts_by_target.get(target, 0) + 1
    conflicts = sorted(
        f"{name or '対象不明'} / {field or '項目不明'}"
        for (name, field), count in counts_by_target.items()
        if count > 1
    )
    lines = []
    if conflicts:
        lines.extend(["状態別明細の対象が重複しています。", *conflicts])
    if has_evidence:
        evidence_targets = {
            (row.get("MS名", ""), row.get("項目", ""))
            for row in parsed.get("登録補正 / 取得証拠", [])
        }
        # already_protected/current_matches_overrideは専用状態表を出さない。
        unlisted = [
            _count(summary.get(status))
            for status in ("already_protected", "current_matches_override")
        ]
        targets = set(counts_by_target)
        if not targets <= evidence_targets or (
            all(count is not None for count in unlisted)
            and len(evidence_targets - targets)
            != sum(count for count in unlisted if count is not None)
        ):
            lines.append(
                "状態別明細の対象全体と取得証拠が整合していません。専用明細のない通常未取得対象を含め、欠落・状態の重複を確認してください。"
            )
    if lines:
        return [
            MailCard(
                "登録補正の状態別対象を確認",
                [*lines, "監査レポートで対象と状態を照合してください。"],
            )
        ]
    return []


def _audit_tables(lines: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """監査の表を検証し、未知形式・壊れた行を捨てず別枠に残す。"""
    rows: list[dict[str, str]] = []
    remainder: list[str] = []
    headers: list[str] = []
    group = ""
    for index, line in enumerate(lines):
        if line.startswith("### "):
            group = _plain(line[4:])
            continue
        if not line.startswith("|"):
            if line.strip() and line != "該当なし":
                remainder.append(line)
            continue
        if re.fullmatch(r"[| :\-]+", line):
            continue
        values = _cells(line)
        if index + 1 < len(lines) and re.fullmatch(r"[| :\-]+", lines[index + 1]):
            headers = values
        elif (
            len(headers) != len(values)
            or len(set(headers)) != len(headers)
            or "MS名" not in headers
        ):
            remainder.append(line)
        elif (values[0] == "なし" and not any(values[1:])) or (
            values[headers.index("MS名")] == "なし"
            and not any(v for i, v in enumerate(values) if headers[i] != "MS名")
        ):
            continue
        else:
            row = dict(zip(headers, values, strict=True))
            if group:
                row["機体・項目の組"] = group
            rows.append(row)
    return rows, remainder


@dataclass
class AuditCards:
    """監査から作ったカード。追加順が通知の表示順になる。"""

    attention: list[MailCard] = field(default_factory=list)
    maintenance: list[MailCard] = field(default_factory=list)
    evidence: list[MailCard] = field(default_factory=list)
    has_summary: bool = False


_ROW_LOCATION_KEYS = {"URL", "WikiURL", "試行時刻", "取得時刻", "HTTP"}
_ROW_EVIDENCE_KEYS = {
    "種別",
    "状態",
    "期限状態",
    "前値の承認修復",
    "前値状態",
    "stale",
    "機体・項目の組",
}
_ROW_VALUE_LABELS = {
    "override": "登録補正値",
    "stale": "既知の旧値",
    "現在値": "採用値",
    "review_after": "再確認期限",
    "remove_after": "撤去判断期限",
    "変更後": "更新候補値",
}
_REQUIRED_SUMMARY_KEYS = {
    "巻き戻りガード": ("protected_rollback", "numeric_decrease", "mixed_level_change"),
    "official_overrides監査": ("review_due", "remove_due"),
    "取得元スロット監査": ("status", *_SOURCE_COUNT_ACTIONS),
}


def _parse_detail_sections(
    sections: dict[str, list[str]], cards: AuditCards
) -> dict[str, list[dict[str, str]]]:
    """監査明細の表を読み、読み取れない行は原文のまま要確認へ回す。"""
    parsed: dict[str, list[dict[str, str]]] = {}
    for heading, lines in sections.items():
        if (
            heading.startswith(("ガード / ", "登録補正 / "))
            or heading == SOURCE_HOLD_HEADING
        ):
            parsed[heading], remainder = _audit_tables(lines)
            if remainder:
                cards.attention.append(
                    MailCard(
                        f"監査明細の確認: {heading}",
                        ["監査の原文を確認してください。", *remainder],
                    )
                )
    return parsed


def _read_summaries(
    sections: dict[str, list[str]], cards: AuditCards
) -> dict[str, dict[str, str]]:
    """監査サマリの箇条書きを読み、重複・読み取り不能を要確認へ回す。"""
    summaries = {
        heading: _facts(sections[heading])
        for heading in AUDIT_SUMMARY_HEADINGS
        if heading in sections
    }
    for heading, values in summaries.items():
        bullets = [line for line in sections[heading] if line.startswith("- ")]
        if len(bullets) != len(values):
            cards.attention.append(
                MailCard(
                    f"{heading}: 監査サマリの形式を確認",
                    ["重複または読み取れない項目があります。", *bullets],
                )
            )
    return summaries


def _reconcile_override_total(
    summaries: dict[str, dict[str, str]],
    source_rows: list[dict[str, str]],
    cards: AuditCards,
) -> None:
    """登録補正の対象総数・状態件数・取得証拠を突き合わせる。

    監査状態は疎なCounter。総数と一意な取得証拠が揃った時だけ、省略された状態を
    0件として `summaries` に補う。
    """
    override = summaries.get("official_overrides監査", {})
    status_counts = {
        key: _count(value)
        for key, value in override.items()
        if key not in {"対象値", "review_due", "remove_due", "期限到達値の取得証拠不足"}
    }
    unique_rows = {(row.get("MS名"), row.get("項目")) for row in source_rows}
    total = _count(override.get("対象値"))
    known_total = sum(value for value in status_counts.values() if value is not None)
    counts_readable = all(value is not None for value in status_counts.values())
    evidence_matches = (
        total is not None
        and counts_readable
        and known_total == total
        and len(unique_rows) == len(source_rows) == total
        and all(name and key for name, key in unique_rows)
    )
    if evidence_matches and all(key in _OVERRIDE_STATUSES for key in status_counts):
        summaries["official_overrides監査"] = {
            **dict.fromkeys(_OVERRIDE_STATUSES, "0"),
            **override,
        }
    elif "対象値" in override and not evidence_matches:
        cards.attention.append(
            MailCard(
                "登録補正の監査情報を確認してください",
                [
                    "対象値・状態件数・取得証拠が整合していません。監査レポートを確認してください。"
                ],
            )
        )


def _summary_item_card(
    key: str, value: str, parsed: dict[str, list[dict[str, str]]], cards: AuditCards
) -> None:
    """サマリ1項目を、対応が要るものは要確認へ、維持の報告は維持欄へ振り分ける。"""
    count = _count(value)
    if count == 0 and key in _STATUS_LABELS:
        return
    label, unit = _STATUS_LABELS.get(key, (key, ""))
    card = MailCard(f"{label}: {value}{unit}")
    if count is None or key not in _STATUS_LABELS:
        if count is None:
            card.title = f"{label}: 未確認"
            card.lines.append(f"監査原文: {key}: {value}")
        card.lines.append("監査の値・状態を確認してください。")
        cards.attention.append(card)
    elif key in _STATUS_ACTIONS:
        if any(parsed.get(section) for section in _DETAIL_FOR_STATUS.get(key, ())):
            card.compact = True
        else:
            card.lines.extend(
                [
                    _STATUS_ACTIONS[key],
                    "対象の機体・LV・項目は、この通知の監査明細にありません。",
                ]
            )
        cards.attention.append(card)
    else:
        if key == "protected_by_override":
            card.lines.append(
                "取得元が既知の旧値だったため、登録済みの補正値を維持しました。新たな更新停止の件数ではありません。"
            )
            if not parsed.get("登録補正 / 適用中"):
                card.lines.append(
                    "対象の機体・LV・項目・値は、この通知の監査明細にありません。"
                )
        cards.maintenance.append(card)


def _summary_cards(
    summaries: dict[str, dict[str, str]],
    parsed: dict[str, list[dict[str, str]]],
    cards: AuditCards,
) -> None:
    """監査サマリの各項目をカードにし、必須項目の欠落も要確認へ回す。"""
    for heading, values in summaries.items():
        for key, value in values.items():
            if key == "監査情報":
                cards.attention.append(
                    MailCard(
                        f"{heading}: 監査情報が不足",
                        [
                            value,
                            "指定された監査レポートを確認してください。未取得は0件として扱いません。",
                        ],
                    )
                )
            elif key == "status":
                if value not in _SOURCE_OK | {"partial_hold"}:
                    cards.attention.append(
                        MailCard(
                            "取得元スロット監査の状態を確認",
                            [f"状態: {value}", "監査レポートを確認してください。"],
                        )
                    )
            elif key != "対象値":
                _summary_item_card(key, value, parsed, cards)
        missing = [key for key in _REQUIRED_SUMMARY_KEYS[heading] if key not in values]
        if missing and "監査情報" not in values:
            cards.attention.append(
                MailCard(
                    f"{heading}: 件数を確認できません",
                    [
                        "不足している監査項目: " + "、".join(missing),
                        "監査レポートを確認してください。",
                    ],
                )
            )


def _row_status(heading: str, row: dict[str, str]) -> str | None:
    """明細1行が属する監査状態（`_STATUS_ACTIONS` のキー）を決める。"""
    if heading == "ガード / LV間で増減が混在した候補":
        return "mixed_level_change"
    if heading == SOURCE_HOLD_HEADING:
        action = row.get("処置", "")
        if action == "approved_override":
            return "approved_record_count"
        if action in _SOURCE_COUNT_ACTIONS["held_record_count"]:
            return "held_record_count"
        return action
    return row.get("期限状態") or row.get("状態") or row.get("種別")


def _row_values(
    row: dict[str, str], state: str
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """明細1行を、カード本体に出す値と取得証拠欄へ回す値に分ける。"""
    values: list[tuple[str, str]] = []
    extra_evidence: list[tuple[str, str]] = []
    for key, value in row.items():
        if key in {"MS名", "項目"} | _ROW_LOCATION_KEYS:
            continue
        if key in _ROW_EVIDENCE_KEYS:
            extra_evidence.append((key, value or "監査記録なし"))
            continue
        label = _ROW_VALUE_LABELS.get(key, key)
        if key == "取得値" and state not in {"match", "mismatch"}:
            label = "監査記録の値（今回の取得値として未確認）"
        if key == "処置":
            extra_evidence.append(("処置コード", value))
            value = _SOURCE_ACTIONS.get(value, value)
        values.append((label, value if value else "監査記録なし"))
    return values, extra_evidence


def _row_cards(
    parsed: dict[str, list[dict[str, str]]],
    source_rows: list[dict[str, str]],
    cards: AuditCards,
) -> None:
    """監査明細の各行を、対象（機体・LV＋項目）ごとのカードにする。"""
    lookup = {(row.get("MS名"), row.get("項目")): row for row in source_rows}
    for heading, rows in parsed.items():
        if heading == SOURCE_EVIDENCE_HEADING:
            continue
        for row in rows:
            name = row.get("MS名", "対象不明")
            target = (name, row.get("項目", "項目不明"))
            card = MailCard(f"{target[0]} / {target[1]}", target=target)
            info = lookup.get((name, row.get("項目")), {})
            state = info.get("取得状態", "")
            card.values, extra_evidence = _row_values(row, state)
            if state:
                card.lines.append("取得証拠: " + _EVIDENCE_STATES.get(state, state))
            elif heading.startswith("登録補正 / "):
                card.lines.append("取得証拠: この通知に対象の取得証拠なし")
            status = _row_status(heading, row)
            if status in _STATUS_ACTIONS:
                card.lines.append("次の対応: " + _STATUS_ACTIONS[status])
                cards.attention.append(card)
            elif heading == "登録補正 / 適用中" and state not in {"match", "mismatch"}:
                card.lines.append(
                    "次の対応: 取得証拠と補正維持の監査状態が整合しているか確認してください。"
                )
                cards.attention.append(card)
            elif status == "approved_record_count":
                card.lines.append("本人確認済みの有効な補正を採用しました。")
                cards.maintenance.append(card)
            elif heading == "登録補正 / 適用中" and status == "protected_by_override":
                card.lines.append(
                    "取得元の既知の旧値に対し、登録補正値を維持しました。"
                )
                cards.maintenance.append(card)
            else:
                card.lines.append(
                    "次の対応: 監査レポートで対象と状態を確認してください。"
                )
                cards.attention.append(card)
            details = [
                (key, value)
                for key, value in {**info, **row}.items()
                if key in _ROW_LOCATION_KEYS and value
            ]
            details.extend(extra_evidence)
            if details:
                cards.evidence.append(
                    MailCard(card.title, values=details, target=target)
                )


def _source_evidence_cards(
    source_rows: list[dict[str, str]], cards: AuditCards
) -> None:
    """明細に現れない取得証拠を根拠欄へ足し、取得・解析の失敗を要確認へ回す。"""
    for row in source_rows:
        target = (row.get("MS名", "対象不明"), row.get("項目", "項目不明"))
        title = f"{target[0]} / {target[1]}"
        state = row.get("取得状態", "")
        details = [
            (key, value)
            for key, value in row.items()
            if key not in {"MS名", "項目"} and value
        ]
        if details and not any(card.title == title for card in cards.evidence):
            cards.evidence.append(MailCard(title, values=details, target=target))
        if (
            state in {"fetch_failed", "parse_failed", "value_missing", "not_parsed"}
            or state not in _EVIDENCE_STATES
        ):
            cards.attention.append(
                MailCard(
                    title,
                    [
                        "取得証拠: " + _EVIDENCE_STATES.get(state, state),
                        "次の対応: 再取得・解析結果を確認してください。",
                    ],
                    target=target,
                )
            )


def build_audit_cards(sections: dict[str, list[str]]) -> AuditCards:
    """通知の節から監査を読み、照合結果と対象別カードを表示順に組み立てる。"""
    cards = AuditCards()
    parsed = _parse_detail_sections(sections, cards)
    summaries = _read_summaries(sections, cards)
    cards.has_summary = bool(summaries)
    source_issue = _source_summary_issue(
        summaries.get("取得元スロット監査", {}),
        parsed.get(SOURCE_HOLD_HEADING, []),
    )
    if source_issue:
        cards.attention.append(source_issue)
    source_rows = parsed.get(SOURCE_EVIDENCE_HEADING, [])
    _reconcile_override_total(summaries, source_rows, cards)
    cards.attention.extend(_detail_count_issues(summaries, parsed, sections))
    _summary_cards(summaries, parsed, cards)
    _row_cards(parsed, source_rows, cards)
    _source_evidence_cards(source_rows, cards)
    return cards
