"""正規化・テキストパース関数の不変条件（プロパティベーステスト）。"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from ms_data.core.ms_names import (
    extract_ms_base_name,
    normalize_ms_base_name,
    normalize_ms_name,
)
from ms_data.scraping.text_values import (
    absolute_url,
    extract_page_id,
    normalize_symbol_text,
    parse_ttl,
    symbol_to_bool,
    to_int,
)

# MS名で頻出する表記揺れ文字を混ぜたストラテジー
_MS_ALPHABET = st.sampled_from(
    list("ガンダムザクジムゲルググ[]［］IIIVＶZΖ0123456789 _-・号機改")
)
_MS_BASE_TEXT = st.text(_MS_ALPHABET, min_size=1, max_size=30)
_ANY_TEXT = st.text(max_size=60)


@given(name=_MS_BASE_TEXT)
def test_normalize_ms_base_name_is_idempotent_and_removes_banned_forms(name: str):
    once = normalize_ms_base_name(name)
    twice = normalize_ms_base_name(once)

    assert twice == once
    for banned in ("[", "]", "Ｖ", "III", "II", "ZZガンダム", "Zガンダム"):
        assert banned not in once


@given(base=_MS_BASE_TEXT, level=st.integers(min_value=1, max_value=99))
def test_normalize_ms_name_preserves_level_and_is_idempotent(base: str, level: int):
    raw = f"{base}_LV{level}"
    once = normalize_ms_name(raw)
    twice = normalize_ms_name(once)

    assert twice == once
    assert once.endswith(f"_LV{level}")
    assert extract_ms_base_name(once) == normalize_ms_base_name(
        extract_ms_base_name(raw) or ""
    )


@given(text=_ANY_TEXT)
def test_normalize_ms_name_leaves_non_level_strings_unchanged(text: str):
    if extract_ms_base_name(text) is None:
        assert normalize_ms_name(text) == text


@given(text=_ANY_TEXT)
def test_normalize_symbol_text_is_idempotent_and_removes_fullwidth_symbols(text: str):
    once = normalize_symbol_text(text)
    twice = normalize_symbol_text(once)

    assert twice == once
    for fw in ("\u3000", "＋", "－", "％", "：", "，", "（", "）"):
        assert fw not in once


@given(n=st.integers(min_value=-(10**9), max_value=10**9))
def test_to_int_roundtrips_plain_and_comma_formatted_integers(n: int):
    assert to_int(str(n)) == n
    if n >= 0:
        assert to_int(f"{n:,}") == n


@given(text=_ANY_TEXT)
def test_to_int_never_raises_on_arbitrary_text(text: str):
    result = to_int(text)
    assert result is None or isinstance(result, int)


@given(
    prefix=st.sampled_from(["https://w.atwiki.jp/battle-operation2", "", "/wiki"]),
    page_id=st.integers(min_value=1, max_value=999999),
)
def test_extract_page_id_roundtrips_pages_url(prefix: str, page_id: int):
    url = f"{prefix}/pages/{page_id}.html"
    assert extract_page_id(url) == page_id


@given(
    href=st.one_of(
        st.text(
            st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789/._-")),
            max_size=40,
        ).filter(lambda s: not s.startswith("http")),
        st.from_regex(r"//[a-z0-9.-]+/[a-z0-9/._-]*", fullmatch=True),
        st.from_regex(r"https?://[a-z0-9.-]+/[a-z0-9/._-]*", fullmatch=True),
    )
)
def test_absolute_url_is_idempotent_and_has_http_scheme(href: str):
    once = absolute_url(href)
    twice = absolute_url(once)

    assert once.startswith(("http://", "https://"))
    assert twice == once


@given(
    val=st.integers(min_value=0, max_value=10000),
    unit=st.sampled_from(["", "s", "m", "h", "d"]),
)
def test_parse_ttl_matches_exact_unit_seconds(val: int, unit: str):
    factors = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
    assert parse_ttl(f"{val}{unit}") == val * factors[unit]


@given(text=_ANY_TEXT)
def test_symbol_to_bool_never_raises_and_prioritizes_negation(text: str):
    result = symbol_to_bool(text)
    assert result in (True, False, None)
    if "不可" in text or "×" in text:
        assert result is False
