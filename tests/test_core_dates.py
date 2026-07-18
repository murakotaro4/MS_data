from datetime import datetime, timedelta

import pytest

from ms_data.core.dates import JST, parse_yyyymmdd_jst


def test_parse_yyyymmdd_jst_returns_jst_aware_datetime():
    parsed = parse_yyyymmdd_jst("20260719")

    assert parsed == datetime(2026, 7, 19, tzinfo=JST)
    assert parsed.tzinfo is JST
    assert parsed.utcoffset() == timedelta(hours=9)


@pytest.mark.parametrize("value", ["", "2026-07-19", "20260230"])
def test_parse_yyyymmdd_jst_rejects_invalid_value(value: str):
    with pytest.raises(ValueError):
        parse_yyyymmdd_jst(value)
