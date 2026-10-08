"""完全な監査の判定後に、両形式へ共有するサイズ内の表示を選ぶ。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from urllib.parse import urlsplit

from ms_data.reporting.update_mail_model import (
    _STATUS_ACTIONS,
    _STATUS_LABELS,
    DETAIL_LABELS,
    MailCard,
    MailView,
)

MAX_HTML_BYTES = 80 * 1024
MAX_LINK_BYTES = 2048


def _merge_cards(cards: list[MailCard]) -> list[MailCard]:
    result: list[MailCard] = []
    indexes: dict[tuple[str, str], int] = {}
    for card in cards:
        if card.target is None or card.target not in indexes:
            if card.target is not None:
                indexes[card.target] = len(result)
            result.append(replace(card, lines=card.lines[:], values=card.values[:]))
        else:
            prior = result[indexes[card.target]]
            prior.lines = list(dict.fromkeys([*prior.lines, *card.lines]))
            prior.values = list(dict.fromkeys([*prior.values, *card.values]))
    return result


def group_card_actions(cards: list[MailCard]) -> list[MailCard]:
    """同じ対応を対象の直前で1回示す。表示選択後なので件数は可視対象数。"""
    groups: dict[tuple[str, ...], list[MailCard]] = {}
    for card in cards:
        actions = tuple(line for line in card.lines if line.startswith("次の対応: "))
        groups.setdefault(actions if card.target else (), []).append(card)
    result = []
    for actions, group in groups.items():
        if actions and len(group) > 1:
            count = len({card.target for card in group})
            result.append(
                MailCard(
                    f"次の対応（以下の{count}項目／機体＋LV＋項目）", list(actions)
                )
            )
            result.extend(
                replace(
                    card, lines=[line for line in card.lines if line not in actions]
                )
                for card in group
            )
        else:
            result.extend(group)
    return result


def _targets(cards: list[MailCard]) -> set[tuple[str, str]]:
    return {card.target for card in cards if card.target is not None}


def _short(text: str, limit: int = 512) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore") + "…（表示省略・完全版で確認）"


def _confirmation_link(link: tuple[str, str]) -> bool:
    if len(link[1].encode("utf-8")) > MAX_LINK_BYTES:
        return False
    try:
        parsed = urlsplit(link[1])
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def fit_mail_view(
    original: MailView, render: Callable[[MailView, bool], str]
) -> tuple[MailView, str]:
    """文字列を切らず、CSS・エスケープ後のHTMLサイズを毎回検証する。"""
    view = original
    html = render(view, False)
    if len(html.encode("utf-8")) <= MAX_HTML_BYTES:
        return view, html

    links = [link for link in original.links if _confirmation_link(link)][:3]
    base_notes = ["明細が多いため、共通の説明をまとめて表示しています。"]
    if len(links) != len(original.links):
        base_notes.append(
            "長すぎる確認URL・使えないURL・4件目以降のリンクは本文に表示していません。実行ログで確認してください。"
        )
    if not links:
        base_notes.append(
            "完全版の確認リンクなし。実行ログの監査・変更レポートを確認してください。"
        )
    view = replace(
        original,
        attention=_merge_cards(original.attention),
        maintenance=_merge_cards(original.maintenance),
        evidence=_merge_cards(original.evidence),
        links=links,
        notices=base_notes,
        condensed=True,
    )
    notes: dict[str, str] = {}

    def measure() -> str:
        view.notices = [*base_notes, *notes.values()]
        return render(view, True)

    html = measure()
    if len(html.encode("utf-8")) > MAX_HTML_BYTES and view.evidence:
        count = len(_targets(view.evidence))
        notes["evidence"] = (
            f"取得証拠の補足: {count}項目分（機体＋LV＋項目）は完全版で確認してください。"
        )
        view = replace(view, evidence=[])
        html = measure()

    for attr, label in (("maintenance", "補正維持・承認補正"), ("attention", "要確認")):
        cards = getattr(view, attr)
        all_targets = _targets(cards)
        while len(html.encode("utf-8")) > MAX_HTML_BYTES and _targets(cards):
            targets = [card for card in cards if card.target is not None]
            keep = {id(card) for card in targets[: len(targets) // 2]}
            cards = [card for card in cards if card.target is None or id(card) in keep]
            if attr == "attention":
                # 明細を省いた状態でも、全対象に必要な対応をサマリへ戻す。
                for index, card in enumerate(cards):
                    if card.target is not None or not card.compact:
                        continue
                    for status, action in _STATUS_ACTIONS.items():
                        status_label = _STATUS_LABELS.get(status, (status, ""))[0]
                        if card.title.startswith(status_label + ":"):
                            cards[index] = replace(
                                card,
                                compact=False,
                                lines=["次の対応: " + action, *card.lines],
                            )
                            break
            view = replace(view, **{attr: cards})
            count = len(all_targets - _targets(cards))
            notes[attr] = (
                f"{label}の詳細を本文に載せない対象: {count}項目（機体＋LV＋項目）。完全版の対象と対応を確認してください。"
            )
            html = measure()

    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        sections = dict(view.sections)
        names = {
            line[4:]
            for heading in DETAIL_LABELS
            for line in sections.get(heading, [])
            if line.startswith("### ")
        }
        if names:
            for heading in DETAIL_LABELS:
                sections.pop(heading, None)
            view = replace(view, sections=sections)
            notes["diff"] = (
                f"変更明細の詳細を本文に載せない対象: {len(names)}機体。LV別の値は完全版の変更レポートで確認してください。"
            )
            html = measure()

    if len(html.encode("utf-8")) > MAX_HTML_BYTES:

        def short_card(card: MailCard) -> MailCard:
            return replace(
                card,
                title=_short(card.title),
                lines=[_short(line) for line in card.lines[:8]],
                values=[
                    (_short(key), _short(value)) for key, value in card.values[:12]
                ],
            )

        notes["long"] = (
            "長い補足情報は一部を省略しています。内容の全文は完全版で確認してください。"
        )
        view = replace(
            view,
            facts={key: _short(value) for key, value in view.facts.items()},
            sections={
                _short(key): [_short(line) for line in lines[:8]]
                for key, lines in view.sections.items()
            },
            attention=[short_card(card) for card in view.attention],
            maintenance=[short_card(card) for card in view.maintenance],
            technical=[_short(line) for line in view.technical[:8]],
        )
        html = measure()
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        # 不正形式の巨大な補足でも、対応要否・実在の確認先を失わず要約へ戻す。
        notes["minimum"] = (
            "本文は結果の要約です。すべての対象・値・補足は完全版の監査・変更レポートを確認してください。"
        )
        view = replace(
            view,
            sections={},
            maintenance=[
                short_card(card) for card in view.maintenance if card.target is None
            ],
            evidence=[],
            technical=view.technical[:3],
            attention=(
                [
                    *[
                        MailCard(
                            _short(card.title, 256),
                            ["次の対応: " + action],
                        )
                        for card in view.attention
                        if card.target is None
                        for status, action in _STATUS_ACTIONS.items()
                        if card.title.startswith(
                            _STATUS_LABELS.get(status, (status, ""))[0] + ":"
                        )
                    ][:20],
                    MailCard(
                        "監査の全文を確認してください",
                        ["要確認の対象と対応は完全版で確認してください。"],
                    ),
                ]
                if original.attention
                else []
            ),
        )
        html = measure()
    assert len(html.encode("utf-8")) <= MAX_HTML_BYTES
    return view, html
