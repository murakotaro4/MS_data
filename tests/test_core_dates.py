from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from ms_data.core.dates import JST, parse_yyyymmdd_jst, today_jst


def test_parse_yyyymmdd_jst_returns_jst_aware_datetime():
    parsed = parse_yyyymmdd_jst("20260719")

    assert parsed == datetime(2026, 7, 19, tzinfo=JST)
    assert parsed.tzinfo is JST
    assert parsed.utcoffset() == timedelta(hours=9)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "2026-07-19",
        "20260230",
        "2026111",
        "202611",
        "202601010",
        "２０２６０１０１",
        "2026010a",
        "2026011 ",
        "20230229",
    ],
)
def test_parse_yyyymmdd_jst_rejects_invalid_value(value: str):
    with pytest.raises(ValueError):
        parse_yyyymmdd_jst(value)


def test_parse_yyyymmdd_jst_accepts_leap_day():
    assert parse_yyyymmdd_jst("20240229") == datetime(2024, 2, 29, tzinfo=JST)


def test_today_jst_uses_jst_clock_not_local():
    fixed = datetime(2026, 7, 29, 23, 30, tzinfo=JST)
    with patch("ms_data.core.dates.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed
        assert today_jst() == "20260729"
        mock_datetime.now.assert_called_once_with(JST)
