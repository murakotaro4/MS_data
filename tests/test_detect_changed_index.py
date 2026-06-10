import argparse
import json
from pathlib import Path

import ms_data.scraping.scrape_msdata as sm


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


def test_parse_index_includes_steam_limited_entries():
    html = """
    <html><body>
      <div id="menu_hanyou">
        <h4>700</h4>
        <ul>
          <li><a href="//w.atwiki.jp/battle-operation2/pages/6994.html">ウイングガンダムゼロ【EW】</a></li>
        </ul>
      </div>
      <div id="menu_etc">
        <h3>Steam版限定</h3>
        <ul>
          <li><a href="//w.atwiki.jp/battle-operation2/pages/5529.html" title="フリーダムガンダム (43d)">フリーダムガンダム</a></li>
          <li><a href="//w.atwiki.jp/battle-operation2/pages/6180.html" title="ゴッドガンダム (3d)">ゴッドガンダム</a></li>
          <li><a href="//w.atwiki.jp/battle-operation2/pages/6603.html" title="ウイングガンダムゼロ (59d)">ウイングガンダムゼロ</a></li>
        </ul>
      </div>
    </body></html>
    """

    items = sm.parse_index(html)

    assert [item["name"] for item in items] == [
        "ウイングガンダムゼロ【EW】",
        "フリーダムガンダム",
        "ゴッドガンダム",
        "ウイングガンダムゼロ",
    ]
    assert items[1]["url"] == "https://w.atwiki.jp/battle-operation2/pages/5529.html"
    assert items[1]["cost"] is None
    assert items[1]["属性"] is None
    assert items[1]["updated_age_text"] == "43d"
    assert items[1]["updated_age_seconds"] == 43 * 86400


def test_parse_iso_datetime_assumes_utc_for_naive_timestamp():
    parsed = sm.parse_iso_datetime("2026-03-05T14:47:11")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_select_changed_index_items_ignores_unknown_cost_and_attr():
    items = [
        {
            "name": "フリーダムガンダム",
            "url": "https://w.atwiki.jp/battle-operation2/pages/5529.html",
            "cost": None,
            "属性": None,
            "updated_age_text": "43d",
            "updated_age_seconds": 43 * 86400,
        }
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=sm.parse_iso_datetime("2026-04-11T09:00:00Z"),
        previous_msdata_index={
            "フリーダムガンダム": {
                "cost": 700,
                "attr": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/5529.html",
            }
        },
        now=sm.parse_iso_datetime("2026-04-12T09:00:00Z"),
        freshness_window_seconds=3600,
        min_age_coverage=0.95,
    )

    assert selected == []
    assert meta["candidate_count"] == 0
    assert meta["reason_counts"] == {}


def test_select_changed_index_items_selects_stale_detail_cache():
    items = [
        {
            "name": "ギャプランTR-5",
            "url": "https://w.atwiki.jp/battle-operation2/pages/5254.html",
            "cost": 500,
            "属性": "汎用",
            "updated_age_text": "30d",
            "updated_age_seconds": 30 * 86400,
        }
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=sm.parse_iso_datetime("2026-04-20T09:00:00Z"),
        previous_msdata_index={
            "ギャプランTR-5": {
                "cost": 500,
                "attr": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/5254.html",
            }
        },
        now=sm.parse_iso_datetime("2026-04-23T09:00:00Z"),
        freshness_window_seconds=3600,
        min_age_coverage=0.95,
        detail_fetch_state={
            "https://w.atwiki.jp/battle-operation2/pages/5254.html": {
                "fetched_at": "2026-04-01T09:00:00Z"
            }
        },
        stale_detail_seconds=14 * 86400,
    )

    assert [item["name"] for item in selected] == ["ギャプランTR-5"]
    assert selected[0]["change_reasons"] == ["stale_detail_cache"]
    assert meta["candidate_count"] == 1
    assert meta["reason_counts"] == {"stale_detail_cache": 1}


def test_select_changed_index_items_ignores_fresh_detail_cache():
    items = [
        {
            "name": "ギャプランTR-5",
            "url": "https://w.atwiki.jp/battle-operation2/pages/5254.html",
            "cost": 500,
            "属性": "汎用",
            "updated_age_text": "30d",
            "updated_age_seconds": 30 * 86400,
        }
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=sm.parse_iso_datetime("2026-04-20T09:00:00Z"),
        previous_msdata_index={
            "ギャプランTR-5": {
                "cost": 500,
                "attr": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/5254.html",
            }
        },
        now=sm.parse_iso_datetime("2026-04-23T09:00:00Z"),
        freshness_window_seconds=3600,
        min_age_coverage=0.95,
        detail_fetch_state={
            "https://w.atwiki.jp/battle-operation2/pages/5254.html": {
                "fetched_at": "2026-04-20T09:00:00Z"
            }
        },
        stale_detail_seconds=14 * 86400,
    )

    assert selected == []
    assert meta["candidate_count"] == 0
    assert meta["reason_counts"] == {}


def test_select_changed_index_items_selects_missing_detail_fetch_history():
    items = [
        {
            "name": "ギャプランTR-5",
            "url": "https://w.atwiki.jp/battle-operation2/pages/5254.html",
            "cost": 500,
            "属性": "汎用",
            "updated_age_text": "30d",
            "updated_age_seconds": 30 * 86400,
        }
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=sm.parse_iso_datetime("2026-04-20T09:00:00Z"),
        previous_msdata_index={
            "ギャプランTR-5": {
                "cost": 500,
                "attr": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/5254.html",
            }
        },
        now=sm.parse_iso_datetime("2026-04-23T09:00:00Z"),
        freshness_window_seconds=3600,
        min_age_coverage=0.95,
        detail_fetch_state={},
        stale_detail_seconds=14 * 86400,
    )

    assert [item["name"] for item in selected] == ["ギャプランTR-5"]
    assert selected[0]["change_reasons"] == ["stale_detail_cache"]


def test_select_changed_index_items_force_full_selects_all_with_stale_enabled():
    items = [
        {"name": "A", "url": "https://w.atwiki.jp/battle-operation2/pages/1.html"},
        {"name": "B", "url": "https://w.atwiki.jp/battle-operation2/pages/2.html"},
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=sm.parse_iso_datetime("2026-04-20T09:00:00Z"),
        previous_msdata_index={},
        now=sm.parse_iso_datetime("2026-04-23T09:00:00Z"),
        force_full=True,
        detail_fetch_state={},
        stale_detail_seconds=14 * 86400,
    )

    assert selected == items
    assert meta["fast_path"] is False
    assert meta["fallback_reason"] == "force_full"
    assert meta["candidate_count"] == 2


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

    assert [item["name"] for item in selected] == [
        "最近更新機",
        "コスト変更機",
        "新規機体",
    ]
    assert meta["fast_path"] is True
    assert meta["fallback_reason"] == ""
    assert meta["candidate_count"] == 3
    assert meta["reason_counts"]["recent_update"] == 1
    assert meta["reason_counts"]["cost_changed"] == 1
    assert meta["reason_counts"]["new_name"] == 1


def test_cmd_detect_changed_falls_back_when_previous_provenance_is_missing(
    tmp_path: Path,
):
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


def test_select_changed_index_items_revalidate_selects_updated_since_fetch():
    items = [
        {
            # 前回取得（5日前）より後に更新（2日前）→ 再取得対象
            "name": "更新済み機",
            "url": "https://w.atwiki.jp/battle-operation2/pages/1.html",
            "cost": 300,
            "属性": "汎用",
            "updated_age_text": "2d",
            "updated_age_seconds": 2 * 86400,
        },
        {
            # 前回取得（5日前）より前の更新（30日前）→ スキップ
            "name": "未更新機",
            "url": "https://w.atwiki.jp/battle-operation2/pages/2.html",
            "cost": 300,
            "属性": "汎用",
            "updated_age_text": "30d",
            "updated_age_seconds": 30 * 86400,
        },
        {
            # 取得履歴なし（前回失敗 or 新規）→ 再取得対象
            "name": "取得履歴なし機",
            "url": "https://w.atwiki.jp/battle-operation2/pages/3.html",
            "cost": 300,
            "属性": "汎用",
            "updated_age_text": "30d",
            "updated_age_seconds": 30 * 86400,
        },
    ]
    msdata_index = {
        name: {
            "cost": 300,
            "attr": "汎用",
            "wiki_url": f"https://w.atwiki.jp/battle-operation2/pages/{i}.html",
        }
        for i, name in enumerate(["更新済み機", "未更新機", "取得履歴なし機"], start=1)
    }

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=None,  # 前回プロビナンスに依存しない
        previous_msdata_index=msdata_index,
        now=sm.parse_iso_datetime("2026-06-11T09:00:00Z"),
        revalidate=True,
        min_age_coverage=0.95,
        detail_fetch_state={
            "https://w.atwiki.jp/battle-operation2/pages/1.html": {
                "fetched_at": "2026-06-06T09:00:00Z"
            },
            "https://w.atwiki.jp/battle-operation2/pages/2.html": {
                "fetched_at": "2026-06-06T09:00:00Z"
            },
        },
    )

    assert [item["name"] for item in selected] == ["更新済み機", "取得履歴なし機"]
    assert selected[0]["change_reasons"] == ["updated_since_fetch"]
    assert selected[1]["change_reasons"] == ["missing_fetch_history"]
    assert meta["mode"] == "revalidate"
    assert meta["fast_path"] is False
    assert meta["fallback_reason"] == "revalidate"
    assert meta["candidate_count"] == 2
    assert meta["reason_counts"] == {
        "updated_since_fetch": 1,
        "missing_fetch_history": 1,
    }


def test_select_changed_index_items_revalidate_falls_back_on_low_age_coverage():
    items = [
        {"name": "A", "url": "https://example.test/1", "updated_age_seconds": None},
        {"name": "B", "url": "https://example.test/2", "updated_age_seconds": None},
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=None,
        previous_msdata_index={},
        now=sm.parse_iso_datetime("2026-06-11T09:00:00Z"),
        revalidate=True,
        min_age_coverage=0.95,
        detail_fetch_state={},
    )

    assert selected == items
    assert meta["fast_path"] is False
    assert meta["fallback_reason"] == "low_age_coverage"
    assert meta["candidate_count"] == 2


def test_select_changed_index_items_revalidate_keeps_identity_checks():
    items = [
        {
            "name": "コスト変更機",
            "url": "https://w.atwiki.jp/battle-operation2/pages/1.html",
            "cost": 500,
            "属性": "汎用",
            "updated_age_text": "30d",
            "updated_age_seconds": 30 * 86400,
        },
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=None,
        previous_msdata_index={
            "コスト変更機": {
                "cost": 450,
                "attr": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/1.html",
            }
        },
        now=sm.parse_iso_datetime("2026-06-11T09:00:00Z"),
        revalidate=True,
        min_age_coverage=0.95,
        detail_fetch_state={
            "https://w.atwiki.jp/battle-operation2/pages/1.html": {
                "fetched_at": "2026-06-10T09:00:00Z"
            }
        },
    )

    assert [item["name"] for item in selected] == ["コスト変更機"]
    assert selected[0]["change_reasons"] == ["cost_changed"]
    assert meta["reason_counts"] == {"cost_changed": 1}


def test_cmd_detect_changed_revalidate_mode(tmp_path: Path):
    index_path = tmp_path / "cache/index.json"
    out_path = tmp_path / "cache/index_changed.json"
    meta_path = tmp_path / "cache/index_changed_meta.json"
    msdata_path = tmp_path / "msData.json"
    detail_state_path = tmp_path / "cache/detail_fetch_state.json"

    _write_json(
        index_path,
        [
            {
                "name": "更新済み機",
                "url": "https://w.atwiki.jp/battle-operation2/pages/1.html",
                "cost": 300,
                "属性": "汎用",
                "updated_age_text": "1d",
                "updated_age_seconds": 86400,
            },
            {
                "name": "未更新機",
                "url": "https://w.atwiki.jp/battle-operation2/pages/2.html",
                "cost": 300,
                "属性": "汎用",
                "updated_age_text": "60d",
                "updated_age_seconds": 60 * 86400,
            },
        ],
    )
    _write_json(
        msdata_path,
        [
            {
                "MS名": "更新済み機_LV1",
                "コスト": 300,
                "属性": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/1.html",
            },
            {
                "MS名": "未更新機_LV1",
                "コスト": 300,
                "属性": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/2.html",
            },
        ],
    )
    _write_json(
        detail_state_path,
        {
            "items": {
                "https://w.atwiki.jp/battle-operation2/pages/1.html": {
                    "fetched_at": "2026-06-01T09:00:00Z"
                },
                "https://w.atwiki.jp/battle-operation2/pages/2.html": {
                    "fetched_at": "2026-06-01T09:00:00Z"
                },
            }
        },
    )

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
            revalidate=True,
            detail_fetch_state=str(detail_state_path),
            now="2026-06-11T09:00:00Z",
        )
    )

    assert rc == 0
    selected = json.loads(out_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert [item["name"] for item in selected] == ["更新済み機"]
    assert meta["mode"] == "revalidate"
    assert meta["fallback_reason"] == "revalidate"
    assert meta["candidate_count"] == 1


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


def test_select_changed_index_items_revalidate_does_not_double_count_missing_history():
    items = [
        {
            "name": "取得履歴なし機",
            "url": "https://w.atwiki.jp/battle-operation2/pages/1.html",
            "cost": 300,
            "属性": "汎用",
            "updated_age_text": "30d",
            "updated_age_seconds": 30 * 86400,
        }
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=None,
        previous_msdata_index={
            "取得履歴なし機": {
                "cost": 300,
                "attr": "汎用",
                "wiki_url": "https://w.atwiki.jp/battle-operation2/pages/1.html",
            }
        },
        now=sm.parse_iso_datetime("2026-06-11T09:00:00Z"),
        revalidate=True,
        min_age_coverage=0.95,
        detail_fetch_state={},
        stale_detail_seconds=40 * 86400,  # 本番同様 stale 判定が有効でも二重計上しない
    )

    assert [item["name"] for item in selected] == ["取得履歴なし機"]
    assert selected[0]["change_reasons"] == ["missing_fetch_history"]
    assert meta["reason_counts"] == {"missing_fetch_history": 1}


def test_select_changed_index_items_force_full_wins_over_revalidate():
    items = [
        {"name": "A", "url": "https://example.test/1", "updated_age_seconds": 86400},
    ]

    selected, meta = sm.select_changed_index_items(
        items,
        previous_generated_at=None,
        previous_msdata_index={},
        now=sm.parse_iso_datetime("2026-06-11T09:00:00Z"),
        force_full=True,
        revalidate=True,
        detail_fetch_state={},
    )

    assert selected == items
    assert meta["mode"] == "full"
    assert meta["fallback_reason"] == "force_full"
    assert meta["candidate_count"] == 1
