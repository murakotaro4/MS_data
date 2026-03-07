import argparse
import json
from pathlib import Path

import scripts.scrape_msdata as sm


def test_parse_index_extracts_updated_age_metadata():
    html = """
    <html><body>
      <div id="menu_hanyou">
        <h4>100</h4>
        <ul>
          <li><a href="//w.atwiki.jp/battle-operation2/pages/343.html" title="ザクⅡ (12h)">ザクⅡ</a></li>
          <li><a href="//w.atwiki.jp/battle-operation2/pages/341.html">ジム</a></li>
        </ul>
      </div>
    </body></html>
    """

    items = sm.parse_index(html)

    assert items == [
        {
            "name": "ザクⅡ",
            "url": "https://w.atwiki.jp/battle-operation2/pages/343.html",
            "page_id": 343,
            "cost": 100,
            "属性": "汎用",
            "updated_age_text": "12h",
            "updated_age_seconds": 12 * 3600,
        },
        {
            "name": "ジム",
            "url": "https://w.atwiki.jp/battle-operation2/pages/341.html",
            "page_id": 341,
            "cost": 100,
            "属性": "汎用",
            "updated_age_text": None,
            "updated_age_seconds": None,
        },
    ]


def test_parse_iso_datetime_assumes_utc_for_naive_timestamp():
    parsed = sm.parse_iso_datetime("2026-03-05T14:47:11")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_cmd_detect_changed_selects_recent_and_mismatched_records(tmp_path: Path):
    index_path = tmp_path / "cache/index.json"
    out_path = tmp_path / "cache/index_changed.json"
    meta_path = tmp_path / "cache/index_changed_meta.json"
    reports_dir = tmp_path / "reports"
    msdata_path = tmp_path / "msData.json"

    _write_json(
        index_path,
        [
            {
                "name": "旧機体",
                "url": "https://w.atwiki.jp/battle-operation2/pages/100.html",
                "cost": 300,
                "属性": "汎用",
                "updated_age_text": "103d",
                "updated_age_seconds": 103 * 86400,
            },
            {
                "name": "最近更新機",
                "url": "https://w.atwiki.jp/battle-operation2/pages/101.html",
                "cost": 350,
                "属性": "汎用",
                "updated_age_text": "1d",
                "updated_age_seconds": 86400,
            },
            {
                "name": "コスト変更機",
                "url": "https://w.atwiki.jp/battle-operation2/pages/102.html",
                "cost": 500,
                "属性": "強襲",
                "updated_age_text": "103d",
                "updated_age_seconds": 103 * 86400,
            },
            {
                "name": "新規機体",
                "url": "https://w.atwiki.jp/battle-operation2/pages/103.html",
                "cost": 550,
                "属性": "支援",
                "updated_age_text": "103d",
                "updated_age_seconds": 103 * 86400,
            },
        ],
    )
    _write_json(
        msdata_path,
        [
            {
                "MS名": "旧機体_LV1",
                "コスト": 300,
                "属性": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/100.html",
            },
            {
                "MS名": "最近更新機_LV1",
                "コスト": 350,
                "属性": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/101.html",
            },
            {
                "MS名": "コスト変更機_LV1",
                "コスト": 450,
                "属性": "強襲",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/102.html",
            },
        ],
    )
    _write_json(
        reports_dir / "provenance_20260305.json",
        {"generated_at": "2026-03-05T14:47:11Z"},
    )

    rc = sm.cmd_detect_changed(
        argparse.Namespace(
            input=str(index_path),
            out=str(out_path),
            meta_out=str(meta_path),
            reports_dir=str(reports_dir),
            previous_provenance="",
            msdata=str(msdata_path),
            freshness_window="1h",
            min_age_coverage=0.95,
            force_full=False,
            now="2026-03-07T14:47:11Z",
        )
    )

    assert rc == 0

    selected = json.loads(out_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert [item["name"] for item in selected] == ["最近更新機", "コスト変更機", "新規機体"]
    assert meta["fast_path"] is True
    assert meta["fallback_reason"] == ""
    assert meta["candidate_count"] == 3
    assert meta["reason_counts"]["recent_update"] == 1
    assert meta["reason_counts"]["cost_changed"] == 1
    assert meta["reason_counts"]["new_name"] == 1


def test_cmd_detect_changed_falls_back_when_previous_provenance_is_missing(tmp_path: Path):
    index_path = tmp_path / "cache/index.json"
    out_path = tmp_path / "cache/index_changed.json"
    meta_path = tmp_path / "cache/index_changed_meta.json"
    msdata_path = tmp_path / "msData.json"

    _write_json(
        index_path,
        [
            {
                "name": "旧機体",
                "url": "https://w.atwiki.jp/battle-operation2/pages/100.html",
                "cost": 300,
                "属性": "汎用",
                "updated_age_text": "103d",
                "updated_age_seconds": 103 * 86400,
            },
            {
                "name": "最近更新機",
                "url": "https://w.atwiki.jp/battle-operation2/pages/101.html",
                "cost": 350,
                "属性": "汎用",
                "updated_age_text": "1d",
                "updated_age_seconds": 86400,
            },
        ],
    )
    _write_json(msdata_path, [])

    rc = sm.cmd_detect_changed(
        argparse.Namespace(
            input=str(index_path),
            out=str(out_path),
            meta_out=str(meta_path),
            reports_dir=str(tmp_path / "reports"),
            previous_provenance="",
            msdata=str(msdata_path),
            freshness_window="1h",
            min_age_coverage=0.95,
            force_full=False,
            now="2026-03-07T14:47:11Z",
        )
    )

    assert rc == 0
    selected = json.loads(out_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert len(selected) == 2
    assert meta["fast_path"] is False
    assert meta["fallback_reason"] == "missing_previous_provenance"


def test_cmd_detect_changed_falls_back_when_previous_provenance_is_invalid(
    tmp_path: Path,
):
    index_path = tmp_path / "cache/index.json"
    out_path = tmp_path / "cache/index_changed.json"
    meta_path = tmp_path / "cache/index_changed_meta.json"
    previous_provenance = tmp_path / "reports/provenance_20260305.json"
    msdata_path = tmp_path / "msData.json"

    _write_json(
        index_path,
        [
            {
                "name": "A",
                "url": "https://w.atwiki.jp/battle-operation2/pages/100.html",
                "cost": 300,
                "属性": "汎用",
                "updated_age_text": "1d",
                "updated_age_seconds": 86400,
            }
        ],
    )
    _write_json(msdata_path, [])
    previous_provenance.parent.mkdir(parents=True, exist_ok=True)
    previous_provenance.write_text("{invalid", encoding="utf-8")

    rc = sm.cmd_detect_changed(
        argparse.Namespace(
            input=str(index_path),
            out=str(out_path),
            meta_out=str(meta_path),
            reports_dir=str(tmp_path / "reports"),
            previous_provenance=str(previous_provenance),
            msdata=str(msdata_path),
            freshness_window="1h",
            min_age_coverage=0.95,
            force_full=False,
            now="2026-03-07T14:47:11Z",
        )
    )

    assert rc == 0
    selected = json.loads(out_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert len(selected) == 1
    assert meta["fast_path"] is False
    assert meta["fallback_reason"] == "missing_previous_provenance"


def test_cmd_detect_changed_falls_back_when_generated_at_is_invalid(tmp_path: Path):
    index_path = tmp_path / "cache/index.json"
    out_path = tmp_path / "cache/index_changed.json"
    meta_path = tmp_path / "cache/index_changed_meta.json"
    previous_provenance = tmp_path / "reports/provenance_20260305.json"
    msdata_path = tmp_path / "msData.json"

    _write_json(
        index_path,
        [
            {
                "name": "A",
                "url": "https://w.atwiki.jp/battle-operation2/pages/100.html",
                "cost": 300,
                "属性": "汎用",
                "updated_age_text": "1d",
                "updated_age_seconds": 86400,
            }
        ],
    )
    _write_json(msdata_path, [])
    _write_json(previous_provenance, {"generated_at": "bad timestamp"})

    rc = sm.cmd_detect_changed(
        argparse.Namespace(
            input=str(index_path),
            out=str(out_path),
            meta_out=str(meta_path),
            reports_dir=str(tmp_path / "reports"),
            previous_provenance=str(previous_provenance),
            msdata=str(msdata_path),
            freshness_window="1h",
            min_age_coverage=0.95,
            force_full=False,
            now="2026-03-07T14:47:11Z",
        )
    )

    assert rc == 0
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["fast_path"] is False
    assert meta["fallback_reason"] == "missing_previous_provenance"


def test_select_changed_index_items_falls_back_when_age_coverage_is_low():
    items = [
        {"name": "A", "updated_age_seconds": None},
        {"name": "B", "updated_age_seconds": None},
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=sm.parse_iso_datetime("2026-03-05T14:47:11Z"),
        previous_msdata_index={},
        now=sm.parse_iso_datetime("2026-03-07T14:47:11Z"),
        freshness_window_seconds=3600,
        min_age_coverage=0.95,
    )

    assert selected == items
    assert meta["fast_path"] is False
    assert meta["fallback_reason"] == "low_age_coverage"
