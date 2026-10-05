"""生成済みの更新通知本文を、機体カード形式の HTML メールに整形する。"""

from __future__ import annotations

import re
from decimal import Decimal
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

DETAIL_LABELS = {
    "追加レコード一覧": "レコード追加",
    "削除レコード一覧": "レコード削除",
    "変更レコード一覧": "変更",
}
WARNING_LABELS = {
    "protected_rollback": "保護対象の巻き戻り",
    "numeric_decrease": "数値低下の確認候補",
    "mixed_level_change": "LV間で増減が混在する候補",
    "source_changed": "取得値が想定と異なる公式補正",
    "review_due": "公式補正の確認期限到達",
    "remove_due": "公式補正の撤去判断期限到達",
    "held_record_count": "LV単位の部分保留（要対応）",
}
_MD_UNESCAPE = re.compile(r"\\([\\`*_\[\]()#+\-.!|<>])")
_NUMBER = re.compile(r"[+-]?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_COUNTS = re.compile(r"レコード数: (\d+) → (\d+) \| \+(\d+) -(\d+) ~(\d+)")


def _plain(text: str) -> str:
    return _MD_UNESCAPE.sub(r"\1", text)


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


def _pair(label: str, value: str) -> str:
    return (
        '<tr><th scope="row">'
        f'{escape(label)}</th><td class="after">{_value(value)}</td></tr>'
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    parts: list[str] = []
    if headers == ["LV", "項目", "変更前", "変更後"]:
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
            parts.append(f'<p class="note">{_text(line)}</p>')
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


def _warnings(sections: dict[str, list[str]]) -> str:
    items: list[str] = []
    for heading in ("巻き戻りガード", "official_overrides監査", "取得元スロット監査"):
        for line in sections.get(heading, []):
            match = re.fullmatch(r"- ([a-z_]+): (\d+)", line.strip())
            if match and match[1] in WARNING_LABELS and int(match[2]) > 0:
                items.append(f"<li>{WARNING_LABELS[match[1]]}: {match[2]}件</li>")
    if not items:
        return ""
    return '<div class="warning"><h2>要確認</h2><ul>' + "".join(items) + "</ul></div>"


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
    source_lines = body.splitlines()
    sections = _sections(
        [line for line in source_lines if not line.startswith("詳細: ")]
    )
    facts: dict[str, str] = {}
    for line in sections[""]:
        if line.startswith("- ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            facts[key] = value
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
    content = (
        _cards(sections)
        if changed
        else '<p class="no-change">データの変更はありませんでした。</p>'
    )

    footer: list[str] = []
    for heading, section_lines in sections.items():
        if heading and heading not in {*DETAIL_LABELS, "変更内容"}:
            footer.append(f'<h2 class="footer-heading">{_text(heading)}</h2>')
            footer.append(_blocks(section_lines))
    metadata = [
        f'<p class="note">{escape(key)}: {escape(value)}</p>'
        for key, value in facts.items()
        if key not in {"実行日", "結果", "msData.json変更", "raw snapshot release"}
    ]
    if metadata:
        footer.extend(['<h2 class="footer-heading">実行情報</h2>', *metadata])
    if "raw snapshot release" in facts:
        footer.append(
            '<p class="note">'
            + _link("取得元・差分レポート", facts["raw snapshot release"])
            + "</p>"
        )
    # 詳細 URL は最後の監査セクション末尾に入ることもあるため、本文全体から拾う。
    for line in source_lines:
        if line.startswith("詳細: "):
            footer.append(f'<p class="note">{_link("詳細レポート", line[4:])}</p>')

    template = Template(
        Path(__file__)
        .with_name("templates")
        .joinpath("update_mail.html")
        .read_text(encoding="utf-8")
    )
    return template.substitute(
        date=escape(date),
        result=escape(facts.get("結果", "")),
        title="機体データの更新内容" if changed else "msData 定期更新の確認結果",
        warnings=_warnings(sections),
        stats=stats,
        content=content,
        footer="".join(footer),
    )
