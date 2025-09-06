import json
from scripts.extract_skills import extract_skills_from_html, extract_skill_owners_from_html
from bs4 import BeautifulSoup


def test_extract_exam_lv1_basic():
    html = """
    <table>
      <tr>
        <th rowspan="2">能力UP「EXAM」</th>
        <td>LV1</td>
        <td>タッチパッドを押すことで任意発動し、攻撃力、防御力、機動力が一定時間上昇。</td>
        <td>
          発動中は<br/>
          ・射撃補正＋25<br/>
          ・スピード＋10<br/>
          ・スラスター消費－50%<br/>
          ※効果時間は、60秒<br/>
          ※発動した瞬間のカットシーン中は、無敵
        </td>
      </tr>
    </table>
    """
    data = extract_skills_from_html(html)
    skills = data["skills"]
    assert skills, "skills not parsed"
    exam = next((s for s in skills if s["name"].startswith("能力UP「EXAM")), None)
    assert exam is not None
    lv1 = exam["levels"][0]
    assert lv1["level"] == 1
    eff = lv1.get("effects") or {}
    assert eff.get("射撃補正", {}).get("value") == 25
    assert abs(eff.get("スラスター消費", {}).get("factor") - 0.5) < 1e-6
    assert lv1.get("duration_sec") == 60
    assert "invincible_on_cast" in (lv1.get("tags") or [])


def test_extract_ntd_and_awaken():
    html = """
    <table>
      <tr>
        <th rowspan="2">能力UP「NT-D」</th>
        <td>LV1</td>
        <td>機体HPが80％以下でタッチパッドを押すと各部位のHPを全回復し機体が変身状態となる。</td>
        <td>
          ・発動後スキルや兵装が変化<br/>
          ・発動中 75/秒 の継続ダメージ発生<br/>
          ※効果時間は、無し
        </td>
      </tr>
      <tr>
        <td>LV2</td>
        <td>機体HPが80％以下でタッチパッドを押すと各部位のHPを全回復し機体が変身状態となる。</td>
        <td>
          ・発動中 30/秒 の継続ダメージ発生<br/>
          ※効果時間は、無し
        </td>
      </tr>
      <tr>
        <th>能力UP「覚醒」</th>
        <td>LV1</td>
        <td>能力UP「NT-D」の状態を一定時間維持した後、タッチパッドを押すと発動する。</td>
        <td>
          ・発動時HP 4000 回復<br/>
          ・被ダメージ 15% 軽減
        </td>
      </tr>
    </table>
    """
    data = extract_skills_from_html(html)
    skills = data["skills"]
    ntd = next((s for s in skills if s["name"].startswith("能力UP「NT-D")), None)
    assert ntd is not None
    lv1 = next(l for l in ntd["levels"] if l["level"] == 1)
    assert lv1.get("hp_drain_per_sec") == 75
    lv2 = next(l for l in ntd["levels"] if l["level"] == 2)
    assert lv2.get("hp_drain_per_sec") == 30
    # 覚醒が phases としてぶら下がる
    phases = ntd.get("phases") or []
    assert phases, "awaken phase not attached"
    ak_lv1 = phases[0]["levels"][0]
    assert ak_lv1.get("hp_heal") == 4000
    eff = ak_lv1.get("effects") or {}
    assert abs(eff.get("被ダメージ", {}).get("factor") - 0.85) < 1e-6


def test_extract_skill_owners_from_html_min():
    html = """
    <table>
      <tr>
        <th rowspan="3"><a id="能力UP「EXAM」LV1" name="能力UP「EXAM」LV1"></a>能力UP「EXAM」 LV1</th>
        <th>強<br/>襲</th>
        <td><a href="/battle-operation2/pages/621.html">イフリート改</a></td>
        <td></td>
      </tr>
      <tr>
        <th>汎<br/>用</th>
        <td><a href="/battle-operation2/pages/1005.html">ブルーディスティニー3号機</a></td>
        <td></td>
      </tr>
      <tr>
        <th>支<br/>援</th>
        <td></td><td></td>
      </tr>
      <tr>
        <th><a id="能力UP「HADES」LV1"></a>能力UP「HADES」 LV1</th>
        <td></td><td></td>
      </tr>
    </table>
    """
    soup = BeautifulSoup(html, "lxml")
    owners = extract_skill_owners_from_html(soup)
    d = { (o['name'], o['level']) : o['owners'] for o in owners }
    assert ("能力UP「EXAM」", 1) in d
    assert "イフリート改" in d[("能力UP「EXAM」", 1)]
    assert any("ブルーディスティニー3号機" in x for x in d[("能力UP「EXAM」", 1)])
