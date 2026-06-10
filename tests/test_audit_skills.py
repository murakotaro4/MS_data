"""audit_skills（skill_owners と msData の突合監査）のテスト。"""

import json
import sys

from ms_data.audit.audit_skills import main


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_main_reports_coverage_and_unknown_series(monkeypatch, tmp_path, capsys):
    owners = tmp_path / "skill_owners.json"
    _write_json(
        owners,
        {
            "owners": [
                {"series": "ガンダム", "base": [{"id": "exam"}, {"id": "boost"}]},
                {"series": "ジム", "base": [{"id": "exam"}]},
                # msData に存在しないシリーズ
                {"series": "謎の機体", "base": [{"id": "exam"}]},
                # series 空はスキップされる
                {"series": "", "base": [{"id": "exam"}]},
            ]
        },
    )
    msdata = tmp_path / "msData.json"
    _write_json(
        msdata,
        [
            {"MS名": "ガンダム_LV1"},
            {"MS名": "ガンダム_LV2"},
            {"MS名": "ジム_LV1"},
            # owners に無いシリーズ（カバレッジ対象外）
            {"MS名": "ザク_LV1"},
            # MS名なしはスキップされる
            {"コスト": 300},
        ],
    )
    out = tmp_path / "audit.md"  # 既定の reports/ に書かないよう必ず --out を渡す
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_skills",
            "--owners",
            str(owners),
            "--msdata",
            str(msdata),
            "--out",
            str(out),
        ],
    )

    rc = main()

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "- msData records: 4" in text
    assert "- covered (series match): 3" in text
    assert "- unknown series (owners not in msData): 1" in text
    assert "## Unknown series" in text
    assert "- 謎の機体" in text
    assert "- exam: 3" in text
    assert "- boost: 1" in text
    assert f"audit: wrote {out}" in capsys.readouterr().out
