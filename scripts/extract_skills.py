#!/usr/bin/env python3
"""
atwiki の「スキル一覧表」から主要なシステム系スキル（EXAM/HADES/各種バイオセンサー/NT-D）を半自動抽出し、
構造化JSONを生成するたたき台。

想定入出力（例）
- 取得＆解析:  uv run python -m scripts.extract_skills all --out cache/skills.json --ttl 7d
- 解析のみ:    uv run python -m scripts.extract_skills parse --in cache/html/pages-179-*.html --out cache/skills.json

注意
- HTML構造や文言の変更に弱い暫定実装です。対象スキルの bullet 主要数値を優先抽出します。
- 付与スキル/無敵/よろけ軽減/免疫などの非数値効果は tags/grants に一部格納します（網羅は今後）。
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag

from scripts.cache_http import CacheHTTP, CacheConfig
from scripts.scrape_msdata import parse_ttl  # 軽量ユーティリティを流用
from scripts.label_utils import clean_text


SKILL_URL = "https://w.atwiki.jp/battle-operation2/pages/179.html"

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


def get_client(timeout: float = 30.0) -> httpx.Client:
    headers = {"User-Agent": "msdata-skills/0.1 (+https://github.com/; contact=local)"}
    return httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)


# ===============
# パーサ補助
# ===============


def _norm(s: str) -> str:
    return clean_text(
        s.replace("\u3000", " ")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("％", "%")
        .replace("：", ":")
        .replace("，", ",")
        .replace("（", "(")
        .replace("）", ")")
    )


def _to_int_first(text: str) -> Optional[int]:
    m = re.search(r"-?\d+", text)
    return int(m.group(0)) if m else None


def _percent_to_factor(text: str, sign: int = -1) -> Optional[float]:
    # sign: -1 for reductions like "-20%" -> 0.8; +1 reserved for increases if needed
    m = re.search(r"(\d+)%", text)
    if not m:
        return None
    p = int(m.group(1))
    p = p * sign
    return round(1.0 + (p / 100.0), 6)


def _extract_activation(desc: str) -> Dict[str, Any]:
    t = _norm(desc)
    act: Dict[str, Any] = {}
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


def _extract_duration(text: str) -> Optional[int]:
    t = _norm(text)
    if "効果時間は無し" in t or "効果時間は、無し" in t or "効果時間は無し" in t:
        return None
    m = re.search(r"効果時間[は、: ]*([0-9]+)秒", t)
    if m:
        return int(m.group(1))
    # 別表現（例: ※効果時間は 75秒）
    m = re.search(r"([0-9]+)秒", t)
    if m and ("効果" in t or "時間" in t):
        return int(m.group(1))
    return None


def _parse_grants(line: str) -> Optional[Dict[str, Any]]:
    t = _norm(line)
    # 例: 緊急回避制御 Lv2 が付与 / Lv3 が付与
    m = re.search(r"([A-Za-z0-9ぁ-んァ-ン一-龥・\-\[\]（）\(\)]+?)\s*Lv\s*(\d+)が付与", t)
    if m:
        return {"skill": m.group(1).strip(), "level": int(m.group(2))}
    return None


def _effects_from_lines(lines: List[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    effects: Dict[str, Any] = {}
    aux: Dict[str, Any] = {}
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


def _split_lines(text: str) -> List[str]:
    t = _norm(text.replace("\r", "\n").replace("<br>", "\n").replace("<br/>", "\n"))
    # 「・」や改行でおおまかに分割
    parts: List[str] = []
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


def extract_skills_from_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    skills: Dict[str, Dict[str, Any]] = {}

    cur_skill: Optional[str] = None
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

        act = _extract_activation(desc_txt + "\n" + BeautifulSoup(details_txt, "lxml").get_text(" "))
        duration = _extract_duration(BeautifulSoup(details_txt, "lxml").get_text(" ")) or _extract_duration(desc_txt)

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

        skills.setdefault(cur_skill, {"name": cur_skill, "levels": []})["levels"].append(rec)

    # 後処理: NT-D 系の派生（覚醒）を phase として紐付け（簡易）
    out_skills: List[Dict[str, Any]] = []
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
    # レベル配列のノイズ除去（内容が全て None の行を除外）
    for v in skills.values():
        filtered: List[Dict[str, Any]] = []
        for lv in v.get("levels", []):
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
                filtered.append(lv)
        v["levels"] = filtered

    # 並べ替え（名前昇順）
    for k in sorted(skills.keys()):
        out_skills.append(skills[k])

    owners = extract_skill_owners_from_html(soup)
    return {"source": SKILL_URL, "skills": out_skills, "skill_owners": owners}


_RE_ANCHOR = re.compile(r"^(能力UP「[^」]+」)\s*LV(\d+)$")


def extract_skill_owners_from_html(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """スキル逆引きテーブルから所持機体を収集（対象: 能力UP系）。

    形式例（th 内の <a id="能力UP「EXAM」LV1">...）を起点に、次のスキル見出しが来るまでの行の td 内リンクを収集。
    戻り: [{name, level, owners: [ms_name, ...]}]
    """
    results: List[Dict[str, Any]] = []
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
        if not any(name.startswith(x.replace("】", "").replace("】", "")) for x in CORE_SKILLS):
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
        owners: List[str] = []
        # 次のアンカー行（または表終端）まで前進
        stop_tr = anchors[idx + 1][2] if idx + 1 < len(anchors) else None
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


# ===============
# CLI
# ===============


def cmd_fetch(args: argparse.Namespace) -> int:
    ttl_sec = parse_ttl(args.ttl)
    client = get_client()
    cache = CacheHTTP(client, CacheConfig(ttl_seconds=ttl_sec, no_network=args.no_network, force=args.force))
    html, meta = cache.get(args.url)
    print(json.dumps({"saved": True, "meta": meta}, ensure_ascii=False))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    html_path = Path(args.input)
    if not html_path.exists():
        raise SystemExit(f"HTML not found: {html_path}")
    html = html_path.read_text(encoding="utf-8")
    data = extract_skills_from_html(html)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"skills: wrote -> {out}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    ttl_sec = parse_ttl(args.ttl)
    client = get_client()
    cache = CacheHTTP(client, CacheConfig(ttl_seconds=ttl_sec, no_network=args.no_network, force=args.force))
    html, meta = cache.get(args.url)
    data = extract_skills_from_html(html)
    data["fetched_at"] = meta.get("fetched_at")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"skills: wrote -> {out}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Extract core system skills from atwiki skills list (prototype)")
    sub = ap.add_subparsers(dest="cmd")

    p_fetch = sub.add_parser("fetch", help="Fetch HTML (cache-aware)")
    p_fetch.add_argument("--url", default=SKILL_URL)
    p_fetch.add_argument("--ttl", default="7d")
    p_fetch.add_argument("--no-network", action="store_true")
    p_fetch.add_argument("--force", action="store_true")
    p_fetch.set_defaults(func=cmd_fetch)

    p_parse = sub.add_parser("parse", help="Parse HTML file into skills JSON")
    p_parse.add_argument("--in", dest="input", required=True, help="Path to cached HTML")
    p_parse.add_argument("--out", dest="out", default="cache/skills.json")
    p_parse.set_defaults(func=cmd_parse)

    p_all = sub.add_parser("all", help="Fetch+Parse in one go")
    p_all.add_argument("--url", default=SKILL_URL)
    p_all.add_argument("--ttl", default="7d")
    p_all.add_argument("--no-network", action="store_true")
    p_all.add_argument("--force", action="store_true")
    p_all.add_argument("--out", dest="out", default="cache/skills.json")
    p_all.set_defaults(func=cmd_all)

    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
