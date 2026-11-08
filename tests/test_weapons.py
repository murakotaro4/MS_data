"""兵装名の抽出（ms_data.scraping.weapons）と data/weapons.json の更新・検証。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_data.core import paths
from ms_data.net.cache_http import url_to_slug
from ms_data.pipeline import update_weapons as uw
from ms_data.scraping.weapons import extract_weapons
from ms_data.validation import validate_weapons as vw

from helpers import write_json

FIXTURE = Path(__file__).parent / "fixtures" / "weapons_page.html"
URL_A = "https://w.atwiki.jp/battle-operation2/pages/5702.html"
URL_B = "https://w.atwiki.jp/battle-operation2/pages/343.html"


def _fixture_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _put_html(html_dir: Path, url: str, html: str, status: int | None = 200) -> None:
    html_dir.mkdir(parents=True, exist_ok=True)
    slug = url_to_slug(url)
    (html_dir / f"{slug}.html").write_text(html, encoding="utf-8")
    if status is not None:
        write_json(html_dir / f"{slug}.meta.json", {"url": url, "http_status": status})


def _rec(ms: str, name: str, url: str, kind: str = "副兵装") -> dict:
    return {"ms_name": ms, "kind": kind, "name": name, "levels": [1], "wiki_url": url}


# ---------------------------------------------------------------------------
# 抽出
# ---------------------------------------------------------------------------


def test_extract_weapons_from_page_structure():
    weapons = extract_weapons(_fixture_html())
    assert weapons == [
        {
            "name": "メッサー用L・B・R",
            "kind": "主兵装",
            "category": "射撃",
            "levels": [1, 2, 3, 4],
        },
        {
            "name": "ハイパー・ビーム・ライフル",
            "kind": "主兵装",
            "category": "射撃",
            "levels": [1, 2],
        },
        {
            "name": "メッサー用ビーム・サーベル",
            "kind": "主兵装",
            "category": "格闘",
            "levels": [1, 2],
        },
        # 副兵装の h2 より前（主兵装の h2 の下）に並ぶ副兵装も拾う
        {"name": "F01型用バルカン砲", "kind": "副兵装", "levels": [1, 2]},
        {"name": "36mmファランクスx2", "kind": "副兵装", "levels": [1]},
        # シールドは見出し行の LV1/LV2/LV3 から LV を読む
        {"name": "メッサーF01型用シールド", "kind": "副兵装", "levels": [1, 2, 3]},
    ]


def test_extract_weapons_ignores_menu_status_tables_and_notes():
    names = {w["name"] for w in extract_weapons(_fixture_html())}
    # サイドメニュー・数値情報の表・表の無い見出し・備考の詳細見出しは兵装にしない
    for name in ("メニューの武器", "機体", "移動方向補正＜地上＞", "見出しだけの項目"):
        assert name not in names
    # 備考の「主兵装詳細」に同名の h4 があっても重複させない
    assert (
        sum(w["name"] == "メッサー用L・B・R" for w in extract_weapons(_fixture_html()))
        == 1
    )


def test_extract_weapons_without_pagetitle_returns_empty():
    assert extract_weapons("<html><body><h2>主兵装</h2></body></html>") == []


def test_extract_main_weapon_without_category_heading():
    html = """
    <h2 id="pagetitle">機体</h2>
    <h2>主兵装</h2>
    <div id="table_weapon"><table>
    <thead><tr><th>武器名</th><th>LV</th></tr></thead>
    <tr><th>ザク・マシンガン</th><td>LV1</td></tr>
    </table></div>
    <h2>スキル情報</h2>
    """
    assert extract_weapons(html) == [
        {"name": "ザク・マシンガン", "kind": "主兵装", "levels": [1]}
    ]


# ---------------------------------------------------------------------------
# 更新（差し替え方式）
# ---------------------------------------------------------------------------


def test_update_replaces_only_ms_with_html(tmp_path):
    html_dir = tmp_path / "html"
    _put_html(html_dir, URL_A, _fixture_html())
    index = [{"name": "メッサーF01型", "url": URL_A}, {"name": "ザクⅡ", "url": URL_B}]
    existing = [
        _rec("メッサーF01型", "古い兵装", URL_A),
        _rec("ザクⅡ", "ザク・マシンガン", URL_B, kind="主兵装"),
    ]
    records, stats = uw.update_weapons(
        index=index, html_dir=html_dir, existing=existing
    )

    by_ms: dict[str, list[str]] = {}
    for rec in records:
        by_ms.setdefault(rec["ms_name"], []).append(rec["name"])
    assert "古い兵装" not in by_ms["メッサーF01型"]
    assert by_ms["メッサーF01型"][0] == "メッサー用L・B・R"
    # HTML が無い機体は既存の行を残す
    assert by_ms["ザクⅡ"] == ["ザク・マシンガン"]
    assert stats["refreshed_count"] == 1
    assert stats["kept_count"] == 1
    # 機体名順に並ぶ
    assert [r["ms_name"] for r in records] == sorted(r["ms_name"] for r in records)
    first = records[[r["ms_name"] for r in records].index("メッサーF01型")]
    assert list(first) == list(uw.RECORD_KEYS)
    assert first["wiki_url"] == URL_A


def test_update_keeps_existing_when_page_has_no_weapons_or_bad_status(tmp_path):
    html_dir = tmp_path / "html"
    _put_html(html_dir, URL_A, "<html>Just a moment...</html>")
    _put_html(html_dir, URL_B, _fixture_html(), status=403)
    index = [{"name": "A", "url": URL_A}, {"name": "B", "url": URL_B}]
    existing = [_rec("A", "a1", URL_A), _rec("B", "b1", URL_B)]
    records, stats = uw.update_weapons(
        index=index, html_dir=html_dir, existing=existing
    )
    assert records == existing
    assert stats["empty_kept"] == ["A"]
    assert stats["html_count"] == 1


def test_update_meta_without_status_or_missing_meta_is_used(tmp_path):
    html_dir = tmp_path / "html"
    _put_html(html_dir, URL_A, _fixture_html(), status=None)
    records, _ = uw.update_weapons(
        index=[{"name": "A", "url": URL_A}], html_dir=html_dir, existing=[]
    )
    assert records and all(r["ms_name"] == "A" for r in records)


def test_update_ignores_broken_meta(tmp_path):
    html_dir = tmp_path / "html"
    _put_html(html_dir, URL_A, _fixture_html())
    (html_dir / f"{url_to_slug(URL_A)}.meta.json").write_text("{", encoding="utf-8")
    records, stats = uw.update_weapons(
        index=[{"name": "A", "url": URL_A}], html_dir=html_dir, existing=[]
    )
    assert records == [] and stats["html_count"] == 0


def test_update_removes_ms_missing_from_index(tmp_path):
    index = [{"name": "A", "url": URL_A}, {"name": "A", "url": URL_B}, {"name": 1}]
    existing = [_rec("A", "a1", URL_A), _rec("消えた機体", "x", URL_B)]
    records, stats = uw.update_weapons(
        index=index, html_dir=tmp_path, existing=existing
    )
    assert records == [_rec("A", "a1", URL_A)]
    assert stats["removed_ms"] == ["消えた機体"]
    assert stats["index_count"] == 1


def test_update_skips_mass_removal(tmp_path):
    existing = [_rec(f"機体{i:02d}", "w", URL_A) for i in range(20)]
    index = [{"name": "機体00", "url": URL_A}]
    records, stats = uw.update_weapons(
        index=index, html_dir=tmp_path, existing=existing
    )
    assert records == existing
    assert stats["removed_ms"] == []
    assert len(stats["removal_skipped"]) == 19


def test_dump_weapons_one_record_per_line():
    assert uw.dump_weapons([]) == "[]\n"
    text = uw.dump_weapons([_rec("A", "a", URL_A), _rec("B", "b", URL_B)])
    lines = text.splitlines()
    assert lines[0] == "[" and lines[-1] == "]"
    assert len(lines) == 4
    assert json.loads(text)[1]["name"] == "b"


def test_main_writes_file_outputs_and_summary(tmp_path, capsys):
    html_dir = tmp_path / "html"
    _put_html(html_dir, URL_A, _fixture_html())
    index_path = tmp_path / "index.json"
    write_json(index_path, [{"name": "メッサーF01型", "url": URL_A}])
    weapons_path = tmp_path / "data" / "weapons.json"
    gh_out = tmp_path / "gh_out.txt"
    summary = tmp_path / "summary.md"
    argv = [
        "--index",
        str(index_path),
        "--html-dir",
        str(html_dir),
        "--weapons",
        str(weapons_path),
        "--github-output",
        str(gh_out),
        "--step-summary",
        str(summary),
    ]
    assert uw.main(argv) == 0
    assert "weapons_changed=true" in gh_out.read_text(encoding="utf-8")
    assert "兵装名一覧" in summary.read_text(encoding="utf-8")
    assert "weapons: ms=1 records=6" in capsys.readouterr().out
    assert vw.main([str(weapons_path)]) == 0

    # 同じ入力で再実行しても変更なし
    gh_out.unlink()
    assert uw.main(argv) == 0
    assert "weapons_changed=false" in gh_out.read_text(encoding="utf-8")


def test_main_summary_lists_kept_and_removed(tmp_path):
    html_dir = tmp_path / "html"
    _put_html(html_dir, URL_A, "<html></html>")
    index_path = tmp_path / "index.json"
    write_json(index_path, [{"name": "A", "url": URL_A}])
    weapons_path = tmp_path / "weapons.json"
    weapons_path.write_text(
        uw.dump_weapons([_rec("A", "a", URL_A), _rec("Z", "z", URL_B)]),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.md"
    argv = ["--index", str(index_path), "--html-dir", str(html_dir)]
    argv += ["--weapons", str(weapons_path), "--step-summary", str(summary)]
    assert uw.main(argv) == 0
    text = summary.read_text(encoding="utf-8")
    assert "既存の行を残した機体: 1 件（A）" in text
    assert "削除した機体: 1 件（Z）" in text


def test_main_summary_reports_skipped_removal(tmp_path):
    index_path = tmp_path / "index.json"
    write_json(index_path, [{"name": "機体00", "url": URL_A}])
    weapons_path = tmp_path / "weapons.json"
    existing = [_rec(f"機体{i:02d}", "w", URL_A) for i in range(20)]
    weapons_path.write_text(uw.dump_weapons(existing), encoding="utf-8")
    summary = tmp_path / "summary.md"
    argv = ["--index", str(index_path), "--html-dir", str(tmp_path / "none")]
    argv += ["--weapons", str(weapons_path), "--step-summary", str(summary)]
    assert uw.main(argv) == 0
    assert "削除を見送り: 19 件" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("index_content", [None, [], {"a": 1}])
def test_main_rejects_missing_or_invalid_index(tmp_path, index_content):
    index_path = tmp_path / "index.json"
    if index_content is not None:
        write_json(index_path, index_content)
    assert (
        uw.main(["--index", str(index_path), "--weapons", str(tmp_path / "w.json")])
        == 2
    )


def test_main_rejects_non_list_weapons(tmp_path):
    index_path = tmp_path / "index.json"
    write_json(index_path, [{"name": "A", "url": URL_A}])
    weapons_path = tmp_path / "w.json"
    write_json(weapons_path, {"bad": True})
    assert uw.main(["--index", str(index_path), "--weapons", str(weapons_path)]) == 2


# ---------------------------------------------------------------------------
# 検証
# ---------------------------------------------------------------------------


def _schema() -> dict:
    return json.loads(paths.WEAPONS_SCHEMA.read_text(encoding="utf-8"))


def test_repository_weapons_json_is_valid():
    assert vw.validate(paths.WEAPONS_JSON, paths.WEAPONS_SCHEMA) == []


def test_repository_weapons_json_contains_issue_examples():
    data = json.loads(paths.WEAPONS_JSON.read_text(encoding="utf-8"))
    names = {r["name"] for r in data if r["ms_name"] == "メッサーF01型"}
    assert {
        "メッサー用L・B・R",
        "メッサー用ビーム・サーベル",
        "F01型用バルカン砲",
    } <= names


def test_validate_schema_errors():
    bad = [
        {"ms_name": "A", "kind": "その他", "name": "", "levels": [0], "wiki_url": "x"}
    ]
    messages = vw.validate_schema(bad, _schema())
    assert any("その他" in m for m in messages)
    assert len(messages) >= 4


def test_validate_semantics_errors():
    data = [
        _rec("B", "b", URL_B),
        _rec("B", "b", URL_A),
        {**_rec("A", "a", URL_A), "levels": [2, 1]},
    ]
    messages = vw.validate_semantics(data)
    assert any("duplicate" in m for m in messages)
    assert any("wiki_url differs" in m for m in messages)
    assert any("not sorted" in m for m in messages)
    assert any("levels not sorted" in m for m in messages)


def test_validate_main(tmp_path, capsys):
    assert vw.main([str(tmp_path / "missing.json")]) == 1
    bad = tmp_path / "bad.json"
    write_json(bad, [{"ms_name": "A"}])
    assert vw.main([str(bad)]) == 1
    assert "NG:" in capsys.readouterr().err
