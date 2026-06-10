"""jsonl_to_json（JSONL→JSON配列変換）のテスト。"""

import json
import sys

from ms_data.pipeline.jsonl_to_json import main


def _run(monkeypatch, input_path, output_path) -> int:
    monkeypatch.setattr(
        sys, "argv", ["jsonl_to_json", str(input_path), str(output_path)]
    )
    return main()


def test_converts_jsonl_to_array(monkeypatch, tmp_path, capsys):
    src = tmp_path / "details.jsonl"
    src.write_text(
        '{"MS名": "ガンダム_LV1"}\n\n{"MS名": "ジム_LV1"}\n',
        encoding="utf-8",
    )
    out = tmp_path / "nested" / "details.json"

    rc = _run(monkeypatch, src, out)

    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8")) == [
        {"MS名": "ガンダム_LV1"},
        {"MS名": "ジム_LV1"},
    ]
    assert "Converted 2 records" in capsys.readouterr().out


def test_skips_invalid_json_lines(monkeypatch, tmp_path, capsys):
    src = tmp_path / "details.jsonl"
    src.write_text(
        '{"ok": 1}\n{broken json}\n{"ok": 2}\n',
        encoding="utf-8",
    )
    out = tmp_path / "details.json"

    rc = _run(monkeypatch, src, out)

    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8")) == [{"ok": 1}, {"ok": 2}]
    captured = capsys.readouterr()
    assert "Warning: 行 2 のJSON解析に失敗しました" in captured.err


def test_missing_input_returns_error(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path / "missing.jsonl", tmp_path / "out.json")

    assert rc == 1
    assert "入力ファイルが見つかりません" in capsys.readouterr().err
