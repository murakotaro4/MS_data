from scripts.label_utils import clean_text, normalize_row_label, apply_key_aliases


def test_clean_and_normalize():
    assert clean_text("  A   B \t C  ") == "A B C"
    # 半角()内の注記は除去、全角（）は保持
    assert normalize_row_label("旋回（地上）( +25 )") == "旋回（地上）"


def test_key_aliases():
    rec = {"射撃補生": 10, "格闘補定": 15, "旋回_通常時_地上": 80}
    out = apply_key_aliases(rec)
    assert "射撃補正" in out and out["射撃補正"] == 10
    assert "格闘補正" in out and out["格闘補正"] == 15
    assert "旋回_地上_通常時" in out and out["旋回_地上_通常時"] == 80
