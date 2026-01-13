"""fullst の points 処理に関するテスト（数値/ハイフン/空セル/ソート）"""
import scripts.scrape_msdata as sm


def _make_html_with_fullst(fullst_rows: str) -> str:
    """強化リスト情報テーブルを含む最小限のHTMLを生成する。

    Args:
        fullst_rows: 強化リストテーブルの <tr> 要素群（文字列）

    Returns:
        parse_details に渡せる完全なHTML文字列
    """
    return f"""
    <html><head><title>テスト機体</title></head>
    <body>
      <div id="table_hanyou">
        <table>
          <thead>
            <tr><th></th><th>LV1</th></tr>
          </thead>
          <tbody>
            <tr><th>機体HP</th><td>10000</td></tr>
            <tr><th>スピード</th><td>120</td></tr>
            <tr><th>スラスター</th><td>60</td></tr>
            <tr><th>高速移動</th><td>180</td></tr>
            <tr><th>射撃補正</th><td>15</td></tr>
            <tr><th>格闘補正</th><td>10</td></tr>
            <tr><th>耐ビーム補正</th><td>8</td></tr>
            <tr><th>耐実弾補正</th><td>10</td></tr>
            <tr><th>耐格闘補正</th><td>6</td></tr>
            <tr><th>旋回（地上）[度/秒]</th><td>75</td></tr>
          </tbody>
        </table>
      </div>
      <h3>パーツスロット</h3>
      <table>
        <tr><th>近距離</th><td>8</td></tr>
        <tr><th>中距離</th><td>6</td></tr>
        <tr><th>遠距離</th><td>4</td></tr>
      </table>

      <h2>強化リスト情報</h2>
      <table>
        <tr>
          <th>強化リスト名</th>
          <th>リストLv</th>
          <th>LV1</th>
          <th>効果</th>
        </tr>
        {fullst_rows}
      </table>

      <div id="label_sortie_G_S"></div>
      <div id="label_env_G_S"></div>
    </body></html>
    """


def test_fullst_with_numeric_points():
    """数値が入っている場合 → points: 数値（例: 2580）"""
    html = _make_html_with_fullst("""
        <tr><th>HP強化</th><th>Lv1</th><td>2580</td><td>効果:+500</td></tr>
    """)
    per_level = sm.parse_details(html)

    assert 1 in per_level
    rec = per_level[1]
    assert "fullst" in rec
    assert len(rec["fullst"]) == 1
    assert rec["fullst"][0]["name"] == "HP強化"
    assert rec["fullst"][0]["level"] == 1
    assert rec["fullst"][0]["points"] == 2580


def test_fullst_with_hyphen():
    """ハイフン（-）が入っている場合 → points: None

    to_int("-") が None を返すが、その行も fullst に追加される。
    points: None として記録される。
    """
    html = _make_html_with_fullst("""
        <tr><th>HP強化</th><th>Lv1</th><td>-</td><td>効果:+500</td></tr>
    """)
    per_level = sm.parse_details(html)

    assert 1 in per_level
    rec = per_level[1]
    # ハイフンの場合、points: None で fullst に追加される
    fullst = rec.get("fullst", [])
    assert len(fullst) == 1
    assert fullst[0]["name"] == "HP強化"
    assert fullst[0]["level"] == 1
    assert fullst[0]["points"] is None


def test_fullst_with_empty_cell():
    """空セルの場合 → points: None

    空セルも to_int が None を返すが、その行も fullst に追加される。
    points: None として記録される。
    """
    html = _make_html_with_fullst("""
        <tr><th>スピード強化</th><th>Lv1</th><td></td><td>効果:+2</td></tr>
    """)
    per_level = sm.parse_details(html)

    assert 1 in per_level
    rec = per_level[1]
    # 空セルの場合、points: None で fullst に追加される
    fullst = rec.get("fullst", [])
    assert len(fullst) == 1
    assert fullst[0]["name"] == "スピード強化"
    assert fullst[0]["level"] == 1
    assert fullst[0]["points"] is None


def test_fullst_sort_none_first():
    """None と数値が混在する場合のソート確認。

    実装では points: None を先頭に、その後数値を昇順でソートする。
    ハイフンや空セルがある行は points: None として追加される。
    """
    # 数値あり・ハイフン・数値あり の混在
    html = _make_html_with_fullst("""
        <tr><th>HP強化</th><th>Lv1</th><td>3000</td><td>効果:+500</td></tr>
        <tr><th>スピード強化</th><th>Lv1</th><td>-</td><td>効果:+2</td></tr>
        <tr><th>スラスター強化</th><th>Lv1</th><td>1000</td><td>効果:+5</td></tr>
    """)
    per_level = sm.parse_details(html)

    assert 1 in per_level
    rec = per_level[1]
    assert "fullst" in rec
    assert len(rec["fullst"]) == 3

    # points: None が先頭、その後数値が昇順
    points_list = [e["points"] for e in rec["fullst"]]
    assert points_list == [None, 1000, 3000]

    # 名前も確認（None が先頭なのでスピード強化が最初）
    names = [e["name"] for e in rec["fullst"]]
    assert names == ["スピード強化", "スラスター強化", "HP強化"]


def test_fullst_fallback_with_none_points():
    """上位レベルの fullst が下位レベルにコピーされる際の points: None 確認。

    LV1 には fullst 数値があり、LV2 以降には数値がない場合、
    LV2 以降には LV1 の構造がコピーされ points: None となる。
    """
    # LV1 と LV2 両方を含むHTML
    html = """
    <html><head><title>テスト機体</title></head>
    <body>
      <div id="table_hanyou">
        <table>
          <thead>
            <tr><th></th><th>LV1</th><th>LV2</th></tr>
          </thead>
          <tbody>
            <tr><th>機体HP</th><td>10000</td><td>11000</td></tr>
            <tr><th>スピード</th><td>120</td><td>120</td></tr>
            <tr><th>スラスター</th><td>60</td><td>62</td></tr>
            <tr><th>高速移動</th><td>180</td><td>182</td></tr>
            <tr><th>射撃補正</th><td>15</td><td>17</td></tr>
            <tr><th>格闘補正</th><td>10</td><td>12</td></tr>
            <tr><th>耐ビーム補正</th><td>8</td><td>9</td></tr>
            <tr><th>耐実弾補正</th><td>10</td><td>11</td></tr>
            <tr><th>耐格闘補正</th><td>6</td><td>7</td></tr>
            <tr><th>旋回（地上）[度/秒]</th><td>75</td><td>76</td></tr>
          </tbody>
        </table>
      </div>
      <h3>パーツスロット</h3>
      <table>
        <tr><th>近距離</th><td>8</td><td>9</td></tr>
        <tr><th>中距離</th><td>6</td><td>7</td></tr>
        <tr><th>遠距離</th><td>4</td><td>5</td></tr>
      </table>

      <h2>強化リスト情報</h2>
      <table>
        <tr>
          <th>強化リスト名</th>
          <th>リストLv</th>
          <th>LV1</th>
          <th>LV2</th>
          <th>効果</th>
        </tr>
        <tr><th>HP強化</th><th>Lv1</th><td>2000</td><td>-</td><td>効果:+500</td></tr>
        <tr><th>HP強化</th><th>Lv2</th><td>4000</td><td>-</td><td>効果:+1000</td></tr>
      </table>

      <div id="label_sortie_G_S"></div>
      <div id="label_env_G_S"></div>
    </body></html>
    """
    per_level = sm.parse_details(html)

    # LV1 には数値あり
    assert 1 in per_level
    assert "fullst" in per_level[1]
    lv1_fullst = per_level[1]["fullst"]
    assert len(lv1_fullst) == 2
    assert lv1_fullst[0]["points"] == 2000
    assert lv1_fullst[1]["points"] == 4000

    # LV2 には数値がないため、LV1 の構造がコピーされ points: None
    assert 2 in per_level
    assert "fullst" in per_level[2]
    lv2_fullst = per_level[2]["fullst"]
    assert len(lv2_fullst) == 2
    # フォールバックコピーでは points: None
    assert lv2_fullst[0]["points"] is None
    assert lv2_fullst[1]["points"] is None
    # 名前とレベルは保持
    assert lv2_fullst[0]["name"] == "HP強化"
    assert lv2_fullst[1]["name"] == "HP強化"
