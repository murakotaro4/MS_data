"""atwiki スキル一覧の HTML 解析とスキル抽出を担う純関数群。"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from ms_data.scraping.text_values import normalize_symbol_text
from ms_data.scraping.skill_owners import SKILL_URL, _RE_ANCHOR

# たたき台の対象スキル（名称は atwiki の見出しに合わせる）
CORE_SKILLS = [
    "能力UP「EXAM】",  # guard for variant quotes; will match via startswith
    "能力UP「EXAM",
    "能力UP「HADES",
    "能力UP「HADES-E",
    "能力UP「ALICE",
    "能力UP「ZEUS",
    "能力UP「バイオセンサー",
    "能力UP「バイオセンサーP",
    "能力UP「バイオセンサーM",
    "能力UP「簡易バイオセンサー",
    "能力UP「NT-D",
    "能力UP「覚醒",
]


# ===============
# パーサ補助
# ===============


_norm = normalize_symbol_text


def _to_int_first(text: str) -> int | None:
    """文字列中の最初の整数を取り出す。"""
    m = re.search(r"-?\d+", text)
    return int(m.group(0)) if m else None


def _percent_to_factor(text: str, sign: int = -1) -> float | None:
    """ "-20%" のような百分率を乗算係数に変換する（sign=-1 で軽減 → 0.8）。"""
    # sign: -1 for reductions like "-20%" -> 0.8; +1 reserved for increases if needed
    m = re.search(r"(\d+)%", text)
    if not m:
        return None
    p = int(m.group(1))
    p = p * sign
    return round(1.0 + (p / 100.0), 6)


def _extract_activation(desc: str) -> dict[str, Any]:
    """説明文から発動方式（手動/自動）と発動条件（HP閾値等）を推定する。"""
    t = _norm(desc)
    act: dict[str, Any] = {}
    if "タッチパッドを押す" in t or "任意発動" in t:
        act["type"] = "manual"
        act["trigger"] = "touchpad"
    if "自動で発動" in t or "自動で" in t:
        act["type"] = "auto"
    m = re.search(r"HP\s*(\d+)%以下", t)
    if m:
        act.setdefault("conditions", {})["hp_leq_percent"] = int(m.group(1))
    m = re.search(r"使用から\s*(\d+)秒\s*経過で発動可", t)
    if m:
        act.setdefault("conditions", {})["after_seconds_to_trigger"] = int(m.group(1))
    return act


def _extract_duration(text: str) -> int | None:
    """説明文から効果時間（秒）を推定する。「効果時間は無し」は None。"""
    t = _norm(text)
    if "効果時間は無し" in t or "効果時間は、無し" in t:
        return None
    m = re.search(r"効果時間[は、: ]*([0-9]+)秒", t)
    if m:
        return int(m.group(1))
    # 別表現（例: ※効果時間は 75秒）
    m = re.search(r"([0-9]+)秒", t)
    if m and ("効果" in t or "時間" in t):
        return int(m.group(1))
    return None


def _parse_grants(line: str) -> dict[str, Any] | None:
    """「<スキル名> LvN が付与」形式の行を {skill, level} に変換する。"""
    t = _norm(line)
    # 例: 緊急回避制御 Lv2 が付与 / Lv3 が付与
    m = re.search(
        r"([A-Za-z0-9ぁ-んァ-ン一-龥・\-\[\]（）\(\)]+?)\s*Lv\s*(\d+)が付与", t
    )
    if m:
        return {"skill": m.group(1).strip(), "level": int(m.group(2))}
    return None


def _effects_from_lines(lines: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """詳細の箇条書きから数値補正（effects）と補助情報（aux）を抽出する。

    effects: 射撃補正/スピード等の加算・スラスター消費等の乗算
    aux: 継続ダメージ・回復量・無敵等のタグ
    """
    effects: dict[str, Any] = {}
    aux: dict[str, Any] = {}
    for raw in lines:
        if not raw:
            continue
        s = _norm(raw)
        # 代表的な数値補正
        for k in ["射撃補正", "格闘補正", "スピード", "高速移動", "旋回", "旋回性能"]:
            if k in s:
                m = re.search(r"([+\-]\s*\d+)", s)
                if m:
                    val = int(m.group(1).replace(" ", ""))
                    key = "旋回" if k in ("旋回", "旋回性能") else k
                    effects[key] = {"op": "add", "value": val}
                    continue
        # 各耐性 +N （→3耐性へ展開はシミュ層で解釈）
        if "各耐性" in s:
            m = re.search(r"([+\-]\s*\d+)", s)
            if m:
                val = int(m.group(1).replace(" ", ""))
                effects["各耐性"] = {"op": "add", "value": val}
                continue
        # スラスター消費 -% （消費減 → 係数<1）
        if "スラスター消費" in s and "%" in s:
            f = _percent_to_factor(s, sign=-1)
            if f is not None:
                effects["スラスター消費"] = {"op": "mul", "factor": f}
                continue
        # 被ダメージ % 軽減 → 係数
        if "被ダメージ" in s and "%" in s and ("軽減" in s or "減少" in s):
            f = _percent_to_factor(s, sign=-1)
            if f is not None:
                effects["被ダメージ"] = {"op": "mul", "factor": f}
                continue
        # 継続ダメージ x/秒
        if "継続ダメージ" in s and "/秒" in s:
            m = re.search(r"(\d+)\s*/\s*秒", s)
            if m:
                aux["hp_drain_per_sec"] = int(m.group(1))
                continue
        # 回復
        if "回復" in s and _to_int_first(s) is not None:
            amt = _to_int_first(s)
            if "味方" in s or "自機及び味方" in s:
                aux["hp_heal_team"] = amt
            else:
                aux["hp_heal"] = amt
            continue
        # 免疫・無敵等（タグ化）
        if "無敵" in s or "ダメージリアクション無効" in s:
            tags = set(aux.get("tags", []))
            if "無敵" in s:
                tags.add("invincible_on_cast")
            if "ダメージリアクション無効" in s:
                tags.add("no_reaction_on_cast")
            aux["tags"] = sorted(tags)
            continue
    return effects, aux


def _split_lines(text: str) -> list[str]:
    """詳細セルの HTML/テキストを「・」と改行でおおまかな行に分割する。"""
    t = _norm(text.replace("\r", "\n").replace("<br>", "\n").replace("<br/>", "\n"))
    # 「・」や改行でおおまかに分割
    parts: list[str] = []
    for seg in re.split(r"[\n\r]+", t):
        seg = seg.strip()
        if not seg:
            continue
        if "・" in seg:
            for p in seg.split("・"):
                if p.strip():
                    parts.append(p.strip())
        else:
            parts.append(seg)
    return parts


# ===============
# 解析本体
# ===============


def extract_skills_from_html(html: str) -> dict[str, Any]:
    """スキル一覧ページから CORE_SKILLS 対象の構造化データを抽出する。

    行ごとに LV・説明・詳細を読み、効果/発動条件/効果時間を推定。
    後処理で NT-D の覚醒フェーズ紐付けと、同一 LV の重複統合
    （情報量スコアが最大の行を採用）を行う。
    """
    soup = BeautifulSoup(html, "lxml")
    skills: dict[str, dict[str, Any]] = {}

    cur_skill: str | None = None
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        if th and th.get_text():
            th_text = _norm(th.get_text())
            # 対象スキル名の先頭一致
            if any(th_text.startswith(x) for x in CORE_SKILLS):
                cur_skill = th_text.split(" ")[0]  # 行末の余分を落とす
        tds = tr.find_all("td")
        if not tds or not cur_skill:
            continue

        # 期待列: LV / desc / details（details は箇条書きが多い）
        lv_txt = _norm(tds[0].get_text(" ")) if len(tds) >= 1 else ""
        desc_txt = _norm(tds[1].get_text(" ")) if len(tds) >= 2 else ""
        details_txt = tds[2].decode_contents() if len(tds) >= 3 else ""

        m_lv = re.search(r"LV\s*(\d+)", lv_txt, flags=re.IGNORECASE)
        level = int(m_lv.group(1)) if m_lv else 1

        act = _extract_activation(
            desc_txt + "\n" + BeautifulSoup(details_txt, "lxml").get_text(" ")
        )
        duration = _extract_duration(
            BeautifulSoup(details_txt, "lxml").get_text(" ")
        ) or _extract_duration(desc_txt)

        details_plain = _norm(BeautifulSoup(details_txt, "lxml").get_text(" "))
        lines = _split_lines(details_txt)
        effects, aux = _effects_from_lines(lines)
        # フォールバック: 代表タグのワード検出
        if "無敵" in details_plain:
            tags = set(aux.get("tags", []))
            tags.add("invincible_on_cast")
            aux["tags"] = sorted(tags)

        rec = {
            "name": cur_skill,
            "level": level,
            "activation": act or None,
            "duration_sec": duration,
            "effects": effects or None,
        }
        rec.update(aux)

        skills.setdefault(cur_skill, {"name": cur_skill, "levels": []})[
            "levels"
        ].append(rec)

    # 後処理: NT-D 系の派生（覚醒）を phase として紐付け（簡易）
    out_skills: list[dict[str, Any]] = []
    nt = None
    for _k in list(skills.keys()):
        if _k.startswith("能力UP「NT-D"):
            nt = skills[_k]
            break
    awaken = []
    for k in list(skills.keys()):
        if k.startswith("能力UP「覚醒"):
            awaken.append(skills.pop(k))
    if nt and awaken:
        nt["phases"] = awaken

    # レベル配列のノイズ除去＋重複統合（同一 level は代表1件に絞る）
    def score_level(lv: dict[str, Any], idx: int) -> tuple[int, int]:
        eff = lv.get("effects") or {}
        score = 0
        score += len(eff.keys())
        if (lv.get("activation") or {}).get("type"):
            score += 1
        if lv.get("duration_sec") is not None:
            score += 1
        if lv.get("hp_drain_per_sec") is not None:
            score += 1
        if lv.get("hp_heal") is not None or lv.get("hp_heal_team") is not None:
            score += 1
        # idxで早い方を優先（tie-breaker: 小さいidxが先）
        return (score, -idx)

    for v in skills.values():
        levels = v.get("levels", [])
        # まず空（すべてNone/空）を除去
        nonempty: list[dict[str, Any]] = []
        for lv in levels:
            if any(
                [
                    lv.get("effects"),
                    lv.get("hp_drain_per_sec") is not None,
                    lv.get("hp_heal") is not None,
                    lv.get("hp_heal_team") is not None,
                    (lv.get("activation") or {}).get("type"),
                    lv.get("duration_sec") is not None,
                ]
            ):
                nonempty.append(lv)
        # levelごとにベストを選ぶ
        best_by_level: dict[int, tuple[tuple[int, int], dict[str, Any]]] = {}
        for idx, lv in enumerate(nonempty):
            lvl = int(lv.get("level") or 0)
            sc = score_level(lv, idx)
            prev = best_by_level.get(lvl)
            if not prev or sc > prev[0]:
                best_by_level[lvl] = (sc, lv)
        # 復元（level順）
        v["levels"] = [best_by_level[k][1] for k in sorted(best_by_level.keys())]

    # 並べ替え（名前昇順）
    for k in sorted(skills.keys()):
        out_skills.append(skills[k])

    owners = extract_skill_owners_from_html(soup)
    return {"source": SKILL_URL, "skills": out_skills, "skill_owners": owners}


def extract_skill_owners_from_html(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """スキル逆引きテーブルから所持機体を収集（対象: 能力UP系）。

    形式例（th 内の <a id="能力UP「EXAM」LV1">...）を起点に、次のスキル見出しが来るまでの行の td 内リンクを収集。
    戻り: [{name, level, owners: [ms_name, ...]}]
    """
    results: list[dict[str, Any]] = []
    # 1) アンカーを列挙
    anchors = []
    for a in soup.find_all("a"):
        aid = (a.get("id") or "").strip()
        if not aid:
            continue
        m = _RE_ANCHOR.match(aid)
        if not m:
            continue
        name = m.group(1)
        level = int(m.group(2))
        # 対象スキルのみ
        if not any(name.startswith(x.replace("】", "")) for x in CORE_SKILLS):
            continue
        # th（スキル見出し）行を取得
        th = a.find_parent("th")
        if not th:
            continue
        tr = th.find_parent("tr")
        if not tr:
            continue
        anchors.append((name, level, tr))

    # 2) 各アンカーから次アンカー直前までの td 内リンクを収集
    for idx, (name, level, tr) in enumerate(anchors):
        owners: list[str] = []
        # 次のアンカー行（または表終端）まで前進
        stop_tr = anchors[idx + 1][2] if idx + 1 < len(anchors) else None
        # まず見出し行自身の td を走査
        for td in tr.find_all("td"):
            for a in td.find_all("a"):
                t = _norm(a.get_text(" "))
                if t and not re.fullmatch(r"[\W_]+", t):
                    owners.append(t)
        cur = tr
        while True:
            cur = cur.find_next_sibling("tr")
            if not cur:
                break
            if stop_tr and cur is stop_tr:
                break
            # td 内のリンクテキストを収集
            for td in cur.find_all("td"):
                for a in td.find_all("a"):
                    t = _norm(a.get_text(" "))
                    # 機体名らしきものだけ取り込む（英数記号のみや空は除外）
                    if t and not re.fullmatch(r"[\W_]+", t):
                        owners.append(t)
        # 正規化・重複除去
        uniq = sorted({o for o in owners})
        # 所持機体が空の段はスキップ
        if uniq:
            results.append({"name": name, "level": level, "owners": uniq})
    return results


# ==========================
# テーブル形式での厳格抽出（Row化）
# ==========================


def _select_main_skill_table(soup: BeautifulSoup) -> Tag | None:
    """ページ内のうち、スキル一覧の“本体テーブル”と推定される table を返す。

    ヒューリスティック:
    - 各 table を走査して `LV\\d+` を含む行数をスコア化
    - th（スキル名）+ td（LV）構成の行が多いテーブルを採用
    - 最大スコアのテーブルを返す
    """
    best = None
    best_score = -1
    for tbl in soup.find_all("table"):
        score = 0
        rows = tbl.find_all("tr")
        for tr in rows:
            th = tr.find("th")
            tds = tr.find_all("td")
            if th and tds:
                lv_txt = _norm(tds[0].get_text(" ")) if tds else ""
                if re.search(r"\bLV\s*\d+\b", lv_txt, flags=re.IGNORECASE):
                    score += 1
        # 候補の中から最大スコアを採用
        if score > best_score and score >= 5:  # 閾値は暫定
            best = tbl
            best_score = score
    return best


def extract_skill_rows_table(html: str) -> dict[str, Any]:
    """スキル一覧テーブルを“行”として抽出（スキル名/レベル/効果説明/詳細）。

    出力: { source, rows: [ {skill, level, desc, details_text, details_html} ] }
    注意: 解析のみ（正規化/集約は行わない）。rowspan により th/desc が欠落する行は直前の値を継承する。
    """
    soup = BeautifulSoup(html, "lxml")
    tbl = _select_main_skill_table(soup)
    if not tbl:
        return {"source": SKILL_URL, "rows": []}

    rows_out: list[dict[str, Any]] = []
    cur_skill = None
    cur_desc = None
    for tr in tbl.find_all("tr"):
        th = tr.find("th")
        if th and th.get_text(" "):
            cur_skill = _norm(th.get_text(" "))
        tds = tr.find_all("td")
        if not tds:
            continue
        # LV は最初の td を想定
        lv_txt = _norm(tds[0].get_text(" ")) if len(tds) >= 1 else ""
        m_lv = re.search(r"LV\s*(\d+)", lv_txt, flags=re.IGNORECASE)
        if not m_lv:
            # LVが無い行はスキップ
            continue
        level = int(m_lv.group(1))

        # desc / details は 2列目・3列目（rowspanの都合で欠けることがある）
        if len(tds) >= 2:
            # 判別: 2列しかない場合は details の可能性が高い
            if len(tds) == 2:
                # details のみ
                details_html = tds[1].decode_contents()
                details_text = _norm(BeautifulSoup(details_html, "lxml").get_text(" "))
                desc_text = cur_desc
            else:
                # 3列めまである場合: [LV, desc, details]
                desc_text = _norm(tds[1].get_text(" "))
                cur_desc = desc_text or cur_desc
                details_html = tds[2].decode_contents()
                details_text = _norm(BeautifulSoup(details_html, "lxml").get_text(" "))
        else:
            # 想定外
            desc_text = cur_desc
            details_html = ""
            details_text = ""

        rows_out.append(
            {
                "skill": cur_skill,
                "level": level,
                "desc": desc_text,
                "details_text": details_text,
                "details_html": details_html,
            }
        )

    return {"source": SKILL_URL, "rows": rows_out}
