"""生成済みの更新通知本文を、機体カード形式の HTML メールに整形する。"""

from __future__ import annotations

import re
from decimal import Decimal
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

from ms_data.reporting.update_mail_model import (
    DETAIL_LABELS,
    ENHANCEMENT_HEADERS,
    MailCard,
    MailView,
    _cells,
    _mail_line,
    _plain,
    build_mail_view,
    change_statement,
)

_NUMBER = re.compile(r"[+-]?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_COUNTS = re.compile(r"レコード数: (\d+) → (\d+) \| \+(\d+) -(\d+) ~(\d+)")


def _text(text: str) -> str:
    return escape(_plain(text))


def _number(text: str) -> str:
    if not _NUMBER.fullmatch(text):
        return text
    formatted = f"{Decimal(text):,f}"
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def _value(text: str) -> str:
    return escape(_number(text)) if text else "未設定"


def _delta(before: str, after: str) -> str:
    if not (_NUMBER.fullmatch(before) and _NUMBER.fullmatch(after)):
        return ""
    delta = Decimal(after) - Decimal(before)
    if not delta:
        return ""
    formatted = f"{delta:+,f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return f'<span class="delta">{formatted}</span>'


def _pair(label: str, value: str) -> str:
    return (
        '<tr><th scope="row">'
        f'{escape(label)}</th><td class="after">{_value(value)}</td></tr>'
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    parts: list[str] = []
    if headers == ENHANCEMENT_HEADERS:
        parts.append(
            '<table class="enhancements" aria-label="強化項目の必要強化値の変更前後"><thead><tr>'
        )
        parts.extend(f'<th scope="col">{escape(header)}</th>' for header in headers)
        parts.append('</tr></thead><tbody>')
        for name, before, after in rows:
            skill, separator, level = name.rpartition("（強化Lv")
            label = (
                f'{escape(skill)}<br><span class="skill-level">強化Lv{escape(level[:-1])}</span>'
                if separator and level.endswith("）")
                else escape(name)
            )
            parts.append(
                f'<tr><th scope="row">{label}</th><td class="before">{_value(before)}</td><td class="after">{_value(after)}</td></tr>'
            )
        parts.append('</tbody></table>')
    elif headers == ["LV", "項目", "変更前", "変更後"]:
        levels: dict[str, list[list[str]]] = {}
        for row in rows:
            levels.setdefault(row[0], []).append(row)
        for level, changes in levels.items():
            parts.append(f'<h3 class="level">{escape(level)}</h3>')
            for _, field, before, after in changes:
                parts.append(
                    '<div class="change">'
                    f'<div class="field">{escape(field)}</div>'
                    f'<span class="before">{_value(before)}</span>'
                    ' <span class="arrow">→</span> '
                    f'<span class="after">{_value(after)}</span> '
                    f"{_delta(before, after)}</div>"
                )
    else:
        # 幅の広い追加ステータス表・fullst 明細も、2列へ展開して全項目を保持する。
        for row in rows:
            if headers[0] == "LV":
                parts.append(f'<h3 class="level">{escape(row[0])}</h3>')
                pairs = zip(headers[1:], row[1:], strict=True)
            else:
                pairs = zip(headers, row, strict=True)
            parts.append('<table class="values" aria-label="項目と値">')
            parts.extend(_pair(label, value) for label, value in pairs)
            parts.append("</table>")
    return "".join(parts)


def _blocks(lines: list[str]) -> str:
    parts: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if (
            line.startswith("|")
            and index + 1 < len(lines)
            and re.fullmatch(r"[| :\-]+", lines[index + 1].strip())
        ):
            headers = _cells(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_cells(lines[index]))
                index += 1
            if headers and all(len(row) == len(headers) for row in rows):
                parts.append(_table(headers, rows))
            else:
                # フォーマットが変わった場合も、明細を黙って捨てない。
                parts.append(f'<p class="note">{escape(" | ".join(headers))}</p>')
                parts.extend(
                    f'<p class="note">{escape(" | ".join(row))}</p>' for row in rows
                )
            continue
        if line:
            parts.append(f'<p class="note">{_text(_mail_line(line))}</p>')
        index += 1
    return "".join(parts)


def _cards(sections: dict[str, list[str]]) -> str:
    machines: dict[str, list[tuple[str, list[str]]]] = {}
    notes: list[str] = []
    for heading, label in DETAIL_LABELS.items():
        group: list[str] | None = None
        for line in sections.get(heading, []):
            if line.startswith("### "):
                name = _plain(line[4:])
                group = []
                machines.setdefault(name, []).append((label, group))
            elif group is not None:
                group.append(line)
            elif line.strip() and not line.startswith("- 件数:"):
                notes.append(line)
    parts = [_blocks(notes)]
    for name, groups in machines.items():
        parts.append(
            f'<div class="machine"><h2 class="machine-name">{escape(name)}</h2>'
        )
        for label, lines in groups:
            parts.append(f'<div class="kind">{escape(label)}</div>{_blocks(lines)}')
        parts.append("</div>")
    return "".join(parts)


def _audit_cards(
    cards: list[MailCard], *, warning: bool = False, dense: bool = False
) -> str:
    if dense:
        from ms_data.reporting.update_mail_display import group_card_actions

        cards = group_card_actions(cards)
    parts: list[str] = []
    for card in cards:
        if dense:
            parts.append(
                f'<div class="compact-card"><strong>{escape(card.title)}</strong>'
            )
            parts.extend(f'<div>{escape(line)}</div>' for line in card.lines)
            parts.extend(
                f'<div>{escape(label)}: {escape(value) if value else "監査記録なし"}</div>'
                for label, value in card.values
            )
            parts.append('</div>')
            continue
        if card.compact:
            parts.append(f'<p class="note"><strong>{escape(card.title)}</strong></p>')
            continue
        parts.append(f'<div class="audit-card"><h3>{escape(card.title)}</h3>')
        parts.extend(f'<p class="note">{escape(line)}</p>' for line in card.lines)
        if card.values:
            parts.append('<table class="values" aria-label="監査対象と根拠">')
            parts.extend(_pair(label, value) for label, value in card.values)
            parts.append('</table>')
        parts.append('</div>')
    if dense and parts:
        parts = ['<div class="compact">', *parts, '</div>']
    if warning and parts:
        return (
            '<div class="warning"><h2>要確認の対象と次の対応</h2>'
            + ''.join(parts)
            + '</div>'
        )
    return ''.join(parts)


def _link(label: str, url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        parsed = None
    if parsed and parsed.scheme in {"https", "http"} and parsed.netloc:
        return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
    return f"{escape(label)}: {escape(url)}"


def render_update_mail(body: str) -> str:
    """テキスト通知と同じ内容から HTML 版を生成する。外部資源は使用しない。"""
    return prepare_update_mail(body)[1]


def prepare_update_mail(body: str) -> tuple[MailView, str]:
    """完全な監査を判定してから、両形式に使うサイズ内の表示を選ぶ。"""
    from ms_data.reporting.update_mail_display import fit_mail_view

    return fit_mail_view(build_mail_view(body), _render_view)


def _render_view(view: MailView, dense: bool = False) -> str:
    sections, facts = view.sections, view.facts
    changed = facts.get("msData.json変更") == "true"
    date = facts.get("実行日", "")
    if re.fullmatch(r"\d{8}", date):
        date = f"{date[:4]} / {date[4:6]} / {date[6:]}"

    summary = "\n".join(sections.get("差分サマリ", []))
    counts = _COUNTS.search(summary)
    stats = ""
    if changed:
        cells: list[str] = []
        for label, value in (
            ("追加", counts[3] if counts else "—"),
            ("変更", counts[5] if counts else "—"),
            ("削除", counts[4] if counts else "—"),
        ):
            cells.append(
                f'<td><div class="stat-label">{label}</div>'
                f'<div class="stat-value">{value}</div></td>'
            )
        stats = (
            '<table class="stats" role="presentation"><tr>'
            + "".join(cells)
            + '</tr></table><p class="counts-note">件数は機体のLV別レコード数</p>'
        )
    content = _cards(sections) if changed else ''
    if dense and content:
        content = '<div class="compact">' + content + '</div>'

    maintenance = ''
    if view.maintenance:
        maintenance = (
            '<div class="maintenance"><h2>補正値の維持と期限</h2>'
            + _audit_cards(view.maintenance, dense=dense)
            + '</div>'
        )

    footer: list[str] = []
    used = {
        *DETAIL_LABELS,
        "変更内容",
        "差分サマリ",
        "巻き戻りガード",
        "official_overrides監査",
        "取得元スロット監査",
        "部分保留エラー・補正証拠",
    }
    for heading, section_lines in sections.items():
        if (
            heading
            and heading not in used
            and not heading.startswith(("ガード / ", "登録補正 / "))
        ):
            footer.append(f'<h2 class="footer-heading">{_text(heading)}</h2>')
            footer.append(_blocks(section_lines))
    metadata = [f'<p class="note">{escape(line)}</p>' for line in view.technical]
    if sections.get("差分サマリ"):
        metadata.insert(0, _blocks(sections["差分サマリ"]))
    if metadata:
        footer.extend(['<h2 class="footer-heading">技術情報</h2>', *metadata])
    if view.evidence:
        footer.append(
            '<h2 class="footer-heading">取得証拠の詳細</h2>'
            + _audit_cards(view.evidence, dense=dense)
        )
    navigation = [f'<p class="note">{escape(line)}</p>' for line in view.notices]
    navigation.extend(
        f'<p class="note">{_link(label, url)}</p>' for label, url in view.links
    )

    template = Template(
        Path(__file__)
        .with_name("templates")
        .joinpath("update_mail.html")
        .read_text(encoding="utf-8")
    )
    html = template.substitute(
        date=escape(date),
        result=escape(facts.get("結果", "")),
        title=change_statement(facts),
        action=escape(view.action),
        navigation=''.join(navigation),
        warnings=_audit_cards(view.attention, warning=True, dense=dense),
        stats=stats,
        content=content,
        maintenance=maintenance,
        footer="".join(footer),
    )
    return _inline_styles(html)


def _inline_styles(html: str) -> str:
    """HTMLメールの基本表示をstyle属性に持たせ、headのCSSなしでも読み取れる。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    styles = {
        "h1": "font-size:24px;line-height:1.4;font-weight:600;margin:20px 0 8px",
        "h2": "font-size:18px;line-height:1.5;margin:0 0 12px;font-weight:600",
        "h3": "font-size:16px;line-height:1.5;margin:0 0 8px;font-weight:600",
        ".kicker,.date": "color:#46556b;font-size:14px",
        ".date": "text-align:right",
        ".result": "color:#215fbc;font-size:16px;margin:0 0 12px",
        ".action": "font-size:16px;margin:0 0 24px",
        ".stats": "width:100%;table-layout:fixed;border-spacing:6px 0;margin:20px 0 0",
        ".stats td": "width:33.33%;padding:12px 4px;background:#edf4ff;text-align:center;border-radius:8px",
        ".stat-label": "color:#46556b;font-size:14px",
        ".stat-value": "font-size:28px;font-weight:600",
        ".counts-note": "margin:8px 0 22px;color:#46556b;font-size:14px",
        ".machine": "border:1px solid #d9e1ec;border-radius:10px;padding:18px;margin:0 0 16px;background:#fff;overflow-wrap:anywhere;word-wrap:break-word",
        ".machine-name": "font-size:19px;line-height:1.5;margin:0 0 8px;font-weight:600",
        ".kind,.field": "color:#46556b;font-size:14px;margin:8px 0 6px",
        ".level": "font-size:16px;margin:16px 0 8px;color:#18222f;font-weight:600",
        ".change": "margin:0 0 12px",
        ".before,.arrow": "color:#46556b",
        ".after": "color:#215fbc;font-weight:600",
        ".delta": "display:inline-block;background:#edf4ff;color:#215fbc;border-radius:4px;padding:1px 7px;font-size:14px;white-space:nowrap",
        ".values": "width:100%;border-collapse:collapse;table-layout:fixed;margin:12px 0;font-size:14px",
        ".values th,.values td": "padding:7px 0;border-bottom:1px solid #e2e8f0;vertical-align:top;overflow-wrap:anywhere;word-wrap:break-word",
        ".values th": "width:42%;padding-right:10px;color:#46556b;text-align:left;font-weight:400",
        ".enhancements": "width:100%;border-collapse:collapse;table-layout:fixed;margin:12px 0;font-size:14px",
        ".enhancements th,.enhancements td": "padding:9px 5px;border-bottom:1px solid #e2e8f0;vertical-align:top;overflow-wrap:anywhere;word-wrap:break-word;text-align:left",
        ".enhancements th:first-child": "width:48%;font-weight:400",
        ".enhancements thead th": "background:#edf4ff;color:#46556b;font-weight:600",
        ".skill-level": "color:#46556b;font-size:14px",
        ".warning": "border:1px solid #c6a168;border-left:4px solid #925313;background:#fff4df;color:#513414;padding:18px;margin:0 0 24px;border-radius:8px;overflow-wrap:anywhere;word-wrap:break-word",
        ".audit-card": "padding:16px;border:1px solid #d9e1ec;border-radius:8px;margin:0 0 12px;background:#fff;overflow-wrap:anywhere;word-wrap:break-word",
        ".warning .audit-card": "border-color:#d9bf97;color:#513414",
        ".maintenance": "margin:24px 0 0",
        ".footer": "border-top:1px solid #d9e1ec;margin-top:24px;padding-top:20px",
        ".footer-heading": "font-size:16px;margin:16px 0 10px;color:#46556b;font-weight:600",
        ".note": "font-size:14px;line-height:1.75;color:#46556b;margin:8px 0;overflow-wrap:anywhere;word-wrap:break-word",
        ".compact": "font-size:14px;line-height:1.75;overflow-wrap:anywhere;word-wrap:break-word",
        ".compact-card": "padding:10px 0;border-bottom:1px solid #d9e1ec",
        "a": "color:#215fbc;text-decoration:underline;overflow-wrap:anywhere;word-wrap:break-word",
    }
    for selector, style in styles.items():
        for node in soup.select(selector):
            if node.find_parent(class_="compact") and selector not in {
                ".compact-card",
                "a",
            }:
                continue
            node['style'] = ';'.join(filter(None, (node.get('style', ''), style)))
    return str(soup)
