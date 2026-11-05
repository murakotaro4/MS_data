"""core/labels・core/ms_names・core/records の未カバー分岐のテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_data.core.labels import apply_key_aliases
from ms_data.core.ms_names import extract_ms_base_name, normalize_ms_name
from ms_data.core.records import load_records_by_name


def test_apply_key_aliases_moves_alias_when_target_missing() -> None:
    assert apply_key_aliases({"射撃補則": "10"}) == {"射撃補正": "10"}


def test_apply_key_aliases_prefers_existing_target() -> None:
    rec = apply_key_aliases({"射撃補則": "old", "射撃補正": "new"})
    assert rec == {"射撃補正": "new"}


def test_normalize_ms_name_without_level_is_unchanged() -> None:
    assert normalize_ms_name("ザクII") == "ザクII"


def test_normalize_ms_name_with_level_normalizes_base() -> None:
    assert normalize_ms_name("ザクII_LV1") == "ザクⅡ_LV1"


def test_extract_ms_base_name_returns_none_without_level() -> None:
    assert extract_ms_base_name("ザクII") is None


def test_load_records_by_name_skips_blank_names(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps([{"MS名": "A"}, {"MS名": "  "}, {"x": 1}], ensure_ascii=False),
        encoding="utf-8",
    )
    assert list(load_records_by_name(path)) == ["A"]


def test_load_records_by_name_rejects_non_array(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_records_by_name(path)


def test_load_records_by_name_rejects_non_object_item(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        load_records_by_name(path)
