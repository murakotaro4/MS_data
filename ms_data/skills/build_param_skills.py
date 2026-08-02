#!/usr/bin/env python3
from __future__ import annotations

"""
skills_table.json（表の行データ）から、パラメータ変化スキルのみを抽出して
data/skills_params.json を生成するたたき台。

対象パラメータ（ホワイトリスト）
- スピード, 高速移動
- 射撃補正, 格闘補正
- 各耐性（→ 耐ビーム補正/耐実弾補正/耐格闘補正 に展開）
- 旋回, 旋回性能（→ 旋回）
- スラスター消費（%→係数）, 被ダメージ（%→係数）

除外
- HP系（回復/継続ダメージ）や、よろけ/ロック/ステルス等の非ステータス項目

入力: cache/skills_table.json（ms_data.scraping.extract_skills の table 出力）
出力: data/skills_params.json
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any


TARGET_KEYS = [
    "スピード",
    "高速移動",
    "射撃補正",
    "格闘補正",
    "各耐性",
    "耐ビーム補正",
    "耐実弾補正",
    "耐格闘補正",
    "旋回",
    "旋回性能",
    "スラスター消費",
    "被ダメージ",
]


def _norm(s: str) -> str:
    return (
        s.replace("\u3000", " ")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("％", "%")
        .replace("：", ":")
        .replace("，", ",")
        .replace("（", "(")
        .replace("）", ")")
        .strip()
    )


def _to_int(text: str) -> int | None:
    m = re.search(r"([+\-]?\d+)", text)
    return int(m.group(1)) if m else None


def _to_percent(text: str) -> int | None:
    m = re.search(r"([+\-]?\d+)\s*%", text)
    return int(m.group(1)) if m else None


def _mul_factor(pct: int, kind: str) -> float:
    """%を係数へ。kindは '減' or '増'。"""
    if kind == "減":
        return round(1.0 - (abs(pct) / 100.0), 6)
    else:
        return round(1.0 + (abs(pct) / 100.0), 6)


def extract_param_effects(text: str) -> dict[str, Any]:
    s = _norm(text)
    effects: dict[str, Any] = {}

    # 行ごとに評価（ラベルの近傍の数値のみ採用）
    raw_lines = re.split(r"[\n\r]+", s)
    lines: list[str] = []
    for ln in raw_lines:
        ln = ln.strip()
        if not ln:
            continue
        if "・" in ln:
            for p in ln.split("・"):
                p = p.strip()
                if p:
                    lines.append(p)
        else:
            lines.append(ln)

    def add_or_update(key: str, op: str, value_key: str, value: Any) -> None:
        cur = effects.get(key)
        if not cur:
            effects[key] = {"op": op, value_key: value}
        else:
            # 同一キーが複数回出たら、より大きい絶対値（代表）を採用
            if value_key == "value":
                if abs(value) > abs(cur.get("value", 0)):
                    effects[key] = {"op": op, value_key: value}
            elif value_key == "factor":
                # 係数はより強い軽減（小さい）またはより強い増加（大きい）を優先
                f = float(value)
                g = float(cur.get("factor", 1.0))
                if f < g or f > g:
                    effects[key] = {"op": op, value_key: value}

    for ln in lines:
        # 基本加算（射撃/格闘/スピード/高速移動/旋回）
        for label, key in (
            ("射撃補正", "射撃補正"),
            ("格闘補正", "格闘補正"),
            ("スピード", "スピード"),
            ("高速移動", "高速移動"),
            ("旋回性能", "旋回"),
            ("旋回", "旋回"),
        ):
            if label in ln:
                m = re.search(r"%s\s*([+\-]?\d+)" % re.escape(label), ln)
                if m:
                    add_or_update(key, "add", "value", int(m.group(1)))

        # 各耐性 → 3耐性
        if "各耐性" in ln:
            m = re.search(r"各耐性\s*([+\-]?\d+)", ln)
            if m:
                v = int(m.group(1))
                for k in ("耐ビーム補正", "耐実弾補正", "耐格闘補正"):
                    add_or_update(k, "add", "value", v)

        # 個別耐性
        for k in ("耐ビーム補正", "耐実弾補正", "耐格闘補正"):
            if k in ln:
                m = re.search(r"%s\s*([+\-]?\d+)" % re.escape(k), ln)
                if m:
                    add_or_update(k, "add", "value", int(m.group(1)))

        # スラスター消費（%→係数）
        if "スラスター消費" in ln and "%" in ln:
            m = re.search(r"([+\-]?\d+)\s*%", ln)
            if m:
                pct = int(m.group(1))
                kind = "減"
                if "増" in ln or "+" in ln:
                    kind = "増"
                add_or_update("スラスター消費", "mul", "factor", _mul_factor(pct, kind))

        # 被ダメージ（%→係数）
        if "被ダメージ" in ln and "%" in ln:
            m = re.search(r"([+\-]?\d+)\s*%", ln)
            if m:
                pct = int(m.group(1))
                kind = "減"
                if "増" in ln or "+" in ln:
                    kind = "増"
                add_or_update("被ダメージ", "mul", "factor", _mul_factor(pct, kind))

    return effects


def score_level(effects: dict[str, Any]) -> int:
    return len(effects.keys())


def build_params(
    rows: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # skill -> level -> best effects
    best: dict[str, dict[int, dict[str, Any]]] = {}
    best_score: dict[str, dict[int, int]] = {}

    for r in rows:
        skill = r.get("skill") or ""
        level = int(r.get("level") or 0)
        # ポリシー適用（抽出側はスキル名を _norm 済みのため、ポリシー側も同じ規則で照合）
        if policy:
            inc = {_norm(x) for x in policy.get("include_exact", []) or []}
            exc = {_norm(x) for x in policy.get("exclude_exact", []) or []}
            if inc and _norm(skill) not in inc:
                # 監査: 除外だが数値含む？
                if audit is not None:
                    maybe = extract_param_effects(
                        (r.get("details_text") or "") + "\n" + (r.get("desc") or "")
                    )
                    if maybe:
                        audit.setdefault("excluded_param_rows", []).append(
                            {"skill": skill, "level": level, "effects": maybe}
                        )
                continue
            if exc and _norm(skill) in exc:
                if audit is not None:
                    maybe = extract_param_effects(
                        (r.get("details_text") or "") + "\n" + (r.get("desc") or "")
                    )
                    if maybe:
                        audit.setdefault("excluded_param_rows", []).append(
                            {"skill": skill, "level": level, "effects": maybe}
                        )
                continue
        details = r.get("details_text") or ""
        effects = extract_param_effects(details)
        if not effects:
            # desc 側にも数値があるケース（EXAM, HADES など）
            effects = extract_param_effects(r.get("desc") or "")
        if not effects:
            continue
        sc = score_level(effects)
        d1 = best_score.setdefault(skill, {})
        d2 = best.setdefault(skill, {})
        if sc > d1.get(level, 0):
            d1[level] = sc
            d2[level] = effects

    skills_out: list[dict[str, Any]] = []
    for skill in sorted(best.keys()):
        levels = []
        for lvl in sorted(best[skill].keys()):
            levels.append({"level": lvl, "effects": best[skill][lvl]})
        if levels:
            skills_out.append({"name": skill, "levels": levels})

    return {"skills": skills_out}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build parameter-change skills from table rows"
    )
    ap.add_argument("--in", dest="input", default="cache/skills_table.json")
    ap.add_argument("--out", dest="out", default="data/skills_params.json")
    ap.add_argument("--policy", dest="policy", default=None)
    ap.add_argument("--audit-out", dest="audit_out", default=None)
    args = ap.parse_args()

    rows = json.loads(Path(args.input).read_text(encoding="utf-8")).get("rows", [])
    pol = None
    if args.policy:
        pol = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    audit: dict[str, Any] = {}
    data = build_params(rows, pol, audit)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote: {args.out}")
    if args.audit_out:
        Path(args.audit_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.audit_out).write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"audit: {args.audit_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
