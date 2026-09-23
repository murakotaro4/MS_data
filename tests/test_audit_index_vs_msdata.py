"""audit_index_vs_msdata（index と msData の突合監査）のテスト。"""

import pytest

from ms_data.audit.audit_index_vs_msdata import (
    audit,
    extract_base_levels,
    main,
    normalize_towards_index,
    render_markdown,
)

from helpers import write_json


def test_extract_base_levels_groups_lv_suffix():
    records = [
        {"MS名": "ガンダム_LV1"},
        {"MS名": "ガンダム_LV2"},
        {"MS名": "ジム_LV1"},
        {"MS名": "LVなし機体"},  # _LVn が無いものは対象外
        {"コスト": 300},  # MS名なしは対象外
    ]

    bases = extract_base_levels(records)

    assert bases == {"ガンダム": [1, 2], "ジム": [1]}


@pytest.mark.parametrize(
    "name, expected, expected_rules",
    [
        ("ガンダム[白]", "ガンダム［白］", ["[]→［］"]),
        ("ガンダムMk-II", "ガンダムMk-Ⅱ", ["II→Ⅱ"]),
        ("Zガンダム", "Ζガンダム", ["Z/ZZ→Ζ/ΖΖ（文脈）"]),
        ("ZZガンダム", "ΖΖガンダム", ["Z/ZZ→Ζ/ΖΖ（文脈）"]),
        ("ゲルググ・Ｖ", "ゲルググ・V", ["Ｖ→V"]),
        # 文脈に合わない Z は変換しない
        ("Zアッザム", "Zアッザム", []),
        # 複合（[] と II）
        ("ジム[改]Mk-II", "ジム［改］Mk-Ⅱ", ["[]→［］", "II→Ⅱ"]),
    ],
)
def test_normalize_towards_index_rules(name, expected, expected_rules):
    norm, rules = normalize_towards_index(name)

    assert norm == expected
    assert rules == expected_rules


def test_audit_detects_diffs(tmp_path):
    index_path = tmp_path / "index.json"
    write_json(
        index_path,
        [
            {"name": "ガンダム", "属性": "汎用", "cost": 300},
            {"name": "ジム", "属性": "汎用", "cost": 200},
            {"name": "Ζガンダム", "属性": "汎用", "cost": 500},
            {"name": "ザク", "属性": "強襲", "cost": 300},  # index のみ
        ],
    )
    ms_path = tmp_path / "msData.json"
    write_json(
        ms_path,
        [
            {"MS名": "ガンダム_LV1", "属性": "汎用", "コスト": 300},
            {"MS名": "ガンダム_LV2", "属性": "汎用", "コスト": 350},
            # 属性・コストとも index と不一致（LV 最小レコードが代表）
            {"MS名": "ジム_LV1", "属性": "支援", "コスト": 250},
            # 正規化（Z→Ζ）で index と一致する
            {"MS名": "Zガンダム_LV1", "属性": "汎用", "コスト": 500},
            # 正規化しても index に無い
            {"MS名": "オリジン_LV1", "属性": "汎用", "コスト": 400},
        ],
    )

    result = audit(index_path, ms_path)

    assert result["index_total"] == 4
    assert result["ms_base_total"] == 4
    # コードポイント順ソート（ギリシャ文字・ASCII はカナより前）
    assert result["index_only"] == ["Ζガンダム", "ザク"]
    assert result["ms_only"] == ["Zガンダム", "オリジン"]
    assert [m["norm_name"] for m in result["normalized_matches"]] == ["Ζガンダム"]
    assert [m["ms_name"] for m in result["normalized_unmatched"]] == ["オリジン"]
    assert result["attr_mismatches"] == [("ジム", "汎用", "支援")]
    assert result["cost_mismatches"] == [("ジム", 200, 250)]

    text = render_markdown(result)
    assert "## indexのみに存在（msData未収載）" in text
    assert "- ザク" in text
    assert "## msDataのみ（正規化すればindexと一致）" in text
    assert "- Zガンダム → Ζガンダム | LV1 | Z/ZZ→Ζ/ΖΖ（文脈）" in text
    assert "## msDataのみ（正規化してもindexに不在）" in text
    assert "- オリジン_LV1" not in text  # 基底名で出力される
    assert "- オリジン（norm: オリジン） | LV1 |" in text
    assert "- 属性: ジム: index=汎用 / msData=支援" in text
    assert "- コスト: ジム: index=200 / msData=250" in text


def test_render_markdown_reports_no_diff():
    result = {
        "index_total": 1,
        "ms_base_total": 1,
        "index_only": [],
        "ms_only": [],
        "attr_mismatches": [],
        "cost_mismatches": [],
        "normalized_matches": [],
        "normalized_unmatched": [],
    }

    text = render_markdown(result)

    assert "差分は検出されませんでした。" in text


def test_main_writes_markdown_report(tmp_path, capsys):
    index_path = tmp_path / "index.json"
    write_json(index_path, [{"name": "ガンダム", "属性": "汎用", "cost": 300}])
    ms_path = tmp_path / "msData.json"
    write_json(ms_path, [{"MS名": "ガンダム_LV1", "属性": "汎用", "コスト": 300}])
    out = tmp_path / "audit.md"  # 既定の reports/ に書かないよう必ず --out を渡す

    rc = main(["--index", str(index_path), "--ms", str(ms_path), "--out", str(out)])

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "# index vs msData 監査レポート" in text
    assert "- index（一覧）: 1 件" in text
    assert "差分は検出されませんでした。" in text
    assert f"wrote {out}" in capsys.readouterr().out
