"""必要階級欄へ誤配置されたリサイクルチケット数の寄せ替えテスト。

atwiki のステータステーブルでは「必要リサイクルチケット」と「必要階級」が
隣接しており、チケット数だけが階級欄へ入ることがある
（例: キャノンガン pages/6138, 2026-08-20 実測）。
"""

from bs4 import BeautifulSoup

import ms_data.scraping.scrape_msdata as sm


def _build_records(rows: str, levels: list[int] | None = None) -> dict:
    html = f"""
    <table>
      <tr><th>項目</th><th>LV1</th><th>LV2</th></tr>
      {rows}
    </table>
    """
    table = BeautifulSoup(html, "html.parser").find("table")
    return sm.build_base_records(table, "テスト機", levels or [1, 2])


def test_numeric_rank_is_moved_to_recycle_tickets():
    recs = _build_records(
        """
        <tr><th>必要リサイクルチケット</th><td></td><td></td></tr>
        <tr><th>必要階級</th><td>225</td><td>260</td></tr>
        """
    )
    assert recs[1]["必要階級"] == ""
    assert recs[2]["必要階級"] == ""
    assert recs[1]["必要リサイクルチケット"] == 225
    assert recs[2]["必要リサイクルチケット"] == 260


def test_numeric_rank_does_not_overwrite_existing_tickets():
    recs = _build_records(
        """
        <tr><th>必要リサイクルチケット</th><td>245</td><td>245</td></tr>
        <tr><th>必要階級</th><td>225</td><td>260</td></tr>
        """
    )
    assert recs[1]["必要階級"] == ""
    assert recs[2]["必要階級"] == ""
    assert recs[1]["必要リサイクルチケット"] == 245
    assert recs[2]["必要リサイクルチケット"] == 245


def test_fullwidth_comma_rank_is_moved_to_recycle_tickets():
    recs = _build_records(
        """
        <tr><th>必要リサイクルチケット</th><td></td><td></td></tr>
        <tr><th>必要階級</th><td>１，２３４</td><td>225</td></tr>
        """
    )
    assert recs[1]["必要階級"] == ""
    assert recs[1]["必要リサイクルチケット"] == 1234
    assert recs[2]["必要リサイクルチケット"] == 225


def test_real_rank_values_are_kept():
    recs = _build_records(
        """
        <tr><th>必要リサイクルチケット</th><td></td><td></td></tr>
        <tr><th>必要階級</th><td>少尉01</td><td>大将10</td></tr>
        """
    )
    assert recs[1]["必要階級"] == "少尉01"
    assert recs[2]["必要階級"] == "大将10"
    assert "必要リサイクルチケット" not in recs[1]
    assert "必要リサイクルチケット" not in recs[2]
