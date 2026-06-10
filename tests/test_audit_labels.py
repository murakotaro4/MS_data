"""audit_labels（ラベル揺らぎ監査）のテスト。"""

import json

from ms_data.audit.audit_labels import analyze, main
from ms_data.core.labels import FIELD_MAP

# FIELD_MAP の中身に依存しないよう既知ラベルは実行時に取得する
KNOWN_LABEL = next(iter(FIELD_MAP))


def test_analyze_counts_and_flags_unknown():
    records = [
        {
            "raw_labels": ["機体  HP", KNOWN_LABEL],
            "normalized_labels": [KNOWN_LABEL, "謎ラベル"],
        },
        {
            "raw_labels": [KNOWN_LABEL],
            "normalized_labels": [KNOWN_LABEL, "謎ラベル"],
        },
    ]

    stats = analyze(records)

    assert stats.pages == 2
    # clean_text により連続空白は1つに圧縮される
    assert stats.raw_counts["機体 HP"] == 1
    assert stats.norm_counts[KNOWN_LABEL] == 2
    assert stats.unknown_norm["謎ラベル"] == 2
    assert KNOWN_LABEL not in stats.unknown_norm


def test_analyze_excludes_role_labels():
    records = [{"raw_labels": [], "normalized_labels": ["汎用", "強襲", "支援"]}]

    stats = analyze(records)

    assert stats.norm_counts == {}
    assert stats.unknown_norm == {}


def test_main_writes_report_skipping_broken_lines(tmp_path, capsys):
    src = tmp_path / "labels_raw.jsonl"
    valid_line = json.dumps(
        {
            "raw_labels": [KNOWN_LABEL],
            "normalized_labels": [KNOWN_LABEL, "謎ラベル"],
        },
        ensure_ascii=False,
    )
    src.write_text("\n".join([valid_line, "{broken json}", ""]), encoding="utf-8")
    out = tmp_path / "label_audit.md"

    rc = main(["--in", str(src), "--out", str(out)])

    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "# ラベル揺らぎ監査レポート" in text
    assert "- ページ数: 1" in text
    assert f"- {KNOWN_LABEL} | 1 | OK" in text
    assert "## 未対応ラベル一覧" in text
    assert "- 謎ラベル (1)" in text
    assert "report: pages=1" in capsys.readouterr().out
