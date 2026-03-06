from scripts.build_param_skills import build_params


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
