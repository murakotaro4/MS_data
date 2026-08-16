from ms_data.skills.build_param_skills import (
    _to_int,
    _to_percent,
    build_params,
    extract_param_effects,
)


def test_build_params_golden():
    rows = [
        {
            "skill": "能力UP「EXAM」",
            "level": 1,
            "desc": "",
            "details_text": "・射撃補正+25\n・スピード+10\n・スラスター消費-50%",
        },
        {
            "skill": "能力UP「EXAM」",
            "level": 1,
            "desc": "",
            "details_text": "・射撃補正+5",
        },
        {
            "skill": "空中制御プログラム",
            "level": 1,
            "desc": "",
            "details_text": "・スピード+5",
        },
    ]
    audit = {}

    data = build_params(
        rows,
        policy={"include_exact": ["能力UP「EXAM」"]},
        audit=audit,
    )

    assert data == {
        "skills": [
            {
                "name": "能力UP「EXAM」",
                "levels": [
                    {
                        "level": 1,
                        "effects": {
                            "射撃補正": {"op": "add", "value": 25},
                            "スピード": {"op": "add", "value": 10},
                            "スラスター消費": {"op": "mul", "factor": 0.5},
                        },
                    }
                ],
            }
        ]
    }
    assert audit == {
        "excluded_param_rows": [
            {
                "skill": "空中制御プログラム",
                "level": 1,
                "effects": {"スピード": {"op": "add", "value": 5}},
            }
        ]
    }


def test_build_params_policy_fullwidth_colon_matches_extracted_name():
    # 抽出側は「：」を「:」へ正規化するため、ポリシー側が全角表記でも一致すること
    rows = [
        {
            "skill": "能力UP「NT-D:共鳴」",
            "level": 1,
            "desc": "",
            "details_text": "・高速移動+10\n・スラスター消費-50%",
        },
    ]

    data = build_params(
        rows,
        policy={"include_exact": ["能力UP「NT-D：共鳴」"]},
        audit=None,
    )

    assert data == {
        "skills": [
            {
                "name": "能力UP「NT-D:共鳴」",
                "levels": [
                    {
                        "level": 1,
                        "effects": {
                            "高速移動": {"op": "add", "value": 10},
                            "スラスター消費": {"op": "mul", "factor": 0.5},
                        },
                    }
                ],
            }
        ]
    }


def test_extract_param_effects_skips_blank_and_splits_midpoint():
    effects = extract_param_effects("\n・射撃補正+10・スピード+5\n\n")
    assert effects == {
        "射撃補正": {"op": "add", "value": 10},
        "スピード": {"op": "add", "value": 5},
    }


def test_extract_param_effects_keeps_larger_abs_for_same_key():
    effects = extract_param_effects("射撃補正+5\n射撃補正+25")
    assert effects == {"射撃補正": {"op": "add", "value": 25}}


def test_extract_param_effects_expands_all_resistances():
    effects = extract_param_effects("各耐性+10")
    assert effects == {
        "耐ビーム補正": {"op": "add", "value": 10},
        "耐実弾補正": {"op": "add", "value": 10},
        "耐格闘補正": {"op": "add", "value": 10},
    }


def test_extract_param_effects_individual_resistance():
    effects = extract_param_effects("耐ビーム補正+8")
    assert effects == {"耐ビーム補正": {"op": "add", "value": 8}}


def test_extract_param_effects_thruster_increase():
    effects = extract_param_effects("スラスター消費+50%")
    assert effects == {"スラスター消費": {"op": "mul", "factor": 1.5}}


def test_extract_param_effects_damage_taken_decrease():
    effects = extract_param_effects("被ダメージ-30%")
    assert effects == {"被ダメージ": {"op": "mul", "factor": 0.7}}


def test_build_params_falls_back_to_desc_when_details_empty():
    data = build_params(
        [
            {
                "skill": "能力UP「EXAM」",
                "level": 1,
                "desc": "スピード+10",
                "details_text": "",
            }
        ],
        policy=None,
        audit=None,
    )
    assert data == {
        "skills": [
            {
                "name": "能力UP「EXAM」",
                "levels": [
                    {
                        "level": 1,
                        "effects": {"スピード": {"op": "add", "value": 10}},
                    }
                ],
            }
        ]
    }


def test_build_params_exclude_exact_records_audit():
    audit: dict = {}
    data = build_params(
        [
            {
                "skill": "能力UP「EXAM」",
                "level": 1,
                "desc": "",
                "details_text": "・スピード+10",
            }
        ],
        policy={"exclude_exact": ["能力UP「EXAM」"]},
        audit=audit,
    )
    assert data == {"skills": []}
    assert audit == {
        "excluded_param_rows": [
            {
                "skill": "能力UP「EXAM」",
                "level": 1,
                "effects": {"スピード": {"op": "add", "value": 10}},
            }
        ]
    }


def test_build_params_skips_rows_without_effects():
    data = build_params(
        [
            {
                "skill": "能力UP「EXAM」",
                "level": 1,
                "desc": "よろけ耐性",
                "details_text": "",
            }
        ],
        policy=None,
        audit=None,
    )
    assert data == {"skills": []}


def test_to_int_and_to_percent_parse_or_none():
    assert _to_int("+12") == 12
    assert _to_int("なし") is None
    assert _to_percent("-50%") == -50
    assert _to_percent("50") is None
