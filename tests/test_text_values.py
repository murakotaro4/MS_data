"""text_values の文字列・数値変換に対する characterization テスト。"""

from datetime import datetime, timedelta, timezone

import pytest

from ms_data.scraping.text_values import (
    absolute_url,
    clean_text,
    extract_page_id,
    extract_updated_age,
    is_counter_placeholder,
    looks_like_ticket_count,
    normalize_symbol_text,
    parse_iso_datetime,
    parse_ttl,
    symbol_to_bool,
    to_int,
)


def test_normalize_symbol_text_normalizes_fullwidth_symbols_and_whitespace():
    assert normalize_symbol_text("　＋－％：，（ ）\n") == "+-%:,( )"


@pytest.mark.parametrize(
    "href, expected",
    [
        (
            "//w.atwiki.jp/battle-operation2/pages/343.html",
            "https://w.atwiki.jp/battle-operation2/pages/343.html",
        ),
        (
            "/battle-operation2/pages/343.html",
            "https://w.atwiki.jp/battle-operation2/pages/343.html",
        ),
        ("https://example.test/x", "https://example.test/x"),
        (
            "battle-operation2/pages/343.html",
            "https://w.atwiki.jp/battle-operation2/pages/343.html",
        ),
        ("", "https://w.atwiki.jp/"),
    ],
)
def test_absolute_url_normalizes_each_link_form(href, expected):
    assert absolute_url(href) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://w.atwiki.jp/battle-operation2/pages/343.html", 343),
        ("https://w.atwiki.jp/battle-operation2/pages/３４３.html", 343),
        ("https://w.atwiki.jp/battle-operation2/pages/343.html?x=1", None),
        ("", None),
    ],
)
def test_extract_page_id_matches_only_terminal_page_path(url, expected):
    assert extract_page_id(url) == expected


def test_extract_page_id_rejects_none():
    with pytest.raises(TypeError):
        extract_page_id(None)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("ザクⅡ (3h)", ("3h", 10_800)),
        ("ザクⅡ\n(１２m)  ", ("12m", 720)),
        ("ザクⅡ (10s)", (None, None)),
        ("", (None, None)),
    ],
)
def test_extract_updated_age_preserves_supported_suffixes(title, expected):
    assert extract_updated_age(title) == expected


def test_extract_updated_age_rejects_none():
    with pytest.raises(TypeError):
        extract_updated_age(None)


def test_parse_iso_datetime_keeps_explicit_offset():
    assert parse_iso_datetime(" 2026-07-18T12:34:56+09:00 ") == datetime(
        2026,
        7,
        18,
        12,
        34,
        56,
        tzinfo=timezone(timedelta(hours=9)),
    )


def test_parse_iso_datetime_rejects_empty_text_and_none():
    with pytest.raises(ValueError):
        parse_iso_datetime("")
    with pytest.raises(AttributeError):
        parse_iso_datetime(None)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("7d", 604_800),
        ("72H", 259_200),
        ("15m", 900),
        ("3600s", 3_600),
        ("90", 90),
        ("", 604_800),
        (" ２d ", 172_800),
        ("1.5", 1),
    ],
)
def test_parse_ttl_converts_current_accepted_forms(value, expected):
    assert parse_ttl(value) == expected


@pytest.mark.parametrize("value", ["1,000", None])
def test_parse_ttl_rejects_current_invalid_forms(value):
    with pytest.raises(ValueError):
        parse_ttl(value)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("１２３", 123),
        ("1,234", 1_234),
        ("45％", 45),
        ("価格 1,234.5 DP", 1_234),
        ("速度なし", None),
        ("   ", None),
    ],
)
def test_to_int_characterizes_additional_numeric_forms(text, expected):
    assert to_int(text) == expected


def test_is_counter_placeholder_normalizes_mixed_whitespace():
    assert is_counter_placeholder("押し倒し\t投げ\n特殊") is True


def test_is_counter_placeholder_rejects_none():
    with pytest.raises(TypeError):
        is_counter_placeholder(None)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("225", True),
        ("260", True),
        ("1,234", True),
        ("  225  ", True),
        ("２２５", True),
        ("１，２３４", True),
        ("少尉01", False),
        ("二等兵01", False),
        ("DP交換不可（リサイクル窓口専用ユニット）", False),
        ("", False),
        ("225チケット", False),
    ],
)
def test_looks_like_ticket_count(text, expected):
    assert looks_like_ticket_count(text) is expected


@pytest.mark.parametrize(
    "text, expected",
    [
        (" yes ", True),
        ("出撃不可", False),
        ("出撃可能", True),
        ("", None),
    ],
)
def test_symbol_to_bool_characterizes_embedded_and_empty_text(text, expected):
    assert symbol_to_bool(text) is expected


def test_symbol_to_bool_rejects_none():
    with pytest.raises(TypeError):
        symbol_to_bool(None)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", ""),
        ("　A\nB\tC　", "A B C"),
    ],
)
def test_clean_text_characterizes_empty_and_unicode_whitespace(text, expected):
    assert clean_text(text) == expected


def test_clean_text_rejects_none():
    with pytest.raises(TypeError):
        clean_text(None)
