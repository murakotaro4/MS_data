import json
from pathlib import Path

from ms_data.net.cache_http import url_to_slug
from ms_data.reporting import build_source_excerpt as excerpt
from ms_data.scraping.detail_page import extract_source_rows
from ms_data.validation.validate_generated_reports import validate_reports

from helpers import make_ms_record, write_json

URL = "https://w.atwiki.jp/battle-operation2/pages/4397.html"
BASE = "ガルバルディβ高機動型［T仕様］"

HTML = """<html><head><title>ガルバルディβ高機動型［T仕様］ - wiki</title></head><body>
<div id="table_kyoushu"><table>
<thead><tr><th>強襲</th><th>LV1</th><th>LV2</th></tr></thead>
<tr><th>コスト</th><td>400</td><td>450</td></tr>
<tr><th>機体HP</th><td>19500</td><td>22000</td></tr>
<tr><th>カウンター</th><td colspan="2">蹴り飛ばし</td></tr>
</table></div>
<h3>パーツスロット</h3>
<table>
<tr><th>近距離</th><td>9</td><td>11</td></tr>
<tr><th>中距離</th><td>17</td><td>20</td></tr>
<tr><th>遠距離</th><td>13</td><td>15</td></tr>
</table>
</body></html>
"""


def _write_cache(html_dir: Path, *, html: str = HTML) -> None:
    html_dir.mkdir(parents=True, exist_ok=True)
    slug = url_to_slug(URL)
    (html_dir / f"{slug}.html").write_text(html, encoding="utf-8")
    write_json(
        html_dir / f"{slug}.meta.json",
        {
            "url": URL,
            "fetched_at": "2026-10-20T14:04:18+00:00",
            "http_status": 200,
            "content_sha256": "27ba35adaab1ffff",
        },
    )


def _record(level: int, **values: object) -> dict:
    rec = make_ms_record(f"{BASE}_LV{level}")
    rec["wiki_url"] = URL
    rec.update(values)
    return rec


def test_extract_source_rows_maps_status_and_parts_slot_rows():
    levels, rows = extract_source_rows(HTML)

    assert levels == [1, 2]
    assert rows["中スロット"] == ("中距離", ["17", "20"])
    assert rows["HP"] == ("機体HP", ["19500", "22000"])
    assert rows["カウンター"] == ("カウンター", ["蹴り飛ばし", "蹴り飛ばし"])


def test_extract_source_rows_without_table_returns_empty():
    assert extract_source_rows("<html><body><p>none</p></body></html>") == ([], {})


def test_changed_field_matches_source_cell(tmp_path: Path):
    html_dir = tmp_path / "html"
    _write_cache(html_dir)
    old = [_record(2, 中スロット=29, HP=22000)]
    new = [_record(2, 中スロット=20, HP=21000)]

    rows, pages = excerpt.collect_excerpt(old, new, html_dir)

    by_field = {row.field_name: row for row in rows}
    assert by_field["中スロット"].status == excerpt.STATUS_MATCH
    assert by_field["中スロット"].source_text == "20"
    assert by_field["中スロット"].row_text == "中距離: LV1=17 / LV2=20"
    assert by_field["HP"].status == excerpt.STATUS_MISMATCH
    assert pages[URL].fetched_at == "2026-10-20T14:04:18+00:00"
    assert pages[URL].ms_name == BASE


def test_text_field_and_missing_row_and_removed_field(tmp_path: Path):
    html_dir = tmp_path / "html"
    _write_cache(html_dir)
    old = [_record(1, カウンター="タックル", 格闘判定力="弱")]
    new_rec = _record(1, カウンター="蹴り飛ばし", 必要階級="少尉")
    new_rec.pop("格闘判定力", None)
    new = [new_rec]

    rows, _ = excerpt.collect_excerpt(old, new, html_dir)

    by_field = {row.field_name: row for row in rows}
    assert by_field["カウンター"].status == excerpt.STATUS_MATCH
    assert by_field["必要階級"].status == excerpt.STATUS_NO_ROW
    assert by_field["格闘判定力"].status == excerpt.STATUS_NO_ROW


def test_added_record_lists_only_table_fields(tmp_path: Path):
    html_dir = tmp_path / "html"
    _write_cache(html_dir)

    rows, _ = excerpt.collect_excerpt([], [_record(1, 中スロット=17)], html_dir)

    fields = {row.field_name for row in rows}
    assert "中スロット" in fields
    assert "MS名" not in fields
    assert "wiki_url" not in fields
    assert all(row.status != excerpt.STATUS_NO_ROW for row in rows)


def test_missing_html_and_missing_url(tmp_path: Path):
    no_url = make_ms_record("ザク_LV1")
    no_url.pop("wiki_url", None)
    old = [_record(2, 中スロット=29), no_url]
    new = [_record(2, 中スロット=20), make_ms_record("ザク_LV1") | {"HP": 1}]
    new[1].pop("wiki_url", None)

    rows, pages = excerpt.collect_excerpt(old, new, tmp_path / "missing")

    statuses = {row.name: row.status for row in rows}
    assert statuses[f"{BASE}_LV2"] == excerpt.STATUS_NO_HTML
    assert statuses["ザク_LV1"] == excerpt.STATUS_NO_URL
    assert pages[URL].html_found is False


def test_main_writes_report_pr_section_and_outputs(tmp_path: Path):
    html_dir = tmp_path / "html"
    _write_cache(html_dir)
    old_path = tmp_path / "before.json"
    new_path = tmp_path / "msData.json"
    write_json(old_path, [_record(1, 中スロット=16), _record(2, 中スロット=29)])
    write_json(new_path, [_record(1, 中スロット=17), _record(2, 中スロット=20)])
    reports = tmp_path / "reports"
    out = reports / "2026/10/source_excerpt_20261020.md"
    pr_section = tmp_path / "pr.md"
    github_output = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"

    rc = excerpt.main(
        [
            "--old",
            str(old_path),
            "--new",
            str(new_path),
            "--html-dir",
            str(html_dir),
            "--report-date",
            "20261020",
            "--out",
            str(out),
            "--pr-section-out",
            str(pr_section),
            "--max-pr-rows",
            "1",
            "--github-output",
            str(github_output),
            "--step-summary",
            str(summary),
        ]
    )

    assert rc == 0
    report = out.read_text(encoding="utf-8")
    assert "- excerpt_rows: 2" in report
    assert "- mismatch: 0" in report
    assert URL in report
    assert "中距離: LV1=17 / LV2=20" in report
    section = pr_section.read_text(encoding="utf-8")
    assert section.count("| 一致 |") == 1
    assert f"残り 1 件は {out}" in section
    outputs = github_output.read_text(encoding="utf-8")
    assert "excerpt_rows=2" in outputs
    assert "mismatch_count=0" in outputs
    assert "html_missing_count=0" in outputs
    assert "### 取得元抜粋" in summary.read_text(encoding="utf-8")
    assert validate_reports(reports, Path("schema/reports")) == []


def test_pr_section_without_rows():
    assert excerpt.build_pr_section([], "x.md", 20)[-1] == "変更項目なし"


def test_source_cells_are_markdown_escaped(tmp_path: Path):
    html_dir = tmp_path / "html"
    _write_cache(html_dir, html=HTML.replace("<td>20</td>", "<td>20 | <b>x</b></td>"))
    rows, _ = excerpt.collect_excerpt(
        [_record(2, 中スロット=29)], [_record(2, 中スロット=20)], html_dir
    )

    cells = rows[0].cells()
    assert "\\|" in cells[5]
    assert "<" not in cells[7]


def test_main_rejects_invalid_input(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    obj = tmp_path / "obj.json"
    obj.write_text(json.dumps({"a": 1}), encoding="utf-8")
    common = ["--report-date", "20261020", "--out", str(tmp_path / "o.md")]

    assert excerpt.main(["--old", str(bad), "--new", str(obj), *common]) == 1
    assert excerpt.main(["--old", str(obj), "--new", str(obj), *common]) == 1
