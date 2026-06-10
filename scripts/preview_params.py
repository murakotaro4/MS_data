#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ms_data.core.ms_names import ms_name_to_series_level


def load_params(skills_params_path: Path) -> Dict[Tuple[str, int], Dict[str, Any]]:
    data = json.loads(skills_params_path.read_text(encoding="utf-8"))
    by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for s in data.get("skills", []):
        name = s.get("name")
        for lv in s.get("levels", []) or []:
            by_key[(name, int(lv.get("level") or 0))] = lv.get("effects") or {}
    return by_key


def load_owners_flat(path: Path) -> Dict[Tuple[str, int], List[Tuple[str, int]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    by_ms: Dict[Tuple[str, int], List[Tuple[str, int]]] = {}
    for o in data.get("owners", []) or []:
        series = o.get("series")
        ms_level = int(o.get("ms_level") or 0)
        skill = o.get("skill")
        skill_level = int(o.get("skill_level") or 0)
        by_ms.setdefault((series, ms_level), []).append((skill, skill_level))
    return by_ms


def aggregate_effects(effects_list: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    for eff in effects_list:
        for k, v in (eff or {}).items():
            op = v.get("op")
            if op == "add":
                agg.setdefault(k, {"op": "add", "value": 0})
                agg[k]["value"] += int(v.get("value") or 0)
            elif op == "mul":
                agg.setdefault(k, {"op": "mul", "factor": 1.0})
                agg[k]["factor"] *= float(v.get("factor") or 1.0)
    return agg


def build_preview(msdata_path: Path, owners_flat_path: Path, params_path: Path) -> List[Dict[str, Any]]:
    msdata = json.loads(msdata_path.read_text(encoding="utf-8"))
    owners = load_owners_flat(owners_flat_path)
    params = load_params(params_path)

    out: List[Dict[str, Any]] = []
    for rec in msdata:
        ms_name = rec.get("MS名") or ""
        series, lv = ms_name_to_series_level(ms_name)
        if lv is None:
            continue
        skills = owners.get((series, lv)) or []
        if not skills:
            continue
        effects_list: List[Dict[str, Any]] = []
        got: List[Dict[str, Any]] = []
        for sname, slevel in skills:
            eff = params.get((sname, slevel))
            if eff:
                effects_list.append(eff)
                got.append({"name": sname, "level": slevel, "effects": eff})
        if not effects_list:
            continue
        agg = aggregate_effects(effects_list)
        out.append(
            {
                "MS名": ms_name,
                "skills": [{"name": s[0], "level": s[1]} for s in skills],
                "applied_skills": got,
                "aggregated_effects": agg,
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Preview parameter-only skill application to msData")
    ap.add_argument("--msdata", default="msData.json")
    ap.add_argument("--owners", default="data/skill_owners_flat.json")
    ap.add_argument("--params", default="data/skills_params.json")
    ap.add_argument("--out", default="derived/ms_params_preview.json")
    args = ap.parse_args()

    out = build_preview(Path(args.msdata), Path(args.owners), Path(args.params))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote: {args.out} ({len(out)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

