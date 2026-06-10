"""preview_params（スキル効果のプレビュー集約）のテスト。"""

import json
import sys

from ms_data.skills.preview_params import aggregate_effects, build_preview, main


def test_aggregate_effects_add_and_mul():
    effects_list = [
        {
            "射撃補正": {"op": "add", "value": 5},
            "スピード": {"op": "mul", "factor": 1.1},
        },
        {
            "射撃補正": {"op": "add", "value": 10},
            "スピード": {"op": "mul", "factor": 1.2},
            "格闘補正": {"op": "add", "value": 3},
        },
        # 未知の op は無視される
        {"HP": {"op": "set", "value": 100}},
    ]

    agg = aggregate_effects(effects_list)

    assert agg["射撃補正"] == {"op": "add", "value": 15}
    assert agg["格闘補正"] == {"op": "add", "value": 3}
    assert agg["スピード"]["op"] == "mul"
    assert abs(agg["スピード"]["factor"] - 1.32) < 1e-9
    assert "HP" not in agg


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_inputs(tmp_path):
    msdata = tmp_path / "msData.json"
    _write_json(
        msdata,
        [
            {"MS名": "ブルー1号機_LV1"},
            {"MS名": "LVなし機体"},  # LV サフィックスなしはスキップ
            {"MS名": "ザク_LV1"},  # スキルなしはスキップ
            {"MS名": "ペイルライダー_LV1"},  # params 不在スキルのみ → スキップ
        ],
    )
    owners = tmp_path / "skill_owners_flat.json"
    _write_json(
        owners,
        {
            "owners": [
                {
                    "series": "ブルー1号機",
                    "ms_level": 1,
                    "skill": "能力UP「EXAM」",
                    "skill_level": 1,
                },
                {
                    "series": "ブルー1号機",
                    "ms_level": 1,
                    "skill": "params未定義スキル",
                    "skill_level": 1,
                },
                {
                    "series": "ペイルライダー",
                    "ms_level": 1,
                    "skill": "params未定義スキル",
                    "skill_level": 1,
                },
            ]
        },
    )
    params = tmp_path / "skills_params.json"
    _write_json(
        params,
        {
            "skills": [
                {
                    "name": "能力UP「EXAM」",
                    "levels": [
                        {
                            "level": 1,
                            "effects": {"射撃補正": {"op": "add", "value": 5}},
                        }
                    ],
                }
            ]
        },
    )
    return msdata, owners, params


def test_build_preview_joins_and_skips(tmp_path):
    msdata, owners, params = _write_inputs(tmp_path)

    preview = build_preview(msdata, owners, params)

    assert [rec["MS名"] for rec in preview] == ["ブルー1号機_LV1"]
    rec = preview[0]
    # skills には params 不在のものも列挙される
    assert rec["skills"] == [
        {"name": "能力UP「EXAM」", "level": 1},
        {"name": "params未定義スキル", "level": 1},
    ]
    # applied_skills / aggregated_effects は params があるものだけ
    assert [s["name"] for s in rec["applied_skills"]] == ["能力UP「EXAM」"]
    assert rec["aggregated_effects"] == {"射撃補正": {"op": "add", "value": 5}}


def test_main_writes_preview(monkeypatch, tmp_path, capsys):
    msdata, owners, params = _write_inputs(tmp_path)
    out = tmp_path / "derived" / "ms_params_preview.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preview_params",
            "--msdata",
            str(msdata),
            "--owners",
            str(owners),
            "--params",
            str(params),
            "--out",
            str(out),
        ],
    )

    rc = main()

    assert rc == 0
    preview = json.loads(out.read_text(encoding="utf-8"))
    assert len(preview) == 1
    assert preview[0]["MS名"] == "ブルー1号機_LV1"
    assert f"wrote: {out} (1 records)" in capsys.readouterr().out
