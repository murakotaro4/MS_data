"""msData 更新通知メール本文を生成する。"""

from __future__ import annotations

import argparse
from pathlib import Path


SUMMARY_KEYS = (
    "レコード数",
    "protected_rollback",
    "numeric_decrease",
    "mixed_level_change",
    "protected_by_override",
    "upstream_current",
    "source_changed",
    "review_due",
    "remove_due",
)

DETAIL_SECTION_HEADINGS = (
    "追加レコード一覧",
    "削除レコード一覧",
    "変更レコード一覧",
)


def _read(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _extract_summary_lines(path: Path | None, *, limit: int = 8) -> list[str]:
    text = _read(path)
    if not text:
        return []

    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        if any(body.startswith(key) for key in SUMMARY_KEYS):
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _section_lines(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    target = f"## {heading}"
    for index, line in enumerate(lines):
        if line.strip() == target:
            start = index
            break
    if start is None:
        return []

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index].strip()
        if line.startswith("## "):
            end = index
            break
    return lines[start:end]


def _section_count(lines: list[str]) -> int | None:
    for raw in lines:
        line = raw.strip()
        if not line.startswith("- 件数:"):
            continue
        value = line.split(":", 1)[1].strip()
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _trim_blank_edges(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _extract_diff_detail_lines(path: Path | None, *, limit: int = 160) -> list[str]:
    text = _read(path)
    if not text:
        return []

    detail_lines: list[str] = []
    truncated = False
    for heading in DETAIL_SECTION_HEADINGS:
        section = _trim_blank_edges(_section_lines(text, heading))
        if not section:
            continue
        count = _section_count(section)
        if count == 0:
            continue
        if detail_lines:
            detail_lines.append("")
        for line in section:
            if len(detail_lines) >= limit:
                truncated = True
                break
            detail_lines.append(line)
        if truncated:
            break

    if truncated:
        detail_lines.extend(
            [
                "",
                f"（変更内容が多いため先頭 {limit} 行のみ表示しています。"
                "全文は添付/Release の差分レポートを確認してください。）",
            ]
        )
    return detail_lines


def _bool_text(value: str) -> str:
    return "true" if value.lower() == "true" else "false"


def _optional_bullets(args: argparse.Namespace) -> list[str]:
    lines: list[str] = []
    if args.candidate_count:
        lines.append(f"- candidate_count: {args.candidate_count}")
    if args.fast_path:
        lines.append(f"- fast_path: {_bool_text(args.fast_path)}")
    if args.age_coverage:
        lines.append(f"- age_coverage: {args.age_coverage}")
    if args.fallback_reason:
        lines.append(f"- fallback_reason: {args.fallback_reason}")
    if args.run_id:
        lines.append(f"- run_id: {args.run_id}")
    if args.source_run_id:
        lines.append(f"- source_run_id: {args.source_run_id}")
    if args.release_url:
        lines.append(f"- raw snapshot release: {args.release_url}")
    return lines


def build_body(args: argparse.Namespace) -> str:
    changed = _bool_text(args.changed)
    lines = [
        "msData 定期更新を実行しました。",
        "",
        f"- 実行日: {args.report_date}",
        f"- 結果: {args.result}",
        f"- msData.json変更: {changed}",
    ]
    lines.extend(_optional_bullets(args))

    diff_lines = _extract_summary_lines(args.diff_path)
    if diff_lines:
        lines.extend(["", "## 差分サマリ", ""])
        lines.extend(diff_lines)

    detail_lines = _extract_diff_detail_lines(args.diff_path)
    if detail_lines:
        lines.extend(["", "## 変更内容", ""])
        lines.extend(detail_lines)

    rollback_lines = _extract_summary_lines(args.rollback_guard_path)
    if rollback_lines:
        lines.extend(["", "## 巻き戻りガード", ""])
        lines.extend(rollback_lines)

    override_lines = _extract_summary_lines(args.official_overrides_audit_path)
    if override_lines:
        lines.extend(["", "## official_overrides監査", ""])
        lines.extend(override_lines)

    if args.detail_url:
        lines.extend(["", f"詳細: {args.detail_url}"])

    return "\n".join(lines).rstrip() + "\n"


def _path_arg(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--changed", required=True)
    parser.add_argument("--candidate-count", default="")
    parser.add_argument("--fast-path", default="")
    parser.add_argument("--age-coverage", default="")
    parser.add_argument("--fallback-reason", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--release-url", default="")
    parser.add_argument("--detail-url", default="")
    parser.add_argument("--diff-path", type=_path_arg, default=None)
    parser.add_argument("--rollback-guard-path", type=_path_arg, default=None)
    parser.add_argument("--official-overrides-audit-path", type=_path_arg, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_body(args), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
