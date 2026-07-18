import pytest

from ms_data.scraping import change_detection, fetch_state


@pytest.mark.parametrize(
    "loader",
    [
        change_detection.load_msdata_base_index,
        fetch_state.load_detail_fetch_state,
    ],
)
def test_missing_state_files_are_quiet_fallbacks(tmp_path, capsys, loader):
    assert loader(tmp_path / "missing.json") == {}
    assert capsys.readouterr().err == ""


def test_find_latest_provenance_skips_broken_json(tmp_path):
    broken = tmp_path / "provenance_20260719.json"
    broken.write_text("{broken", encoding="utf-8")

    assert change_detection.find_latest_provenance(tmp_path) == (None, None)


def test_find_latest_provenance_does_not_swallow_programming_errors(tmp_path):
    invalid_shape = tmp_path / "provenance_20260719.json"
    invalid_shape.write_text("[]", encoding="utf-8")

    with pytest.raises(TypeError):
        change_detection.find_latest_provenance(tmp_path)


def test_load_msdata_base_index_falls_back_for_broken_json(tmp_path):
    broken = tmp_path / "msData.json"
    broken.write_text("{broken", encoding="utf-8")

    assert change_detection.load_msdata_base_index(broken) == {}


def test_load_detail_fetch_state_falls_back_for_broken_json(tmp_path):
    broken = tmp_path / "detail_fetch_state.json"
    broken.write_text("{broken", encoding="utf-8")

    assert fetch_state.load_detail_fetch_state(broken) == {}


@pytest.mark.parametrize(
    "loader",
    [
        change_detection.load_msdata_base_index,
        fetch_state.load_detail_fetch_state,
    ],
)
def test_json_loaders_do_not_swallow_programming_errors(tmp_path, monkeypatch, loader):
    path = tmp_path / "input.json"
    path.write_text("{}", encoding="utf-8")
    module = change_detection if loader is change_detection.load_msdata_base_index else fetch_state
    monkeypatch.setattr(
        module.json,
        "loads",
        lambda text: (_ for _ in ()).throw(TypeError("bad parser call")),
    )

    with pytest.raises(TypeError, match="bad parser call"):
        loader(path)
