from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_data import tasks
from ms_data.scraping import custom_parts as cp
from ms_data.validation import validate_custom_parts as vcp

HEADER = (
    '<tr><th rowspan="2">名称</th><th rowspan="2">LV</th><th rowspan="2">レア度</th>'
    '<th colspan="3">消費スロット</th><th rowspan="2">説明</th></tr>'
    "<tr><th>近</th><th>中</th><th>遠</th></tr>"
)


def _table(rows: str) -> str:
    return f"<table>{HEADER}{rows}</table>"


def _page(tables: dict[str, str]) -> str:
    body = "".join(f"<h3>{cat}</h3>{_table(rows)}" for cat, rows in tables.items())
    return f'<html><body><div id="wikibody"><h2>一覧</h2>{body}</div></body></html>'


def _full_page(**override: str) -> str:
    tables = {
        "攻撃系": (
            '<tr><th rowspan="2"><a href="/p/279.html">射撃強化プログラム</a></th>'
            "<td>LV1</td><td>☆</td><td>0</td><td>0</td><td>1</td><td>射撃+2</td></tr>"
            "<tr><td>LV2</td><td>☆☆</td><td>0</td><td>0</td><td>3</td><td>射撃+5</td></tr>"
        ),
        "防御系": "<tr><th>強化フレーム</th><td>LV1</td><td>☆</td><td>0</td><td>0</td><td>1</td><td>x</td></tr>",
        "移動系": "<tr><th>噴射制御装置</th><td>LV1</td><td>☆</td><td>3</td><td>0</td><td>0</td><td>x</td></tr>",
        "補助系": "<tr><th>冷却システム</th><td>LV1</td><td>☆</td><td>1</td><td>0</td><td>0</td><td>x</td></tr>",
        "特殊系": "<tr><th>ハロ（V）</th><td>LV1</td><td>☆☆☆</td><td>0</td><td>0</td><td>0</td><td>x</td></tr>",
    }
    tables.update(override)
    return _page(tables)


def test_parse_expands_rowspan_and_categories() -> None:
    records = cp.parse_custom_parts(_full_page())
    assert records[:2] == [
        {
            "名称": "射撃強化プログラム",
            "LV": 1,
            "レア度": 1,
            "系統": "攻撃系",
            "出典URL": cp.CUSTOM_PARTS_URL,
        },
        {
            "名称": "射撃強化プログラム",
            "LV": 2,
            "レア度": 2,
            "系統": "攻撃系",
            "出典URL": cp.CUSTOM_PARTS_URL,
        },
    ]
    assert [r["系統"] for r in records] == [
        "攻撃系",
        "攻撃系",
        "防御系",
        "移動系",
        "補助系",
        "特殊系",
    ]
    assert records[-1]["レア度"] == 3


def test_parse_ignores_tables_without_name_header() -> None:
    html = _full_page().replace(
        "<h2>一覧</h2>", "<h2>一覧</h2><table><tr><th>近</th><th>中</th></tr></table>"
    )
    assert len(cp.parse_custom_parts(html)) == 6


@pytest.mark.parametrize(
    ("override", "message"),
    [
        (
            {
                "特殊系": "<tr><th>X</th><td>Lv?</td><td>☆</td><td>0</td><td>0</td><td>0</td><td>x</td></tr>"
            },
            "LV",
        ),
        (
            {
                "特殊系": "<tr><th>X</th><td>LV1</td><td>3</td><td>0</td><td>0</td><td>0</td><td>x</td></tr>"
            },
            "レア度",
        ),
        (
            {
                "特殊系": "<tr><th>冷却システム</th><td>LV1</td><td>☆</td><td>0</td><td>0</td><td>0</td><td>x</td></tr>"
            },
            "重複",
        ),
        (
            {
                "特殊系": "<tr><th></th><td>LV1</td><td>☆</td><td>0</td><td>0</td><td>0</td><td>x</td></tr>"
            },
            "名称",
        ),
    ],
)
def test_parse_rejects_unexpected_rows(override: dict[str, str], message: str) -> None:
    with pytest.raises(cp.CustomPartsParseError, match=message):
        cp.parse_custom_parts(_full_page(**override))


def test_parse_rejects_missing_category() -> None:
    html = _full_page().replace("<h3>特殊系</h3>", "<h3>その他</h3>")
    with pytest.raises(cp.CustomPartsParseError):
        cp.parse_custom_parts(html)
    html = _full_page().replace("<h3>特殊系</h3>", "")
    with pytest.raises(cp.CustomPartsParseError, match="特殊系"):
        cp.parse_custom_parts(html)


def test_parse_rejects_table_without_lv_header() -> None:
    html = _full_page().replace('<th rowspan="2">LV</th>', '<th rowspan="2">Lv</th>', 1)
    with pytest.raises(cp.CustomPartsParseError, match="見出し"):
        cp.parse_custom_parts(html)


def test_summarize_changes() -> None:
    old = [{"名称": "A", "LV": 1, "レア度": 1}, {"名称": "B", "LV": 1, "レア度": 1}]
    new = [{"名称": "A", "LV": 1, "レア度": 2}, {"名称": "C", "LV": 1, "レア度": 1}]
    assert cp.summarize_changes(old, new) == {
        "added": ["C LV1"],
        "removed": ["B LV1"],
        "changed": ["A LV1"],
    }


def test_main_writes_output_and_reports_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    html = tmp_path / "263.html"
    html.write_text(_full_page(), encoding="utf-8")
    out = tmp_path / "custom_parts.json"
    assert cp.main(["--html", str(html), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 6
    assert out.read_text(encoding="utf-8").endswith("]\n")
    assert "追加 6" in capsys.readouterr().out


def test_main_keeps_existing_file_on_parse_error(tmp_path: Path) -> None:
    html = tmp_path / "263.html"
    html.write_text("<html></html>", encoding="utf-8")
    out = tmp_path / "custom_parts.json"
    out.write_text("[]\n", encoding="utf-8")
    assert cp.main(["--html", str(html), "--out", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "[]\n"


def test_main_refuses_sharp_drop(tmp_path: Path) -> None:
    html = tmp_path / "263.html"
    html.write_text(_full_page(), encoding="utf-8")
    out = tmp_path / "custom_parts.json"
    old = [{"名称": f"P{i}", "LV": 1} for i in range(20)]
    out.write_text(json.dumps(old), encoding="utf-8")
    assert cp.main(["--html", str(html), "--out", str(out)]) == 1
    assert json.loads(out.read_text(encoding="utf-8")) == old


def test_main_fetches_via_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def fake_fetch(url: str, **kwargs: object) -> str:
        calls.append({"url": url, **kwargs})
        return _full_page()

    monkeypatch.setattr(cp, "fetch_html", fake_fetch)
    out = tmp_path / "custom_parts.json"
    assert cp.main(["--out", str(out), "--no-network", "--ttl", "1d"]) == 0
    assert calls == [
        {"url": cp.CUSTOM_PARTS_URL, "ttl": "1d", "no_network": True, "force": False}
    ]


def test_fetch_html_uses_cache_http(monkeypatch: pytest.MonkeyPatch) -> None:
    import ms_data.net.cache_http as cache_http
    import ms_data.net.client as client

    seen: dict[str, object] = {}

    class FakeCache:
        def __init__(self, _client: object, cfg: object) -> None:
            seen["cfg"] = cfg

        def get(self, url: str) -> tuple[str, dict]:
            seen["url"] = url
            return "<html/>", {}

    monkeypatch.setattr(cache_http, "CacheHTTP", FakeCache)
    monkeypatch.setattr(client, "get_scraper_client", lambda: object())
    assert cp.fetch_html("u", ttl="2d", no_network=True, force=True) == "<html/>"
    cfg = seen["cfg"]
    assert seen["url"] == "u"
    assert (cfg.ttl_seconds, cfg.no_network, cfg.force) == (172800, True, True)


def test_repository_custom_parts_json_is_valid() -> None:
    schema = json.loads(
        Path("schema/custom_parts.schema.json").read_text(encoding="utf-8")
    )
    data = json.loads(Path("data/custom_parts.json").read_text(encoding="utf-8"))
    assert vcp.validate_custom_parts(data, schema) == []


def test_validator_reports_schema_and_duplicates(tmp_path: Path) -> None:
    schema = json.loads(
        Path("schema/custom_parts.schema.json").read_text(encoding="utf-8")
    )
    rec = {
        "名称": "A",
        "LV": 1,
        "レア度": 1,
        "系統": "攻撃系",
        "出典URL": cp.CUSTOM_PARTS_URL,
    }
    messages = vcp.validate_custom_parts([rec, dict(rec), {**rec, "LV": 0}], schema)
    assert any("重複" in m for m in messages)
    assert any(m.startswith("2/LV") for m in messages)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([rec, rec]), encoding="utf-8")
    assert vcp.main([str(path)]) == 1
    assert vcp.main([str(tmp_path / "missing.json")]) == 1
    path.write_text(json.dumps([rec]), encoding="utf-8")
    assert vcp.main([str(path)]) == 0


def test_tasks_custom_parts_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, ...]] = []
    monkeypatch.setattr(tasks, "_run_python_module", lambda *a: captured.append(a) or 0)
    monkeypatch.setenv("NO_NET", "1")
    monkeypatch.setenv("TTL", "3d")
    assert tasks.main(["custom-parts"]) == 0
    assert tasks.main(["validate-custom-parts"]) == 0
    assert captured[0] == (
        "ms_data.scraping.custom_parts",
        "--out",
        "data/custom_parts.json",
        "--ttl",
        "3d",
        "--no-network",
    )
    assert captured[1] == (
        "ms_data.validation.validate_custom_parts",
        "data/custom_parts.json",
    )
    assert "validate-custom-parts" in tasks.CI_TARGETS


def test_data_update_workflow_rides_custom_parts_on_msdata_pr() -> None:
    from workflow_contract import workflow_text

    text = workflow_text("data_update.yml")
    step = text[text.index("- id: custom_parts") : text.index("- id: source_excerpt")]
    assert "if: steps.changes.outputs.changed == 'true'" in step
    assert "continue-on-error: true" in step
    assert "ms_data.tasks custom-parts" in step
    assert "ms_data.tasks validate-custom-parts" in step
    assert "git checkout -- data/custom_parts.json" in step
    add_paths = text[text.index("add-paths: |") :]
    assert "data/custom_parts.json" in add_paths.split("- id:")[0]
    ci = workflow_text("ci.yml")
    assert "data/custom_parts.json" in ci
    assert "ms_data.tasks validate-custom-parts" in ci
