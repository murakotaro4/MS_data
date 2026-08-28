
import ms_data.scraping.scrape_msdata as sm


def test_parse_details_minimal_golden():
    html = """
    <html><head><title>ゴールデンMS</title></head>
    <body>
      <div id="table_hanyou">
        <table>
          <thead>
            <tr><th></th><th>LV1</th></tr>
          </thead>
          <tbody>
            <tr><th>機体HP</th><td>12000</td></tr>
            <tr><th>スピード</th><td>130</td></tr>
            <tr><th>スラスター</th><td>65</td></tr>
            <tr><th>高速移動</th><td>200</td></tr>
            <tr><th>射撃補正</th><td>20</td></tr>
            <tr><th>格闘補正</th><td>15</td></tr>
            <tr><th>耐ビーム補正</th><td>10</td></tr>
            <tr><th>耐実弾補正</th><td>12</td></tr>
            <tr><th>耐格闘補正</th><td>8</td></tr>
            <tr><th>旋回（地上）[度/秒]</th><td>81（盾装備時：78.6）</td></tr>
          </tbody>
        </table>
      </div>
      <h3>パーツスロット</h3>
      <table>
        <tr><th>近距離</th><td>10</td></tr>
        <tr><th>中距離</th><td>8</td></tr>
        <tr><th>遠距離</th><td>6</td></tr>
      </table>

      <h2>強化リスト情報</h2>
      <table>
        <tr><th>スピード強化</th><th>Lv1</th><td>200</td><td>効果:+2</td></tr>
        <tr><th>スピード強化</th><th>Lv2</th><td>400</td><td>効果:+3</td></tr>
      </table>

      <div id="label_sortie_G_S"></div>
      <div id="label_env_G_S"></div>
    </body></html>
    """
    per_level = sm.parse_details(html)
    # 1レベルのみ抽出される想定
    assert set(per_level.keys()) == {1}
    rec = per_level[1]
    # 必須キーが満たされていること
    required = {
        "HP",
        "スピード",
        "スラスター",
        "高速移動",
        "射撃補正",
        "格闘補正",
        "耐ビーム補正",
        "耐実弾補正",
        "耐格闘補正",
        "近スロット",
        "中スロット",
        "遠スロット",
        "旋回_地上_通常時",
    }
    assert required.issubset(rec.keys())
    assert rec["HP"] == 12000
    assert rec["旋回_地上_通常時"] == 81  # 先頭整数を採用
    assert rec["近スロット"] == 10 and rec["中スロット"] == 8 and rec["遠スロット"] == 6
    # 出撃/環境適正
    assert rec["出撃_地上可"] is True and rec["出撃_宇宙可"] is True
    assert rec["環境適正_地上"] is True and rec["環境適正_宇宙"] is True
    # 属性判定（hanyou → 汎用）
    assert rec["属性"] == "汎用"
    # fullst が構築されている（points 昇順で2件）
    assert isinstance(rec.get("fullst"), list)
    assert [e["points"] for e in rec["fullst"]] == [200, 400]
