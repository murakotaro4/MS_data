#!/usr/bin/env python3
"""
labels_raw.jsonl を集計して、行見出し（項目名）の表記揺れを可視化するツール。

出力: Markdown レポート（頻度表、未対応ラベル一覧、提案メモ欄）
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ms_data.core.labels import FIELD_MAP, clean_text

# 監査から除外する normalized ラベル（データ項目ではないもの）
EXCLUDE_LABELS = {"汎用", "強襲", "支援"}


def load_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


@dataclass
class Stats:
    pages: int
    raw_counts: Counter
    norm_counts: Counter
    unknown_norm: Counter


def analyze(records: Iterable[dict]) -> Stats:
    raw = Counter()
    norm = Counter()
    unknown = Counter()
    pages = 0
    for rec in records:
        pages += 1
        for s in rec.get("raw_labels", []) or []:
            raw[clean_text(str(s))] += 1
        for s in rec.get("normalized_labels", []) or []:
            ss = clean_text(str(s))
            if ss in EXCLUDE_LABELS:
                # 集計から除外
                continue
            norm[ss] += 1
            if ss not in FIELD_MAP:
                unknown[ss] += 1
    return Stats(pages=pages, raw_counts=raw, norm_counts=norm, unknown_norm=unknown)


def write_report(stats: Stats, out: Path) -> None:
    total_norm = sum(stats.norm_counts.values())
    known = total_norm - sum(stats.unknown_norm.values())
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write("# ラベル揺らぎ監査レポート\n\n")
        f.write(f"- ページ数: {stats.pages}\n")
        f.write(f"- ユニーク(raw): {len(stats.raw_counts)}\n")
        f.write(f"- ユニーク(normalized): {len(stats.norm_counts)}\n")
        f.write(f"- normalized 総出現: {total_norm}\n")
        f.write(f"- 既知: {known} / 未対応: {sum(stats.unknown_norm.values())}\n\n")

        f.write("## 頻度（normalized）上位\n")
        f.write("ラベル | 出現数 | 状態\n\n")
        for label, cnt in stats.norm_counts.most_common(100):
            status = "OK" if label in FIELD_MAP else "UNKNOWN"
            f.write(f"- {label} | {cnt} | {status}\n")

        if stats.unknown_norm:
            f.write("\n## 未対応ラベル一覧\n")
            for label, cnt in stats.unknown_norm.most_common():
                f.write(f"- {label} ({cnt})\n")

        f.write("\n## 提案メモ\n")
        f.write("- 未対応ラベルのうち、正規キーに相当するものを FIELD_MAP に追加\n")
        f.write("- 出力JSONのキー揺れは KEY_ALIASES で吸収（別モジュール）\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="input", default="cache/labels_raw.jsonl")
    ap.add_argument("--out", dest="out", default="reports/label_audit_latest.md")
    args = ap.parse_args(argv)

    stats = analyze(load_jsonl(Path(args.input)))
    write_report(stats, Path(args.out))
    print(
        "report: pages="
        f"{stats.pages}, unique_norm={len(stats.norm_counts)}, "
        f"unknown={len(stats.unknown_norm)} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
