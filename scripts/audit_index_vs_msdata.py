#!/usr/bin/env python3
"""
index.json（atwiki一覧）と msData.json（既存データ）を突き合わせ、
名称の食い違い・表記差・属性/コスト不一致などを監査し、Markdownレポートを出力。

使い方（例）
- uv run python -m scripts.audit_index_vs_msdata --index cache/index.json --ms msData.json --out reports/index_ms_audit.md

出力内容（Markdown）
- 件数サマリ
- indexのみ / msDataのみ（基底名）
- msDataのみ（正規化で一致）: 変換ポイント（[]→［］/II→Ⅱ/Z→Ζ/Ｖ→V 等）を記載
- 属性/コストの不一致一覧
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_base_levels(ms_records: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    bases: Dict[str, List[int]] = defaultdict(list)
    for r in ms_records:
        name = r.get("MS名")
        if not isinstance(name, str):
            continue
        m = re.match(r"^(.*)_LV(\d+)$", name)
        if not m:
            continue
        base = m.group(1)
        lv = int(m.group(2))
        bases[base].append(lv)
    return bases


def normalize_towards_index(name: str) -> Tuple[str, List[str]]:
    """msData名を index 側の表記に近づける軽正規化を行い、適用ルールを返す。

    ルール:
    - 半角[] → 全角［］（atwiki index 準拠）
    - ローマ数字 II/III → Ⅱ/Ⅲ
    - 文脈限定Z → ギリシャ文字 Ζ（Zガンダム/ZZガンダム/同3号機…）
    - 全角Ｖ → 半角V（例: ゲルググ・Ｖ・キュアノス）
    """
    rules: List[str] = []
    out = name

    # 1) [] → ［］
    if ("[" in out) or ("]" in out):
        out2 = out.replace("[", "［").replace("]", "］")
        if out2 != out:
            rules.append("[]→［］")
            out = out2

    # 2) II/III → Ⅱ/Ⅲ（順序注意）
    out2 = out.replace("III", "Ⅲ").replace("II", "Ⅱ")
    if out2 != out:
        # どちらが変わったか一括表示
        if "III" in out:
            rules.append("III→Ⅲ")
        if "II" in out:
            rules.append("II→Ⅱ")
        out = out2

    # 3) 文脈Z → Ζ（ギリシャ）
    def z_to_greek(s: str) -> str:
        s = re.sub(r"ZZ(?=ガンダム)", "ΖΖ", s)
        s = re.sub(r"Z(?=ガンダム)", "Ζ", s)
        s = re.sub(r"Z(?=ガンダム3号機)", "Ζ", s)
        return s

    out2 = z_to_greek(out)
    if out2 != out:
        rules.append("Z/ZZ→Ζ/ΖΖ（文脈）")
        out = out2

    # 4) Ｖ → V
    if "Ｖ" in out:
        out2 = out.replace("Ｖ", "V")
        if out2 != out:
            rules.append("Ｖ→V")
            out = out2

    return out, rules


def audit(index_path: Path, ms_path: Path) -> Dict[str, Any]:
    idx_list = load_json(index_path)
    ms_list = load_json(ms_path)
    if not isinstance(idx_list, list) or not isinstance(ms_list, list):
        raise SystemExit("ERROR: inputs must be arrays")

    idx_by_name: Dict[str, Dict[str, Any]] = {e["name"]: e for e in idx_list if isinstance(e, dict) and e.get("name")}
    idx_names = set(idx_by_name.keys())

    ms_bases_levels = extract_base_levels([r for r in ms_list if isinstance(r, dict)])
    ms_bases = set(ms_bases_levels.keys())

    # presence diffs
    index_only = sorted(idx_names - ms_bases)
    ms_only = sorted(ms_bases - idx_names)

    # attr/cost mismatches for names present in both (compare vs LV最小のレコードで代表)
    rep_by_base: Dict[str, Dict[str, Any]] = {}
    for base, levels in ms_bases_levels.items():
        min_lv = min(levels) if levels else None
        if min_lv is None:
            continue
        # pick representative record (first matching LV)
        for r in ms_list:
            n = r.get("MS名")
            if n == f"{base}_LV{min_lv}":
                rep_by_base[base] = r
                break

    attr_mismatches: List[Tuple[str, str, str]] = []
    cost_mismatches: List[Tuple[str, int, int]] = []
    for name in sorted(idx_names & ms_bases):
        idx_attr = idx_by_name[name].get("属性")
        idx_cost = idx_by_name[name].get("cost")
        rep = rep_by_base.get(name) or {}
        ms_attr = rep.get("属性")
        ms_cost = rep.get("コスト")
        if (idx_attr is not None) and (ms_attr is not None) and (idx_attr != ms_attr):
            attr_mismatches.append((name, str(idx_attr), str(ms_attr)))
        if isinstance(idx_cost, int) and isinstance(ms_cost, int) and (idx_cost != ms_cost):
            cost_mismatches.append((name, int(idx_cost), int(ms_cost)))

    # ms-only names: try normalization to see if they actually match index after normalization
    normalized_matches: List[Dict[str, Any]] = []
    normalized_unmatched: List[Dict[str, Any]] = []
    for base in ms_only:
        norm, rules = normalize_towards_index(base)
        info = {
            "ms_name": base,
            "norm_name": norm,
            "rules": rules,
            "levels": sorted(set(ms_bases_levels.get(base, []))),
        }
        if norm in idx_names:
            normalized_matches.append(info)
        else:
            normalized_unmatched.append(info)

    return {
        "index_total": len(idx_names),
        "ms_base_total": len(ms_bases),
        "index_only": index_only,
        "ms_only": ms_only,
        "attr_mismatches": attr_mismatches,
        "cost_mismatches": cost_mismatches,
        "normalized_matches": normalized_matches,
        "normalized_unmatched": normalized_unmatched,
    }


def render_markdown(result: Dict[str, Any]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append(f"# index vs msData 監査レポート")
    lines.append("")
    lines.append(f"generated at: {now}")
    lines.append("")
    lines.append("## サマリ")
    lines.append(f"- index（一覧）: {result['index_total']} 件")
    lines.append(f"- msData（基底名）: {result['ms_base_total']} 件")
    lines.append(f"- indexのみ: {len(result['index_only'])} 件")
    lines.append(f"- msDataのみ: {len(result['ms_only'])} 件")
    lines.append(f"- 属性不一致: {len(result['attr_mismatches'])} 件")
    lines.append(f"- コスト不一致: {len(result['cost_mismatches'])} 件")
    lines.append("")

    if result["index_only"]:
        lines.append("## indexのみに存在（msData未収載）")
        for name in result["index_only"]:
            lines.append(f"- {name}")
        lines.append("")

    if result["normalized_matches"]:
        lines.append("## msDataのみ（正規化すればindexと一致）")
        lines.append("表記差のポイントを括弧内に記載しています。")
        for row in result["normalized_matches"]:
            lv = row["levels"]
            rng = f"LV{lv[0]}-{lv[-1]}" if lv and len(lv) > 1 else (f"LV{lv[0]}" if lv else "-")
            rules = "/".join(row["rules"]) if row["rules"] else "(差分特定済み)"
            lines.append(f"- {row['ms_name']} → {row['norm_name']} | {rng} | {rules}")
        lines.append("")

    if result["normalized_unmatched"]:
        lines.append("## msDataのみ（正規化してもindexに不在）")
        lines.append("index抽出漏れ等の可能性があります。")
        for row in result["normalized_unmatched"]:
            lv = row["levels"]
            rng = f"LV{lv[0]}-{lv[-1]}" if lv and len(lv) > 1 else (f"LV{lv[0]}" if lv else "-")
            rules = "/".join(row["rules"]) if row["rules"] else "(差分特定済み)"
            lines.append(f"- {row['ms_name']}（norm: {row['norm_name']}） | {rng} | {rules}")
        lines.append("")

    if result["attr_mismatches"] or result["cost_mismatches"]:
        lines.append("## 属性/コストの不一致")
        for name, i_attr, m_attr in result["attr_mismatches"]:
            lines.append(f"- 属性: {name}: index={i_attr} / msData={m_attr}")
        for name, i_cost, m_cost in result["cost_mismatches"]:
            lines.append(f"- コスト: {name}: index={i_cost} / msData={m_cost}")
        lines.append("")

    if not (result["index_only"] or result["normalized_matches"] or result["normalized_unmatched"] or result["attr_mismatches"] or result["cost_mismatches"]):
        lines.append("差分は検出されませんでした。")

    return "\n".join(lines) + "\n"


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", type=Path, default=Path("cache/index.json"))
    ap.add_argument("--ms", type=Path, default=Path("msData.json"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    res = audit(args.index, args.ms)
    out_path = args.out
    if out_path is None:
        out_path = Path("reports") / f"index_ms_audit_{dt.datetime.now().strftime('%Y%m%d')}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_text = render_markdown(res)
    out_path.write_text(out_text, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

