#!/usr/bin/env python3
"""変更レコードの取得元（atwiki HTML）抜粋レポートを生成する。

atwiki は Cloudflare により外部エージェント（Codex 等）からの直接閲覧ができない
ため、Actions が取得した ``cache/html`` から変更項目の該当行を抜き出し、
レビュー時に差分と取得元を照合できるようにする。

例:
  uv run python -m ms_data.reporting.build_source_excerpt \\
    --old msData.before.json --new msData.json \\
    --out reports/2026/10/source_excerpt_20261020.md \\
    --pr-section-out "$RUNNER_TEMP/source_excerpt_pr.md"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ms_data.core import json_io, paths
from ms_data.core.labels import clean_text
from ms_data.core.ms_names import MS_NAME_WITH_LEVEL
from ms_data.gh.outputs import append_step_summary, write_github_output
from ms_data.net.cache_http import url_to_slug
from ms_data.reporting.msdata_diff_model import (
    get_changed_records_detail,
    index_by_name,
    ms_level_sort_key,
)
from ms_data.reporting.rendering import append_table
from ms_data.reporting.report_msdata_diff import format_field_value, format_value
from ms_data.scraping.detail_page import _TEXT_FIELDS, extract_source_rows
from ms_data.scraping.text_values import to_int

REPORT_TITLE = "# 取得元抜粋"
EXPLANATION = (
    "atwiki は Cloudflare により外部エージェントからの直接閲覧ができないため、"
    "Actions が取得した HTML（`cache/html`）から変更項目の該当行を抜粋しています。"
    "レビュー時の取得元照合はこの抜粋を使ってください。"
    "`不一致` は公式調整オーバーライド・LV単位保留・前LV補完などの後処理が"
    "入った可能性を示し、直ちに誤りを意味しません。"
)
STATUS_MATCH = "一致"
STATUS_MISMATCH = "不一致"
STATUS_NO_ROW = "表に行なし"
STATUS_NO_HTML = "HTMLなし"
STATUS_NO_URL = "wiki_urlなし"
STATUS_REMOVED = "-"
EXCERPT_HEADERS = [
    "MS名",
    "LV",
    "項目",
    "変更前",
    "変更後",
    "取得元（該当LV）",
    "照合",
    "取得元の行（全LV）",
]
PAGE_HEADERS = ["機体", "wiki_url", "取得時刻", "HTTP", "content_sha256"]
DEFAULT_MAX_PR_ROWS = 20
_CELL_MAX_LEN = 80
_ROW_MAX_LEN = 200


@dataclass
class SourcePage:
    """1 ページ分の取得元情報（HTML キャッシュとメタ情報）。"""

    url: str
    ms_name: str = ""
    html_found: bool = False
    fetched_at: str = ""
    http_status: str = ""
    content_sha256: str = ""
    levels: list[int] = field(default_factory=list)
    rows: dict[str, tuple[str, list[str | None]]] = field(default_factory=dict)

    def cell(self, key: str, level: int) -> str | None:
        row = self.rows.get(key)
        if row is None or level not in self.levels:
            return None
        return row[1][self.levels.index(level)]

    def row_text(self, key: str) -> str:
        row = self.rows.get(key)
        if row is None:
            return ""
        label, cells = row
        parts = [
            f"LV{lv}={value}"
            for lv, value in zip(self.levels, cells, strict=False)
            if value
        ]
        return f"{label}: " + " / ".join(parts)


@dataclass
class ExcerptRow:
    name: str
    level: str
    field_name: str
    old_text: str
    new_text: str
    source_text: str
    status: str
    row_text: str

    def cells(self) -> list[str]:
        return [
            format_value(self.name),
            self.level,
            format_value(self.field_name),
            self.old_text,
            self.new_text,
            format_value(self.source_text, _CELL_MAX_LEN),
            self.status,
            format_value(self.row_text, _ROW_MAX_LEN),
        ]


def load_source_page(url: str, html_dir: Path) -> SourcePage:
    """URL に対応する HTML キャッシュとメタ情報を読み込み、表の行を抽出する。"""
    page = SourcePage(url=url)
    slug = url_to_slug(url)
    html_path = html_dir / f"{slug}.html"
    meta = json_io.load_json_or_default(html_dir / f"{slug}.meta.json", {})
    if isinstance(meta, dict):
        page.fetched_at = str(meta.get("fetched_at") or "")
        status = meta.get("http_status")
        page.http_status = "" if status is None else str(status)
        page.content_sha256 = str(meta.get("content_sha256") or "")[:12]
    if not html_path.is_file():
        return page
    page.html_found = True
    page.levels, page.rows = extract_source_rows(html_path.read_text(encoding="utf-8"))
    return page


def _matches(field_name: str, source: str | None, value: Any) -> bool:
    if source is None:
        return False
    if field_name in _TEXT_FIELDS:
        return clean_text(source) == clean_text(str(value))
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return to_int(source) == value


def _excerpt_row(
    name: str,
    op: str,
    field_name: str,
    old_val: Any,
    new_val: Any,
    page: SourcePage | None,
) -> ExcerptRow:
    match = MS_NAME_WITH_LEVEL.match(name)
    level = int(match.group("level")) if match else None
    old_text = "" if op == "added" else format_field_value(field_name, old_val)
    new_text = "" if op == "removed" else format_field_value(field_name, new_val)
    source_text = ""
    row_text = ""
    if page is None:
        status = STATUS_NO_URL
    elif not page.html_found:
        status = STATUS_NO_HTML
    elif field_name not in page.rows:
        status = STATUS_NO_ROW
    else:
        row_text = page.row_text(field_name)
        source = page.cell(field_name, level) if level is not None else None
        source_text = "" if source is None else source
        if op == "removed":
            status = STATUS_REMOVED
        else:
            status = (
                STATUS_MATCH
                if _matches(field_name, source, new_val)
                else STATUS_MISMATCH
            )
    return ExcerptRow(
        name=name,
        level=f"LV{level}" if level is not None else "LV不明",
        field_name=field_name,
        old_text=old_text,
        new_text=new_text,
        source_text=source_text,
        status=status,
        row_text=row_text,
    )


def collect_excerpt(
    old_list: list[Any],
    new_list: list[Any],
    html_dir: Path,
    *,
    page_loader: Callable[[str, Path], SourcePage] = load_source_page,
) -> tuple[list[ExcerptRow], dict[str, SourcePage]]:
    """追加・変更レコードの項目ごとに取得元抜粋を集める。"""
    old, _, _ = index_by_name(old_list)
    new, _, _ = index_by_name(new_list)
    changes: list[tuple[str, list[tuple[str, str, Any, Any]]]] = list(
        get_changed_records_detail(old, new)
    )
    for name in set(new) - set(old):
        changes.append(
            (name, [("added", k, None, v) for k, v in sorted(new[name].items())])
        )
    changes.sort(key=lambda item: ms_level_sort_key(item[0]))

    pages: dict[str, SourcePage] = {}
    rows: list[ExcerptRow] = []
    for name, record_changes in changes:
        record = new.get(name) or old.get(name) or {}
        url = record.get("wiki_url")
        page: SourcePage | None = None
        if isinstance(url, str) and url:
            if url not in pages:
                pages[url] = page_loader(url, html_dir)
                match = MS_NAME_WITH_LEVEL.match(name)
                pages[url].ms_name = match.group("base") if match else name
            page = pages[url]
        for op, field_name, old_val, new_val in record_changes:
            if field_name in {"MS名", "wiki_url"}:
                continue
            row = _excerpt_row(name, op, field_name, old_val, new_val, page)
            # 追加レコードは表に対応する行がある項目だけを載せる
            if op == "added" and name not in old and row.status == STATUS_NO_ROW:
                continue
            rows.append(row)
    return rows, pages


def _status_count(rows: list[ExcerptRow], status: str) -> int:
    return sum(1 for row in rows if row.status == status)


def _page_rows(pages: dict[str, SourcePage]) -> list[list[str]]:
    return [
        [
            format_value(page.ms_name),
            url,
            page.fetched_at or "未取得",
            page.http_status or "-",
            page.content_sha256 or ("HTMLなし" if not page.html_found else "-"),
        ]
        for url, page in pages.items()
    ]


def build_report_lines(
    rows: list[ExcerptRow], pages: dict[str, SourcePage], report_date: str
) -> list[str]:
    lines = [REPORT_TITLE, "", f"- report_date: {report_date}", "", EXPLANATION, ""]
    lines += [
        "## サマリ",
        "",
        f"- excerpt_rows: {len(rows)}",
        f"- source_pages: {len(pages)}",
        f"- match: {_status_count(rows, STATUS_MATCH)}",
        f"- mismatch: {_status_count(rows, STATUS_MISMATCH)}",
        f"- no_row: {_status_count(rows, STATUS_NO_ROW)}",
        f"- html_missing: {_status_count(rows, STATUS_NO_HTML)}",
        "",
        "## 取得元ページ",
        "",
    ]
    append_table(lines, PAGE_HEADERS, _page_rows(pages))
    lines += ["", "## 変更項目の抜粋", ""]
    append_table(lines, EXCERPT_HEADERS, [row.cells() for row in rows])
    lines.append("")
    return lines


def build_pr_section(
    rows: list[ExcerptRow], report_path: str, max_rows: int
) -> list[str]:
    """PR 本文に載せる抜粋（上限件数つき）。"""
    lines = [
        "### 取得元抜粋（atwiki は外部から直接閲覧できないため Actions 取得 HTML から抜粋）",
        "",
    ]
    if not rows:
        lines.append("変更項目なし")
        return lines
    shown = rows[:max_rows]
    append_table(lines, EXCERPT_HEADERS, [row.cells() for row in shown])
    lines.append("")
    if len(rows) > len(shown):
        lines.append(f"...（残り {len(rows) - len(shown)} 件は {report_path} を参照）")
    else:
        lines.append(f"全件: {report_path}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, default=paths.MSDATA_BEFORE)
    parser.add_argument("--new", type=Path, default=paths.MSDATA)
    parser.add_argument("--html-dir", type=Path, default=paths.HTML_CACHE_DIR)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pr-section-out", type=Path)
    parser.add_argument("--max-pr-rows", type=int, default=DEFAULT_MAX_PR_ROWS)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--step-summary", type=Path)
    args = parser.parse_args(argv)

    try:
        old_list = json_io.load_json(args.old)
        new_list = json_io.load_json(args.new)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"エラー: msData の読み込みに失敗しました: {exc}", file=sys.stderr)
        return 1
    if not isinstance(old_list, list) or not isinstance(new_list, list):
        print("エラー: msData は配列である必要があります", file=sys.stderr)
        return 1

    rows, pages = collect_excerpt(old_list, new_list, args.html_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(build_report_lines(rows, pages, args.report_date)),
        encoding="utf-8",
    )
    if args.pr_section_out is not None:
        args.pr_section_out.parent.mkdir(parents=True, exist_ok=True)
        args.pr_section_out.write_text(
            "\n".join(build_pr_section(rows, str(args.out), args.max_pr_rows)) + "\n",
            encoding="utf-8",
        )
    mismatch = _status_count(rows, STATUS_MISMATCH)
    html_missing = _status_count(rows, STATUS_NO_HTML)
    if args.github_output is not None:
        write_github_output(
            args.github_output,
            {
                "excerpt_rows": len(rows),
                "mismatch_count": mismatch,
                "html_missing_count": html_missing,
            },
        )
    append_step_summary(
        [
            "### 取得元抜粋",
            f"- excerpt_rows: {len(rows)}",
            f"- mismatch: {mismatch}",
            f"- html_missing: {html_missing}",
            f"- report: {args.out}",
        ],
        args.step_summary,
    )
    print(f"source excerpt: rows={len(rows)} mismatch={mismatch} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
