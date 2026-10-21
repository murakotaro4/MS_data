"""停止・失敗などの運用通知を、日次通知と同じ見た目の HTML カードにする。"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from string import Template

from ms_data.reporting.update_mail_html import _inline_styles, _link


@dataclass
class NoticeCard:
    title: str
    lines: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Notice:
    kicker: str
    title: str
    result: str
    action: str
    date: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    cards_heading: str = ""
    cards: list[NoticeCard] = field(default_factory=list)
    footer: list[str] = field(default_factory=list)


def _card(card: NoticeCard) -> str:
    parts = [f'<div class="audit-card"><h3>{escape(card.title)}</h3>']
    parts.extend(f'<p class="note">{escape(line)}</p>' for line in card.lines)
    parts.extend(
        f'<p class="note">{_link(label, url)}</p>' for label, url in card.links
    )
    parts.append("</div>")
    return "".join(parts)


def render_notice_html(notice: Notice) -> str:
    """外部資源を使わず、head の CSS がなくても読める HTML を返す。"""

    cards = ""
    if notice.cards:
        cards = (
            '<div class="warning">'
            + (
                f"<h2>{escape(notice.cards_heading)}</h2>"
                if notice.cards_heading
                else ""
            )
            + "".join(_card(card) for card in notice.cards)
            + "</div>"
        )
    template = Template(
        Path(__file__)
        .with_name("templates")
        .joinpath("notice_mail.html")
        .read_text(encoding="utf-8")
    )
    html = template.substitute(
        kicker=escape(notice.kicker),
        date=escape(notice.date),
        title=escape(notice.title),
        result=escape(notice.result),
        action=escape(notice.action),
        navigation="".join(
            f'<p class="note">{_link(label, url)}</p>' for label, url in notice.links
        ),
        cards=cards,
        footer="".join(f'<p class="note">{escape(line)}</p>' for line in notice.footer),
    )
    return _inline_styles(html)


def render_notice_text(notice: Notice) -> str:
    """HTML と同じ表示モデルから、プレーンテキスト版を作る。"""
    lines = [notice.title, notice.result, f"次の対応: {notice.action}", ""]
    lines.extend(f"- {label}: {url}" for label, url in notice.links)
    if notice.cards:
        lines.extend(["", notice.cards_heading] if notice.cards_heading else [""])
        for card in notice.cards:
            lines.append(f"- {card.title}")
            lines.extend(f"  {line}" for line in card.lines)
            lines.extend(f"  {label}: {url}" for label, url in card.links)
    if notice.footer:
        lines.extend(["", *notice.footer])
    return "\n".join(lines).rstrip() + "\n"
