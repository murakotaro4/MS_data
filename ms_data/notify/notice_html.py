"""停止・失敗などの運用通知を、日次通知と同じ見た目の HTML カードにする。"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

# notify failure は依存を導入せずシステムの python3 で動くため、標準ライブラリだけで
# 組み立てる。見た目は日次通知（update_mail_html の inline CSS）に合わせる。
_STYLES = {
    "h1": "font-size:24px;line-height:1.4;font-weight:600;margin:20px 0 8px",
    "h2": "font-size:18px;line-height:1.5;margin:0 0 12px;font-weight:600",
    "h3": "font-size:16px;line-height:1.5;margin:0 0 8px;font-weight:600",
    "kicker": "color:#46556b;font-size:14px",
    "date": "color:#46556b;font-size:14px;text-align:right",
    "result": "color:#215fbc;font-size:16px;margin:0 0 12px",
    "action": "font-size:16px;margin:0 0 24px",
    "warning": "border:1px solid #c6a168;border-left:4px solid #925313;"
    "background:#fff4df;color:#513414;padding:18px;margin:0 0 24px;"
    "border-radius:8px;overflow-wrap:anywhere;word-wrap:break-word",
    "card": "padding:16px;border:1px solid #d9bf97;border-radius:8px;"
    "margin:0 0 12px;background:#fff;color:#513414;"
    "overflow-wrap:anywhere;word-wrap:break-word",
    "footer": "border-top:1px solid #d9e1ec;margin-top:24px;padding-top:20px",
    "note": "font-size:14px;line-height:1.75;color:#46556b;margin:8px 0;"
    "overflow-wrap:anywhere;word-wrap:break-word",
    "a": "color:#215fbc;text-decoration:underline;"
    "overflow-wrap:anywhere;word-wrap:break-word",
}


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


def _link(label: str, url: str) -> str:
    """http(s) の URL だけをリンクにし、それ以外は文字列として表示する。"""
    try:
        parsed = urlsplit(url)
    except ValueError:
        parsed = None
    if parsed and parsed.scheme in {"https", "http"} and parsed.netloc:
        return (
            f'<a href="{escape(url, quote=True)}" style="{_STYLES["a"]}">'
            f"{escape(label)}</a>"
        )
    return f"{escape(label)}: {escape(url)}"


def _note(content: str) -> str:
    return f'<p class="note" style="{_STYLES["note"]}">{content}</p>'


def _card(card: NoticeCard) -> str:
    parts = [
        f'<div class="audit-card" style="{_STYLES["card"]}">'
        f'<h3 style="{_STYLES["h3"]}">{escape(card.title)}</h3>'
    ]
    parts.extend(_note(escape(line)) for line in card.lines)
    parts.extend(_note(_link(label, url)) for label, url in card.links)
    parts.append("</div>")
    return "".join(parts)


def render_notice_html(notice: Notice) -> str:
    """外部資源を使わず、head の CSS がなくても読める HTML を返す。"""

    cards = ""
    if notice.cards:
        heading = (
            f'<h2 style="{_STYLES["h2"]}">{escape(notice.cards_heading)}</h2>'
            if notice.cards_heading
            else ""
        )
        cards = (
            f'<div class="warning" style="{_STYLES["warning"]}">'
            + heading
            + "".join(_card(card) for card in notice.cards)
            + "</div>"
        )
    template = Template(
        Path(__file__)
        .with_name("templates")
        .joinpath("notice_mail.html")
        .read_text(encoding="utf-8")
    )
    return template.substitute(
        **{
            f"{name}_style": _STYLES[name]
            for name in ("kicker", "date", "h1", "result", "action", "footer")
        },
        kicker=escape(notice.kicker),
        date=escape(notice.date),
        title=escape(notice.title),
        result=escape(notice.result),
        action=escape(notice.action),
        navigation="".join(_note(_link(label, url)) for label, url in notice.links),
        cards=cards,
        footer="".join(_note(escape(line)) for line in notice.footer),
    )


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
