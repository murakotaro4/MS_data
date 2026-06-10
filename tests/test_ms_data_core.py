"""ms_data.core / ms_data.gh / ms_data.reporting の共通ユーティリティのテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_data.core.env import env_flag, env_float, env_int, env_str
from ms_data.core.json_io import load_json, load_json_or_default
from ms_data.core.ms_names import (
    MS_NAME_WITH_LEVEL,
    extract_ms_base_name,
    ms_name_to_series_level,
    normalize_ms_base_name,
)
from ms_data.core.records import load_records_by_name
from ms_data.gh.gh_json import (
    flatten_pages,
    load_json_stream,
    login_of,
    parse_json_stream,
)
from ms_data.gh.outputs import append_step_summary, write_github_output
from ms_data.reporting.rendering import value_text


# --- json_io ---


def test_load_json_reads_utf8(tmp_path: Path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps({"MS名": "ガンダム"}, ensure_ascii=False), encoding="utf-8"
    )
    assert load_json(path) == {"MS名": "ガンダム"}


def test_load_json_raises_on_missing(tmp_path: Path):
    with pytest.raises(OSError):
        load_json(tmp_path / "missing.json")


def test_load_json_or_default(tmp_path: Path):
    assert load_json_or_default(None, []) == []
    assert load_json_or_default(tmp_path / "missing.json", {"a": 1}) == {"a": 1}
    path = tmp_path / "data.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_json_or_default(path, []) == [1, 2]


# --- ms_names ---


def test_ms_name_with_level_groups():
    m = MS_NAME_WITH_LEVEL.match("ガンダム_LV3")
    assert m is not None
    assert m.group("base") == "ガンダム"
    assert m.group("level") == "3"


def test_extract_ms_base_name():
    assert extract_ms_base_name("ガンダム_LV3") == "ガンダム"
    assert extract_ms_base_name("ガンダム") is None


def test_normalize_ms_base_name():
    assert normalize_ms_base_name("Zガンダム") == "Ζガンダム"
    assert normalize_ms_base_name("ZZガンダム") == "ΖΖガンダム"
    assert normalize_ms_base_name("ジム[WD隊仕様]") == "ジム［WD隊仕様］"
    assert normalize_ms_base_name("ガンダムMk-II") == "ガンダムMk-Ⅱ"


def test_ms_name_to_series_level():
    assert ms_name_to_series_level("イフリート改_LV2") == ("イフリート改", 2)
    assert ms_name_to_series_level("イフリート改") == ("イフリート改", None)


# --- records ---


def test_load_records_by_name(tmp_path: Path):
    path = tmp_path / "records.json"
    path.write_text(
        json.dumps(
            [{"MS名": "ガンダム_LV1", "HP": 100}, {"HP": 5}], ensure_ascii=False
        ),
        encoding="utf-8",
    )
    records = load_records_by_name(path)
    assert records == {"ガンダム_LV1": {"MS名": "ガンダム_LV1", "HP": 100}}


def test_load_records_by_name_rejects_non_array(tmp_path: Path):
    path = tmp_path / "records.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        load_records_by_name(path)


# --- env ---


def test_env_str(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MSDATA_TEST_ENV", raising=False)
    assert env_str("MSDATA_TEST_ENV") is None
    assert env_str("MSDATA_TEST_ENV", "x") == "x"
    monkeypatch.setenv("MSDATA_TEST_ENV", "")
    assert env_str("MSDATA_TEST_ENV", "x") == "x"
    monkeypatch.setenv("MSDATA_TEST_ENV", "value")
    assert env_str("MSDATA_TEST_ENV") == "value"


def test_env_int_float_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MSDATA_TEST_ENV", "5")
    assert env_int("MSDATA_TEST_ENV", 1) == 5
    monkeypatch.setenv("MSDATA_TEST_ENV", "2.5")
    assert env_float("MSDATA_TEST_ENV", 1.0) == 2.5
    for value, expected in [("1", True), ("0", False), ("false", False), ("on", True)]:
        monkeypatch.setenv("MSDATA_TEST_ENV", value)
        assert env_flag("MSDATA_TEST_ENV") is expected


# --- gh.outputs ---


def test_write_github_output(tmp_path: Path):
    path = tmp_path / "out" / "github_output"
    write_github_output(path, {"a": 1, "b": None, "c": "x"})
    assert path.read_text(encoding="utf-8") == "a=1\nb=\nc=x\n"


def test_append_step_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "summary.md"
    append_step_summary(["# 見出し", "- 項目"], path)
    assert path.read_text(encoding="utf-8") == "# 見出し\n- 項目\n"
    # path も環境変数もない場合は何もしない
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    append_step_summary(["x"], None)


# --- gh.gh_json ---


def test_parse_json_stream_concatenated():
    assert parse_json_stream('[{"id": 1}]\n[{"id": 2}]') == [{"id": 1}, {"id": 2}]
    assert parse_json_stream('{"id": 1}') == {"id": 1}
    assert parse_json_stream("") == []


def test_load_json_stream(tmp_path: Path):
    path = tmp_path / "pages.json"
    path.write_text('[{"id": 1}]\n[{"id": 2}]', encoding="utf-8")
    assert load_json_stream(path) == [{"id": 1}, {"id": 2}]


def test_flatten_pages():
    assert flatten_pages([[1, 2], [3]]) == [1, 2, 3]
    assert flatten_pages([1, 2]) == [1, 2]
    assert flatten_pages("x") == "x"


def test_login_of():
    assert login_of({"user": {"login": "octocat"}}) == "octocat"
    assert login_of({"user": "bad"}) == ""
    assert login_of({}) == ""


# --- reporting.rendering ---


def test_value_text():
    assert value_text(None) == ""
    assert value_text({"a": "あ"}) == '{"a": "あ"}'
    assert value_text([1]) == "[1]"
    assert value_text(12) == "12"
