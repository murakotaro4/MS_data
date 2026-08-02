from ms_data.skills.build_owners_flat import (
    build_audit,
    build_flat_owners,
    normalize_series_levels,
)


def test_build_owners_flat_golden():
    owners_table = {
        "rows": [
            {
                "skill": "能力UP「EXAM」",
                "level": 1,
                "owners": [
                    {"name": "テストMS [通常]"},
                    {"name": "未収載機"},
                ],
            },
            {
                "skill": "空中制御プログラム",
                "level": 1,
                "owners": [{"name": "別機体"}],
            },
        ]
    }
    series_levels = normalize_series_levels(
        {
            "テストMS [通常]": {1, 2},
            "別機体": {1},
        }
    )

    owners_out, unknown_series = build_flat_owners(
        owners_table,
        series_levels,
        include={"能力UP「EXAM」"},
    )

    assert owners_out == [
        {
            "skill": "能力UP「EXAM」",
            "skill_level": 1,
            "series": "テストMS ［通常］",
            "ms_level": 1,
        },
        {
            "skill": "能力UP「EXAM」",
            "skill_level": 1,
            "series": "テストMS ［通常］",
            "ms_level": 2,
        },
    ]
    assert unknown_series == {
        "未収載機": [{"skill": "能力UP「EXAM」", "skill_level": 1}]
    }
    assert build_audit(unknown_series, owners_out) == {
        "unknown_series_count": 1,
        "unknown_series": [
            {
                "series": "未収載機",
                "examples": [{"skill": "能力UP「EXAM」", "skill_level": 1}],
            }
        ],
        "owners_count": 2,
    }


def test_build_flat_owners_include_fullwidth_colon_matches_extracted_name():
    # 抽出側は「：」を「:」へ正規化するため、ポリシー側が全角表記でも一致すること
    owners_table = {
        "rows": [
            {
                "skill": "能力UP「NT-D:共鳴」",
                "level": 1,
                "owners": [{"name": "テストMS"}],
            },
        ]
    }
    series_levels = normalize_series_levels({"テストMS": {1}})

    owners_out, unknown_series = build_flat_owners(
        owners_table,
        series_levels,
        include={"能力UP「NT-D：共鳴」"},
    )

    assert owners_out == [
        {
            "skill": "能力UP「NT-D:共鳴」",
            "skill_level": 1,
            "series": "テストMS",
            "ms_level": 1,
        },
    ]
    assert unknown_series == {}
