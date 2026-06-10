#!/usr/bin/env python3
from __future__ import annotations

"""
cache/owners_table.json（所持機体 逆引きの行データ）から、
「スキル名 / スキルLv / 所有機体シリーズ / 機体レベル」をフラットに展開して出力。

入力:
- cache/owners_table.json  … ms_data.scraping.extract_skills owners-table で生成
- msData.json              … 機体のレベル一覧を取得（シリーズ名→存在Lv）
- data/skills_policy.json  … include_exact でスキル名をホワイトリスト

出力:
- data/skill_owners_flat.json
  形式: { owners: [ {skill, skill_level, series, ms_level} ] }

注: owners_table 側はシリーズ名（例: イフリート改）。msData は `MS名=シリーズ名_LVn`。
    シリーズ→Lv の対応は msData から導出し、全Lvに展開する（将来、例外があれば個別に調整）。
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set

from ms_data.core.ms_names import ms_name_to_series_level


def load_series_levels(msdata_path: Path) -> Dict[str, Set[int]]:
    series_levels: Dict[str, Set[int]] = {}
    arr = json.loads(msdata_path.read_text(encoding="utf-8"))
    for rec in arr:
        ms = rec.get("MS名") or ""
        if not ms:
            continue
        series, lv = ms_name_to_series_level(ms)
        if lv is None:
            continue
        series_levels.setdefault(series, set()).add(lv)
    return series_levels


def normalize_series(name: str) -> str:
    # 半角括弧/角括弧を全角へ、空白統一
    t = name.strip()
    t = (
        t.replace("(", "（")
        .replace(")", "）")
        .replace("[", "［")
        .replace("]", "］")
    )
    # 連続空白を1つへ
    t = " ".join(t.split())
    return t


def normalize_series_levels(
    series_levels_raw: Dict[str, Set[int]]
) -> Dict[str, Set[int]]:
    series_levels: Dict[str, Set[int]] = {}
    for s, lvset in series_levels_raw.items():
        ns = normalize_series(s)
        series_levels.setdefault(ns, set()).update(lvset)
    return series_levels


def build_flat_owners(
    owners_table: Dict[str, Any],
    series_levels: Dict[str, Set[int]],
    include: Set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    owners_out: List[Dict[str, Any]] = []
    unknown_series: Dict[str, List[Dict[str, Any]]] = {}

    for row in owners_table.get("rows", []):
        skill = row.get("skill") or ""
        if include and skill not in include:
            continue
        skill_lv = int(row.get("level") or 0)
        for o in row.get("owners", []) or []:
            series = normalize_series((o.get("name") or "").strip())
            if not series:
                continue
            levels = series_levels.get(series)
            if not levels:
                unknown_series.setdefault(series, []).append({"skill": skill, "skill_level": skill_lv})
                continue
            for lv in sorted(levels):
                owners_out.append({
                    "skill": skill,
                    "skill_level": skill_lv,
                    "series": series,
                    "ms_level": lv,
                })
    return owners_out, unknown_series


def build_audit(
    unknown_series: Dict[str, List[Dict[str, Any]]], owners_out: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        "unknown_series_count": len(unknown_series),
        "unknown_series": [
            {"series": s, "examples": v[:5]} for s, v in sorted(unknown_series.items())
        ],
        "owners_count": len(owners_out),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build flat owners list (skill, series, ms_level)")
    ap.add_argument("--in", dest="input", default="cache/owners_table.json")
    ap.add_argument("--msdata", dest="msdata", default="msData.json")
    ap.add_argument("--policy", dest="policy", default="data/skills_policy.json")
    ap.add_argument("--out", dest="out", default="data/skill_owners_flat.json")
    ap.add_argument("--audit-out", dest="audit_out", default="reports/owners_flat_audit.json")
    args = ap.parse_args()

    owners_table = json.loads(Path(args.input).read_text(encoding="utf-8"))
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8")) if args.policy else {}
    include = set(policy.get("include_exact", []) or [])
    series_levels = normalize_series_levels(load_series_levels(Path(args.msdata)))
    owners_out, unknown_series = build_flat_owners(owners_table, series_levels, include)

    data = {"owners": owners_out}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit = build_audit(unknown_series, owners_out)
    Path(args.audit_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.audit_out).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"wrote: {args.out}\n audit: {args.audit_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
