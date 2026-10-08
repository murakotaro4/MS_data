"""通知の判断・対応・監査根拠をHTMLとテキストで共有する表示モデル。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

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
_MD_UNESCAPE = re.compile(r"\\([\\`*_\[\]()#+\-.!|<>])")


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


def _plain(text: str) -> str:
    return _MD_UNESCAPE.sub(r"\1", text)


def _sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"": []}
    heading = ""
    for line in lines:
        if line.startswith("## "):
            heading = line[3:]
            sections.setdefault(heading, [])
        else:
            sections[heading].append(line)
    return sections


def _cells(line: str) -> list[str]:
    # 生成元は '\\|' と '\\\\' をエスケープする。後者の直後の区切りも扱う。
    cells = re.split(r"(?<!\\)((?:\\\\)*)\|", line.strip()[1:-1])
    # re.split のキャプチャ（区切り直前のバックスラッシュ対）を元セルへ戻す。
    values = [cells[0]]
    for index in range(1, len(cells), 2):
        values[-1] += cells[index]
        values.append(cells[index + 1])
    return [_plain(value.strip()) for value in values]


@dataclass
class MailCard:
    title: str
    lines: list[str] = field(default_factory=list)
    values: list[tuple[str, str]] = field(default_factory=list)
    compact: bool = False


@dataclass
class MailView:
    facts: dict[str, str]
    sections: dict[str, list[str]]
    action: str
    attention: list[MailCard]
    maintenance: list[MailCard]
    technical: list[str]
    evidence: list[MailCard]


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
}
_SOURCE_OK = {"ok", "approved_correction"}
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


def _facts(lines: list[str]) -> dict[str, str]:
    return dict(
        line[2:].split(": ", 1)
        for line in lines
        if line.startswith("- ") and ": " in line
    )


def _count(value: str | None) -> int | None:
    return int(value) if value is not None and re.fullmatch(r"\d+", value) else None


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
        elif values[headers.index("MS名")] == "なし" and not any(
            v for i, v in enumerate(values) if headers[i] != "MS名"
        ):
            continue
        else:
            row = dict(zip(headers, values, strict=True))
            if group:
                row["機体・項目の組"] = group
            rows.append(row)
    return rows, remainder


def _technical(facts: dict[str, str]) -> list[str]:
    items: list[str] = []
    if "candidate_count" in facts:
        items.append(
            f"再取得候補: {facts['candidate_count']}ページ（URL重複排除後の選定数。変更件数・取得成功数ではありません。）"
        )
    if "fast_path" in facts:
        value = {"true": "有効", "false": "無効"}.get(
            facts["fast_path"], facts["fast_path"]
        )
        items.append(f"高速選定: {value}")
    if "age_coverage" in facts:
        value = facts["age_coverage"]
        try:
            rate = Decimal(value)
            if rate.is_finite() and 0 <= rate <= 1:
                value = f"{(rate * 100).normalize():f}%（{value}）"
        except InvalidOperation:
            pass
        items.append(
            f"一覧の更新経過時間読み取り率: {value}。詳細取得の成功率ではありません。"
        )
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
            "candidate_count",
            "fast_path",
            "age_coverage",
            "fallback_reason",
        }:
            continue
        items.append(_mail_field(key, value))
    return items


def build_mail_view(body: str) -> MailView:
    sections = _sections(
        [line for line in body.splitlines() if not line.startswith("詳細: ")]
    )
    facts = _facts(sections[""])
    attention: list[MailCard] = []
    maintenance: list[MailCard] = []
    evidence: list[MailCard] = []
    parsed: dict[str, list[dict[str, str]]] = {}
    for heading, lines in sections.items():
        if (
            heading.startswith(("ガード / ", "登録補正 / "))
            or heading == "部分保留エラー・補正証拠"
        ):
            parsed[heading], remainder = _audit_tables(lines)
            if remainder:
                attention.append(
                    MailCard(
                        f"監査明細の確認: {heading}",
                        ["監査の原文を確認してください。", *remainder],
                    )
                )

    summaries = {
        heading: _facts(sections[heading])
        for heading in (
            "巻き戻りガード",
            "official_overrides監査",
            "取得元スロット監査",
        )
        if heading in sections
    }
    for heading, values in summaries.items():
        bullets = [line for line in sections[heading] if line.startswith("- ")]
        if len(bullets) != len(values):
            attention.append(
                MailCard(
                    f"{heading}: 監査サマリの形式を確認",
                    ["重複または読み取れない項目があります。", *bullets],
                )
            )
    override = summaries.get("official_overrides監査", {})
    status_counts = {
        key: _count(value)
        for key, value in override.items()
        if key not in {"対象値", "review_due", "remove_due", "期限到達値の取得証拠不足"}
    }
    source_rows = parsed.get("登録補正 / 取得証拠", [])
    unique_rows = {(row.get("MS名"), row.get("項目")) for row in source_rows}
    total = _count(override.get("対象値"))
    # 監査状態は疎なCounter。総数と一意な取得証拠を突き合わせた時だけ省略を0と判断する。
    complete = (
        total is not None
        and all(
            key in _OVERRIDE_STATUSES and value is not None
            for key, value in status_counts.items()
        )
        and sum(value for value in status_counts.values() if value is not None) == total
        and len(unique_rows) == len(source_rows) == total
        and all(name and key for name, key in unique_rows)
    )
    if complete:
        override = {**dict.fromkeys(_OVERRIDE_STATUSES, "0"), **override}
        summaries["official_overrides監査"] = override
    elif "対象値" in override and (
        total is None
        or any(value is None for value in status_counts.values())
        or sum(value for value in status_counts.values() if value is not None) != total
        or len(unique_rows) != len(source_rows)
        or len(source_rows) != total
    ):
        attention.append(
            MailCard(
                "登録補正の監査情報を確認してください",
                [
                    "対象値・状態件数・取得証拠が整合していません。監査レポートを確認してください。"
                ],
            )
        )

    for heading, values in summaries.items():
        for key, value in values.items():
            if key == "監査情報":
                attention.append(
                    MailCard(
                        f"{heading}: 監査情報が不足",
                        [
                            value,
                            "指定された監査レポートを確認してください。未取得は0件として扱いません。",
                        ],
                    )
                )
                continue
            if key in {"対象値", "status"}:
                if key == "status" and value not in _SOURCE_OK | {"partial_hold"}:
                    attention.append(
                        MailCard(
                            "取得元スロット監査の状態を確認",
                            [f"状態: {value}", "監査レポートを確認してください。"],
                        )
                    )
                continue
            count = _count(value)
            if count == 0 and key in _STATUS_LABELS:
                continue
            label, unit = _STATUS_LABELS.get(key, (key, ""))
            card = MailCard(f"{label}: {value}{unit}")
            if count is None or key not in _STATUS_LABELS:
                if count is None:
                    card.title = f"{label}: 未確認"
                    card.lines.append(f"監査原文: {key}: {value}")
                card.lines.append("監査の値・状態を確認してください。")
                attention.append(card)
            elif key in _STATUS_ACTIONS:
                if any(
                    parsed.get(section) for section in _DETAIL_FOR_STATUS.get(key, ())
                ):
                    card.compact = True
                else:
                    card.lines.extend(
                        [
                            _STATUS_ACTIONS[key],
                            "対象の機体・LV・項目は、この通知の監査明細にありません。",
                        ]
                    )
                attention.append(card)
            else:
                if key == "protected_by_override":
                    card.lines.append(
                        "取得元が既知の旧値だったため、登録済みの補正値を維持しました。新たな更新停止の件数ではありません。"
                    )
                    if not parsed.get("登録補正 / 適用中"):
                        card.lines.append(
                            "対象の機体・LV・項目・値は、この通知の監査明細にありません。"
                        )
                maintenance.append(card)
        keys = (
            ("protected_rollback", "numeric_decrease", "mixed_level_change")
            if heading == "巻き戻りガード"
            else (
                ("review_due", "remove_due")
                if heading == "official_overrides監査"
                else ("held_record_count", "previous_unverified_count")
            )
        )
        missing = [key for key in keys if key not in values]
        if missing and "監査情報" not in values:
            attention.append(
                MailCard(
                    f"{heading}: 件数を確認できません",
                    [
                        "不足している監査項目: " + "、".join(missing),
                        "監査レポートを確認してください。",
                    ],
                )
            )

    if override and all(
        _count(override.get(key)) == 0 for key in ("review_due", "remove_due")
    ):
        maintenance.append(
            MailCard("登録補正の期限", ["再確認・撤去判断の期限到達なし。"])
        )

    lookup = {(row.get("MS名"), row.get("項目")): row for row in source_rows}
    for heading, rows in parsed.items():
        if heading == "登録補正 / 取得証拠":
            continue
        for row in rows:
            name = row.get("MS名", "対象不明")
            card = MailCard(f"{name} / {row.get('項目', '項目不明')}")
            info = lookup.get((name, row.get("項目")), {})
            state = info.get("取得状態", "")
            extra_evidence: list[tuple[str, str]] = []
            for key, value in row.items():
                if key in {
                    "MS名",
                    "項目",
                    "URL",
                    "WikiURL",
                    "試行時刻",
                    "取得時刻",
                    "HTTP",
                }:
                    continue
                if key in {
                    "種別",
                    "状態",
                    "期限状態",
                    "前値の承認修復",
                    "前値状態",
                    "stale",
                    "機体・項目の組",
                }:
                    extra_evidence.append((key, value or "監査記録なし"))
                    continue
                label = {
                    "override": "登録補正値",
                    "stale": "既知の旧値",
                    "現在値": "採用値",
                    "review_after": "再確認期限",
                    "remove_after": "撤去判断期限",
                    "変更後": "更新候補値",
                }.get(key, key)
                if key == "取得値" and state and state not in {"match", "mismatch"}:
                    label = "監査記録の値（今回の取得値として未確認）"
                if key == "状態":
                    value = _STATUS_LABELS.get(value, (value, ""))[0]
                if key == "期限状態":
                    value = _STATUS_LABELS.get(value, (value, ""))[0]
                if key == "処置":
                    extra_evidence.append(("処置コード", value))
                    value = _SOURCE_ACTIONS.get(value, value)
                card.values.append((label, value if value else "監査記録なし"))
            if state:
                card.lines.append("取得証拠: " + _EVIDENCE_STATES.get(state, state))
            status = row.get("期限状態") or row.get("状態") or row.get("種別")
            if heading == "ガード / LV間で増減が混在した候補":
                status = "mixed_level_change"
            if heading == "部分保留エラー・補正証拠":
                status = (
                    "approved_record_count"
                    if row.get("処置") == "approved_override"
                    else "held_record_count"
                )
            if status in _STATUS_ACTIONS:
                card.lines.append("次の対応: " + _STATUS_ACTIONS[status])
                attention.append(card)
            elif heading == "登録補正 / 適用中" and (
                state and state not in {"match", "mismatch"}
            ):
                card.lines.append(
                    "次の対応: 取得証拠と補正維持の監査状態が整合しているか確認してください。"
                )
                attention.append(card)
            elif status == "approved_record_count":
                card.lines.append("本人確認済みの有効な補正を採用しました。")
                maintenance.append(card)
            elif heading == "登録補正 / 適用中":
                card.lines.append(
                    "取得元の既知の旧値に対し、登録補正値を維持しました。"
                )
                maintenance.append(card)
            else:
                card.lines.append(
                    "次の対応: 監査レポートで対象と状態を確認してください。"
                )
                attention.append(card)
            details = [
                (key, value)
                for key, value in {**info, **row}.items()
                if key in {"URL", "WikiURL", "試行時刻", "取得時刻", "HTTP"} and value
            ]
            details.extend(extra_evidence)
            if details:
                evidence.append(MailCard(card.title, values=details))

    for row in source_rows:
        state = row.get("取得状態", "")
        details = [
            (key, value)
            for key, value in row.items()
            if key not in {"MS名", "項目"} and value
        ]
        if details and not any(
            card.title
            == f"{row.get('MS名', '対象不明')} / {row.get('項目', '項目不明')}"
            for card in evidence
        ):
            evidence.append(
                MailCard(
                    f"{row.get('MS名', '対象不明')} / {row.get('項目', '項目不明')}",
                    values=details,
                )
            )
        if (
            state in {"fetch_failed", "parse_failed", "value_missing", "not_parsed"}
            or state not in _EVIDENCE_STATES
        ):
            attention.append(
                MailCard(
                    f"{row.get('MS名', '対象不明')} / {row.get('項目', '項目不明')}",
                    [
                        "取得証拠: " + _EVIDENCE_STATES.get(state, state),
                        "次の対応: 再取得・解析結果を確認してください。",
                    ],
                )
            )
    if facts.get("msData.json変更") not in {"true", "false"}:
        attention.append(
            MailCard(
                "データ差分の有無を確認してください",
                ["差分の有無が通知にありません。詳細レポートを確認してください。"],
            )
        )
    if sections.get("既存の全体安全停止"):
        attention.append(MailCard("既存の全体安全停止", sections["既存の全体安全停止"]))
    # optional監査の未指定は失敗扱いにしない。安心文には監査の添付範囲を明示する。
    if attention:
        action = "対応が必要です。下の対象と次の対応を確認してください。"
    elif summaries:
        action = "今回のチェックで要確認の項目なし（添付された監査の範囲）。"
    else:
        action = "監査情報の添付なし。対応要否はこの通知だけでは判定できません。"
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
    return MailView(
        facts, sections, action, attention, maintenance, _technical(facts), evidence
    )


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


def localize_mail_body(body: str) -> str:
    """同じ表示モデルから、結果・対応・根拠・技術情報の順のテキストを生成する。"""
    view = build_mail_view(body)
    lines = [
        "msData 定期更新の確認結果",
        "",
        f"実行日: {view.facts.get('実行日', '')}",
        f"結果: {view.facts.get('結果', '')}",
        change_statement(view.facts),
        view.action,
    ]

    def append_cards(title: str, cards: list[MailCard]) -> None:
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
    if "raw snapshot release" in view.facts:
        lines.extend(
            ["", "取得元・差分レポート: " + view.facts["raw snapshot release"]]
        )
    lines.extend(line for line in body.splitlines() if line.startswith("詳細: "))
    return "\n".join(lines).rstrip() + "\n"
