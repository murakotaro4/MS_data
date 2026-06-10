#!/usr/bin/env python3
"""
skills_catalog.json / skill_owners.json の生成（たたき台）。

入力: cache/skills.json（ms_data.scraping.extract_skills の出力）
出力:
- data/skills_catalog.json
- data/skill_owners.json

設計メモ:
- カタログ: 日本語名 → 英小文字スネークのIDに正規化。
- 所持: atwikiの逆引き（シリーズ名）を series として採用し、各スキルの最大Lvを base に格納。
  レベル差異のルールは今後 'rules' で拡張予定。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def name_to_id(name: str) -> Optional[str]:
    m = name.strip()
    # 代表的なマッピング
    table = {
        "能力UP「EXAM」": "exam",
        "能力UP「HADES」": "hades",
        "能力UP「HADES-E」": "hades_e",
        "能力UP「ALICE」": "alice",
        "能力UP「ZEUS」": "zeus",
        "能力UP「バイオセンサー」": "biosensor",
        "能力UP「バイオセンサーP」": "biosensor_p",
        "能力UP「バイオセンサーM」": "biosensor_m",
        "能力UP「簡易バイオセンサー」": "biosensor_simple",
        "能力UP「NT-D」": "ntd",
        "能力UP「覚醒」": "awaken",
        "能力UP「覚醒：フェネクス」": "awaken_phenex",
        # 非能力UP（今は対象外だが将来拡張）
        "ラムアタック「バイオセンサー」": "ram_biosensor",
    }
    # 部分一致（念のため全角コロンの表記揺れ）
    if m in table:
        return table[m]
    for k, v in table.items():
        if m.startswith(k):
            return v
    return None


def build_catalog(data: Dict[str, Any]) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    for s in data.get("skills", []):
        name = s.get("name") or ""
        sid = name_to_id(name)
        if not sid:
            continue
        entry: Dict[str, Any] = {"id": sid, "name": name, "levels": []}
        # levels
        for lv in s.get("levels", []) or []:
            entry["levels"].append(
                {
                    "level": lv.get("level"),
                    "activation": lv.get("activation"),
                    "duration_sec": lv.get("duration_sec"),
                    "effects": lv.get("effects"),
                    "tags": lv.get("tags"),
                }
            )
        # phases（あれば）
        phases_out: List[Dict[str, Any]] = []
        for ph in s.get("phases", []) or []:
            ph_name = ph.get("name") or ""
            ph_id = name_to_id(ph_name) or ""
            phases_out.append(
                {
                    "id": ph_id or ph_name,
                    "name": ph_name,
                    "levels": [
                        {
                            "level": lv.get("level"),
                            "activation": lv.get("activation"),
                            "duration_sec": lv.get("duration_sec"),
                            "effects": lv.get("effects"),
                            "tags": lv.get("tags"),
                        }
                        for lv in ph.get("levels", []) or []
                    ],
                }
            )
        if phases_out:
            entry["phases"] = phases_out
        out.append(entry)
    return {"skills": out}


def build_owners(data: Dict[str, Any]) -> Dict[str, Any]:
    # skill_owners: [{name, level, owners: [series, ...]}]
    acc: Dict[str, Dict[str, int]] = {}
    for it in data.get("skill_owners", []) or []:
        sid = name_to_id(it.get("name", ""))
        if not sid:
            continue
        lvl = int(it.get("level") or 1)
        for series in it.get("owners", []) or []:
            series = series.strip()
            if not series:
                continue
            acc.setdefault(series, {})
            # 同一スキルのレベルが複数ある場合は最大値採用（暫定）
            acc[series][sid] = max(acc[series].get(sid, 0), lvl)

    owners: List[Dict[str, Any]] = []
    for series in sorted(acc.keys()):
        skills = [
            {"id": sid, "level": lvl}
            for sid, lvl in sorted(acc[series].items(), key=lambda x: (x[0], x[1]))
        ]
        owners.append({"series": series, "base": skills})
    return {"owners": owners}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build skills_catalog.json and skill_owners.json from cache/skills.json")
    ap.add_argument("--in", dest="input", default="cache/skills.json")
    ap.add_argument("--out-catalog", dest="out_catalog", default="data/skills_catalog.json")
    ap.add_argument("--out-owners", dest="out_owners", default="data/skill_owners.json")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"input not found: {src}")
    data = json.loads(src.read_text(encoding="utf-8"))

    catalog = build_catalog(data)
    owners = build_owners(data)

    Path(args.out_catalog).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_catalog).write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    Path(args.out_owners).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_owners).write_text(json.dumps(owners, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"wrote: {args.out_catalog}\nwrote: {args.out_owners}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

