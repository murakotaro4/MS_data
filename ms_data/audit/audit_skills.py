#!/usr/bin/env python3
"""
skill_owners.json と msData.json を突合し、監査レポートを出力。

出力: reports/skill_owners_audit_YYYYMMDD.md

チェック項目（初期版）
- unknown_series: owners にあるが msData にシリーズが見つからない
- coverage: msData レコードのうち、何件がスキル付与対象になるか（シリーズ一致ベース）
- per-skill 所持シリーズ数（概要統計）
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
from pathlib import Path
from typing import Any

from ms_data.core.ms_names import ms_name_to_series_level


def ms_name_to_series(ms_name: str) -> str:
    return ms_name_to_series_level(ms_name)[0]


def load_msdata(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit skill_owners against msData.json")
    ap.add_argument("--owners", default="data/skill_owners.json")
    ap.add_argument("--msdata", default="msData.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    owners = json.loads(Path(args.owners).read_text(encoding="utf-8"))
    msdata = load_msdata(Path(args.msdata))

    series_in_ms: set[str] = set()
    for rec in msdata:
        name = rec.get("MS名") or ""
        if not name:
            continue
        series_in_ms.add(ms_name_to_series(name))

    # unknown series
    unknown: list[str] = []
    owners_map: dict[str, list[dict[str, Any]]] = {}
    for o in owners.get("owners", []):
        series = o.get("series") or ""
        if not series:
            continue
        owners_map[series] = o.get("base", [])
        if series not in series_in_ms:
            unknown.append(series)

    # coverage: 何件の msData レコードにスキルが付与されるか
    covered = 0
    total = 0
    for rec in msdata:
        name = rec.get("MS名") or ""
        if not name:
            continue
        total += 1
        series = ms_name_to_series(name)
        if series in owners_map and owners_map[series]:
            covered += 1

    # per-skill 所持シリーズ数
    per_skill = collections.Counter()
    for series, skills in owners_map.items():
        for s in skills:
            sid = s.get("id") or ""
            if sid:
                per_skill[sid] += 1

    # 出力
    today = dt.datetime.now().strftime("%Y%m%d")
    out = args.out or f"reports/skill_owners_audit_{today}.md"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# skill owners audit ({today})\n\n")
        f.write(f"- msData records: {total}\n")
        f.write(f"- covered (series match): {covered}\n")
        f.write(f"- unknown series (owners not in msData): {len(unknown)}\n\n")
        if unknown:
            f.write("## Unknown series\n")
            for s in sorted(set(unknown)):
                f.write(f"- {s}\n")
            f.write("\n")
        f.write("## Per-skill owners (series count)\n")
        for sid, cnt in per_skill.most_common():
            f.write(f"- {sid}: {cnt}\n")
        f.write("\n")
    print(f"audit: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
