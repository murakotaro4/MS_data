from pathlib import Path

import scripts.validate_skills_data as vs


def test_validate_skills_data_main_accepts_committed_files():
    assert vs.main([]) == 0


def test_validate_against_schema_rejects_invalid_skills_params():
    invalid = {"skills": [{"name": "能力UP「EXAM」", "levels": [{"level": 1}]}]}
    errors = vs.validate_against_schema(
        invalid, Path("schema/skills_params.schema.json")
    )
    assert errors


def test_validate_skills_data_main_accepts_absolute_requested_path():
    assert vs.main(["--path", str(Path("data/skills_params.json").resolve())]) == 0


def test_validate_skills_data_main_rejects_unknown_requested_path():
    assert vs.main(["--path", "data/unknown.json"]) == 2
