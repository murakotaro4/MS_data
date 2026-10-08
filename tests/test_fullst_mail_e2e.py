"""実通知の差分fixtureをCLIから生成し、左右比較とテキストの意味を検証する。"""

from pathlib import Path

from bs4 import BeautifulSoup

from ms_data.reporting.build_update_mail_body import main


def test_actual_20261009_mail_comparison(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures/reports/diff_msdata_20261009.md"
    text, html = tmp_path / "mail.txt", tmp_path / "mail.html"
    assert main([
        "--report-date", "20261009", "--result", "マージ済み", "--changed", "true",
        "--diff-path", str(fixture), "--out", str(text), "--html-out", str(html),
    ]) == 0
    soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
    tables = soup.select(".enhancements")
    assert len(tables) == 2
    expected = [
        [("AD-PA", 1, 1030), ("耐格闘装甲補強", 1, 2060),
         ("フレーム補強", 1, 3090), ("複合拡張パーツスロット", 1, 4120),
         ("AD-PA", 4, 8240), ("緊急格闘防御機構", 1, 12360)],
        [("耐ビーム装甲補強", 1, 660), ("耐格闘装甲補強", 1, 1320),
         ("AD-PA", 1, 1980), ("複合拡張パーツスロット", 1, 2650),
         ("耐ビーム装甲補強", 4, 5300), ("AD-PA", 4, 7950)],
    ]
    plain = text.read_text(encoding="utf-8")
    for table, skills in zip(tables, expected, strict=True):
        assert [th.get_text() for th in table.select("thead th")] == [
            "強化項目・強化Lv", "変更前", "変更後"]
        rows = table.select("tbody tr")
        assert len(rows) == 6
        for row, (name, level, points) in zip(rows, skills, strict=True):
            assert [cell.get_text(" ", strip=True) for cell in row.select("th,td")] == [
                f"{name} 強化Lv{level}", "値なし", f"{points:,}"]
            assert f"{name}（強化Lv{level}）" in plain
            assert str(points) in plain
    for name in ["ディマーテル", "プロトタイプΖΖガンダム", "キャノンガンダム"]:
        assert name in soup.get_text() and name in plain
    assert "必要リサイクルチケット" in soup.get_text() and "380" in plain
    assert "機体LV2" in soup.get_text()
    assert "必要強化値" in soup.get_text() and "必要強化値" in plain
    assert "null" not in plain and "fullst" not in plain
    assert "6件 | 6件" not in plain
    assert len(html.read_bytes()) <= 80 * 1024
