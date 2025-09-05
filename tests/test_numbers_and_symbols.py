import scripts.scrape_msdata as sm


def test_to_int_extracts_head_integer():
    assert sm.to_int("81（盾装備時：78.6）") == 81
    assert sm.to_int("  15秒 ") == 15
    assert sm.to_int("235 [度/秒]") == 235
    assert sm.to_int("") is None


def test_symbol_to_bool():
    assert sm.symbol_to_bool("◯") is True
    assert sm.symbol_to_bool("×") is False
    assert sm.symbol_to_bool("可") is True
    assert sm.symbol_to_bool("不可") is False
    # 不明記号
    assert sm.symbol_to_bool("？") is None
