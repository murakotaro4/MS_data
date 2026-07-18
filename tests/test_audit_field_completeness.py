import json
from pathlib import Path

import pytest

from ms_data.audit import audit_field_completeness


def _record(name: str = "テスト機_LV1") -> dict[str, object]:
    record: dict[str, object] = {
        field: 1 for field in audit_field_completeness.REQUIRED_KEYS
    }
    record.update(
        {
            "MS名": name,
            "レアリティ": "☆",
            "必要階級": "二等兵01",
            "格闘判定力": "中",
            "旋回_地上_通常時": 60,
        }
    )
    return record


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _run(
    tmp_path: Path,
    records: list[dict[str, object]],
    *,
    entries: list[dict[str, str]] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[int, Path]:
    msdata = tmp_path / "msData.json"
    allowlist = tmp_path / "allowlist.json"
    report = tmp_path / "report.md"
    _write_json(msdata, records)
    _write_json(allowlist, {"version": 1, "entries": entries or []})
    code = audit_field_completeness.main(
        [
            "--msdata",
            str(msdata),
            "--allowlist",
            str(allowlist),
            "--out",
            str(report),
            "--today",
            "2026-07-18",
            *(extra_args or []),
        ]
    )
    return code, report


def _entry(
    name: str = "テスト機_LV1",
    field: str = "レアリティ",
    review_after: str = "2026-10-16",
) -> dict[str, str]:
    return {
        "MS名": name,
        "field": field,
        "reason": "wiki未記載",
        "review_after": review_after,
    }


def test_detects_missing_required_key(tmp_path: Path):
    record = _record()
    del record["HP"]

    code, report = _run(tmp_path, [record])

    assert code == 0
    assert "- missing_key: 1" in report.read_text(encoding="utf-8")
    assert "| テスト機_LV1 | HP | missing_key |" in report.read_text(encoding="utf-8")


@pytest.mark.parametrize("field", ["属性", "コスト"])
def test_detects_missing_additional_required_key(tmp_path: Path, field: str):
    record = _record()
    del record[field]

    _, report = _run(tmp_path, [record])

    text = report.read_text(encoding="utf-8")
    assert "- missing_key: 1" in text
    assert f"| テスト機_LV1 | {field} | missing_key |" in text


def test_detects_empty_rarity(tmp_path: Path):
    record = _record()
    record["レアリティ"] = ""

    _, report = _run(tmp_path, [record])

    assert "- empty_value: 1" in report.read_text(encoding="utf-8")


def test_detects_empty_counter(tmp_path: Path):
    record = _record()
    record["カウンター"] = ""

    _, report = _run(tmp_path, [record])

    text = report.read_text(encoding="utf-8")
    assert "- empty_value: 1" in text
    assert "| テスト機_LV1 | カウンター | empty_value |" in text


@pytest.mark.parametrize("rank_value", ["", None])
def test_empty_rank_without_dp_is_allowed(tmp_path: Path, rank_value: object):
    record = _record()
    record["必要階級"] = rank_value

    _, report = _run(tmp_path, [record])

    text = report.read_text(encoding="utf-8")
    assert "- missing_key: 0" in text
    assert "- empty_value: 0" in text


def test_missing_rank_without_dp_is_allowed(tmp_path: Path):
    record = _record()
    del record["必要階級"]

    _, report = _run(tmp_path, [record])

    assert "- missing_key: 0" in report.read_text(encoding="utf-8")


def test_empty_rank_with_dp_is_detected(tmp_path: Path):
    record = _record()
    record["必要階級"] = ""
    record["必要DP"] = 1000

    _, report = _run(tmp_path, [record])

    assert "| テスト機_LV1 | 必要階級 | empty_value |" in report.read_text(
        encoding="utf-8"
    )


def test_turn_pair_accepts_one_side_and_detects_both_missing(tmp_path: Path):
    one_side = _record("片側あり_LV1")
    neither = _record("両側なし_LV1")
    del neither["旋回_地上_通常時"]

    _, report = _run(tmp_path, [one_side, neither])

    text = report.read_text(encoding="utf-8")
    assert "- pair_missing: 1" in text
    assert "| 両側なし_LV1 | 旋回_地上_通常時 / 旋回_宇宙_通常時 |" in text
    assert "| 片側あり_LV1 | 旋回_地上_通常時 |" not in text


def test_transform_fields_are_ignored(tmp_path: Path):
    record = _record()
    record["旋回_地上_変形時"] = ""
    record["スピード_変身時"] = None

    _, report = _run(tmp_path, [record])

    text = report.read_text(encoding="utf-8")
    assert "_変形時" not in text
    assert "_変身時" not in text


def test_allowlist_match_is_suppressed_before_rank_exception(tmp_path: Path):
    record = _record()
    del record["必要階級"]

    _, report = _run(tmp_path, [record], entries=[_entry(field="必要階級")])

    text = report.read_text(encoding="utf-8")
    assert "- missing_key: 0" in text
    assert "- suppressed: 1" in text
    assert "| テスト機_LV1 | 必要階級 | suppressed |" in text


def test_expired_entry_is_warning_even_without_current_finding(tmp_path: Path):
    _, report = _run(
        tmp_path,
        [_record()],
        entries=[_entry(review_after="2026-07-18")],
    )

    text = report.read_text(encoding="utf-8")
    assert "- expired: 1" in text
    assert "| テスト機_LV1 | レアリティ | expired |" in text


def test_fail_on_findings_excludes_suppressed(tmp_path: Path):
    missing = _record()
    del missing["HP"]
    code, _ = _run(tmp_path, [missing], extra_args=["--fail-on-findings"])
    assert code == 1

    suppressed = _record()
    suppressed["レアリティ"] = ""
    code, _ = _run(
        tmp_path,
        [suppressed],
        entries=[_entry()],
        extra_args=["--fail-on-findings"],
    )
    assert code == 0


@pytest.mark.parametrize(
    "entries",
    [
        [_entry(), _entry()],
        [_entry(review_after="2026-02-30")],
    ],
)
def test_allowlist_configuration_error_returns_two(
    tmp_path: Path, entries: list[dict[str, str]]
):
    code, report = _run(tmp_path, [_record()], entries=entries)

    assert code == 2
    assert not report.exists()


def test_writes_github_output_and_step_summary(tmp_path: Path):
    record = _record()
    del record["HP"]
    github_output = tmp_path / "github-output.txt"
    step_summary = tmp_path / "step-summary.md"

    code, _ = _run(
        tmp_path,
        [record],
        extra_args=[
            "--github-output",
            str(github_output),
            "--step-summary",
            str(step_summary),
        ],
    )

    assert code == 0
    output_text = github_output.read_text(encoding="utf-8")
    assert "field_completeness_findings=1" in output_text
    assert "field_completeness_missing_key=1" in output_text
    summary_text = step_summary.read_text(encoding="utf-8")
    assert "### フィールド充足率監査" in summary_text
    assert "- findings: 1" in summary_text


def test_report_contains_required_headings(tmp_path: Path):
    _, report = _run(tmp_path, [_record()])

    text = report.read_text(encoding="utf-8")
    assert "# フィールド充足率監査" in text
    assert "## サマリ" in text
    for category in audit_field_completeness.CATEGORIES:
        assert f"- {category}: 0" in text
        assert f"## {category}" in text
        assert "| なし |" in text
