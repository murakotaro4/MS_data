import json

import pytest

from ms_data.scraping import extract_skills


@pytest.mark.parametrize(
    "command", ["fetch", "parse", "all", "table", "owners-table"]
)
def test_all_subcommands_help_exits_zero(command):
    with pytest.raises(SystemExit) as exc_info:
        extract_skills.main([command, "--help"])

    assert exc_info.value.code == 0


def test_parse_uses_local_html_without_network(tmp_path, load_fixture, monkeypatch):
    html_path = tmp_path / "skills.html"
    html_path.write_text(
        load_fixture("extract_skill_owners_rowspan.html"), encoding="utf-8"
    )
    output = tmp_path / "skills.json"

    def fail_on_network():
        raise AssertionError("parse must not create a network client")

    monkeypatch.setattr(extract_skills, "get_client", fail_on_network)

    assert (
        extract_skills.main(
            ["parse", "--in", str(html_path), "--out", str(output)]
        )
        == 0
    )
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["source"] == extract_skills.SKILL_URL
    assert data["skills"]
    assert data["skill_owners"]
