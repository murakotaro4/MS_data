"""build_skills（skills_catalog / skill_owners 生成）のテスト。"""

import json
import sys

from ms_data.skills.build_skills import build_catalog, build_owners, main, name_to_id


def test_name_to_id_exact_prefix_and_unknown():
    assert name_to_id("能力UP「EXAM」") == "exam"
    # 前方一致フォールバック（末尾に注記が付く表記揺れ）
    assert name_to_id("能力UP「EXAM」(発動条件あり)") == "exam"
    assert name_to_id("  能力UP「NT-D」  ") == "ntd"
    assert name_to_id("未知のスキル") is None


def test_build_catalog_skips_unknown_and_keeps_phases():
    data = {
        "skills": [
            {
                "name": "能力UP「EXAM」",
                "levels": [
                    {
                        "level": 1,
                        "activation": "手動",
                        "duration_sec": 30,
                        "effects": {"射撃補正": {"op": "add", "value": 5}},
                        "tags": ["buff"],
                    }
                ],
            },
            {
                "name": "能力UP「NT-D」",
                "levels": [],
                "phases": [
                    {
                        "name": "能力UP「覚醒」",
                        "levels": [{"level": 2, "activation": "自動"}],
                    },
                    {"name": "独自フェーズ", "levels": []},
                ],
            },
            {"name": "未知のスキル", "levels": [{"level": 1}]},
        ]
    }

    catalog = build_catalog(data)

    assert [s["id"] for s in catalog["skills"]] == ["exam", "ntd"]
    exam = catalog["skills"][0]
    assert exam["levels"] == [
        {
            "level": 1,
            "activation": "手動",
            "duration_sec": 30,
            "effects": {"射撃補正": {"op": "add", "value": 5}},
            "tags": ["buff"],
        }
    ]
    assert "phases" not in exam
    ntd = catalog["skills"][1]
    assert [p["id"] for p in ntd["phases"]] == ["awaken", "独自フェーズ"]
    assert ntd["phases"][0]["levels"][0]["level"] == 2


def test_build_owners_takes_max_level_and_sorts_series():
    data = {
        "skill_owners": [
            {"name": "能力UP「EXAM」", "level": 1, "owners": ["ブルー1号機"]},
            # 同一シリーズ・同一スキルは最大レベルを採用
            {"name": "能力UP「EXAM」", "level": 3, "owners": ["ブルー1号機"]},
            {"name": "能力UP「HADES」", "level": 2, "owners": ["ペイルライダー", " "]},
            # 未知スキルはスキップ
            {"name": "未知のスキル", "level": 1, "owners": ["ガンダム"]},
        ]
    }

    owners = build_owners(data)

    assert owners == {
        "owners": [
            {"series": "ブルー1号機", "base": [{"id": "exam", "level": 3}]},
            {"series": "ペイルライダー", "base": [{"id": "hades", "level": 2}]},
        ]
    }


def test_main_writes_catalog_and_owners(monkeypatch, tmp_path, capsys):
    src = tmp_path / "skills.json"
    src.write_text(
        json.dumps(
            {
                "skills": [{"name": "能力UP「EXAM」", "levels": [{"level": 1}]}],
                "skill_owners": [
                    {"name": "能力UP「EXAM」", "level": 1, "owners": ["ブルー1号機"]}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out_catalog = tmp_path / "data" / "skills_catalog.json"
    out_owners = tmp_path / "data" / "skill_owners.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_skills",
            "--in",
            str(src),
            "--out-catalog",
            str(out_catalog),
            "--out-owners",
            str(out_owners),
        ],
    )

    rc = main()

    assert rc == 0
    catalog = json.loads(out_catalog.read_text(encoding="utf-8"))
    assert catalog["skills"][0]["id"] == "exam"
    owners = json.loads(out_owners.read_text(encoding="utf-8"))
    assert owners["owners"][0]["series"] == "ブルー1号機"
    assert f"wrote: {out_catalog}" in capsys.readouterr().out
