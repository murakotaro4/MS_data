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


def test_fullst_with_hyphen_strong_sortie():
    """強行出撃のみ、ハイフン（-）は points: None で採用される。"""
    html = _make_html_with_fullst("""
        <tr><th>強行出撃</th><th>Lv1</th><td>-</td><td>効果:+500</td></tr>
    """)
    per_level = sm.parse_details(html)

    assert 1 in per_level
    rec = per_level[1]
    # 強行出撃のみ points: None を許可
    fullst = rec.get("fullst", [])
    assert len(fullst) == 1
    assert fullst[0]["name"] == "強行出撃"
    assert fullst[0]["level"] == 1
    assert fullst[0]["points"] is None


def test_fullst_with_hyphen_non_special():
    """ハイフン（-）は強行出撃以外では fullst に含めない。"""
    html = _make_html_with_fullst("""
        <tr><th>HP強化</th><th>Lv1</th><td>-</td><td>効果:+500</td></tr>
    """)
    per_level = sm.parse_details(html)

    assert 1 in per_level
    rec = per_level[1]
    assert "fullst" not in rec


def test_fullst_with_empty_cell():
    """空セルは（強行出撃以外） fullst に含めない。"""
    html = _make_html_with_fullst("""
        <tr><th>スピード強化</th><th>Lv1</th><td></td><td>効果:+2</td></tr>
    """)
    per_level = sm.parse_details(html)

    assert 1 in per_level
    rec = per_level[1]
    assert "fullst" not in rec


def test_fullst_sort_none_first():
    """None と数値が混在する場合のソート確認。

    実装では points: None を先頭に、その後数値を昇順でソートする。
    points: None は強行出撃のみ許可される。
    """
    # 数値あり・強行出撃（ハイフン）・数値あり の混在
    html = _make_html_with_fullst("""
        <tr><th>HP強化</th><th>Lv1</th><td>3000</td><td>効果:+500</td></tr>
        <tr><th>強行出撃</th><th>Lv1</th><td>-</td><td>効果:+2</td></tr>
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

    # 名前も確認（None が先頭なので強行出撃が最初）
    names = [e["name"] for e in rec["fullst"]]
    assert names == ["強行出撃", "スラスター強化", "HP強化"]


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


def test_fullst_skip_missing_points_per_level():
    """同じリストでも該当LVのpointsが無い場合は採用しない（強行出撃を除く）。"""
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
        <tr><th>AD-FCS</th><th>Lv1</th><td>1000</td><td>1100</td><td>効果:+5</td></tr>
      </table>

      <div id="label_sortie_G_S"></div>
      <div id="label_env_G_S"></div>
    </body></html>
    """
    per_level = sm.parse_details(html)

    assert 2 in per_level
    fullst = per_level[2].get("fullst", [])
    # LV2 では points がある行のみ採用
    assert len(fullst) == 1
    assert fullst[0]["name"] == "AD-FCS"
    assert fullst[0]["points"] == 1100


def test_fullst_strong_sortie_only_should_fallback_from_prev_level():
    """当該LVが強行出撃のみになった場合は直前LVの構成で補完する。"""
    html = """
    <html><head><title>テスト機体</title></head>
    <body>
      <div id="table_hanyou">
        <table>
          <thead>
            <tr><th></th><th>LV1</th><th>LV2</th></tr>
          </thead>
          <tbody>
            <tr><th>機体HP</th><td>28000</td><td>29000</td></tr>
            <tr><th>スピード</th><td>125</td><td>125</td></tr>
            <tr><th>スラスター</th><td>80</td><td>82</td></tr>
            <tr><th>高速移動</th><td>220</td><td>222</td></tr>
            <tr><th>射撃補正</th><td>35</td><td>37</td></tr>
            <tr><th>格闘補正</th><td>30</td><td>32</td></tr>
            <tr><th>耐ビーム補正</th><td>30</td><td>32</td></tr>
            <tr><th>耐実弾補正</th><td>26</td><td>28</td></tr>
            <tr><th>耐格闘補正</th><td>28</td><td>30</td></tr>
            <tr><th>旋回（地上）[度/秒]</th><td>66</td><td>66</td></tr>
          </tbody>
        </table>
      </div>
      <h3>パーツスロット</h3>
      <table>
        <tr><th>近距離</th><td>16</td><td>18</td></tr>
        <tr><th>中距離</th><td>24</td><td>26</td></tr>
        <tr><th>遠距離</th><td>8</td><td>10</td></tr>
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
        <tr><th>強行出撃</th><th>Lv1</th><td>-</td><td>-</td><td>効果:+500</td></tr>
        <tr><th>AD-PA</th><th>Lv1</th><td>2780</td><td>-</td><td>効果:+3</td></tr>
        <tr><th>冷却補助システム</th><th>Lv1</th><td>3640</td><td>-</td><td>効果:+5</td></tr>
      </table>

      <div id="label_sortie_G_S"></div>
      <div id="label_env_G_S"></div>
    </body></html>
    """
    per_level = sm.parse_details(html)

    assert 1 in per_level and 2 in per_level
    lv1_fullst = per_level[1].get("fullst", [])
    lv2_fullst = per_level[2].get("fullst", [])

    assert len(lv1_fullst) == 3
    assert [e["name"] for e in lv1_fullst] == ["強行出撃", "AD-PA", "冷却補助システム"]

    assert len(lv2_fullst) == 3
    assert [e["name"] for e in lv2_fullst] == [e["name"] for e in lv1_fullst]
    assert all(e["points"] is None for e in lv2_fullst)


def test_fullst_only_strong_sortie_remains_single_entry():
    """強行出撃のみが正しいケースはそのまま維持する。"""
    html = """
    <html><head><title>テスト機体</title></head>
    <body>
      <div id="table_hanyou">
        <table>
          <thead>
            <tr><th></th><th>LV1</th><th>LV2</th></tr>
          </thead>
          <tbody>
            <tr><th>機体HP</th><td>25000</td><td>26000</td></tr>
            <tr><th>スピード</th><td>120</td><td>120</td></tr>
            <tr><th>スラスター</th><td>75</td><td>77</td></tr>
            <tr><th>高速移動</th><td>215</td><td>217</td></tr>
            <tr><th>射撃補正</th><td>28</td><td>30</td></tr>
            <tr><th>格闘補正</th><td>26</td><td>28</td></tr>
            <tr><th>耐ビーム補正</th><td>26</td><td>28</td></tr>
            <tr><th>耐実弾補正</th><td>24</td><td>26</td></tr>
            <tr><th>耐格闘補正</th><td>24</td><td>26</td></tr>
            <tr><th>旋回（地上）[度/秒]</th><td>64</td><td>64</td></tr>
          </tbody>
        </table>
      </div>
      <h3>パーツスロット</h3>
      <table>
        <tr><th>近距離</th><td>12</td><td>14</td></tr>
        <tr><th>中距離</th><td>20</td><td>22</td></tr>
        <tr><th>遠距離</th><td>8</td><td>10</td></tr>
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
        <tr><th>強行出撃</th><th>Lv1</th><td>-</td><td>-</td><td>効果:+500</td></tr>
      </table>

      <div id="label_sortie_G_S"></div>
      <div id="label_env_G_S"></div>
    </body></html>
    """
    per_level = sm.parse_details(html)

    assert 1 in per_level and 2 in per_level
    for lv in (1, 2):
        fullst = per_level[lv].get("fullst", [])
        assert len(fullst) == 1
        assert fullst[0]["name"] == "強行出撃"
        assert fullst[0]["points"] is None
