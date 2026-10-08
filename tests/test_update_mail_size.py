from collections import Counter
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ms_data.audit.audit_official_overrides import render_markdown
from ms_data.audit.source_slots import empty_audit
from ms_data.audit.source_slots import render_markdown as render_source
from ms_data.reporting.build_update_mail_body import _audit_lines, main
from ms_data.reporting.update_mail_display import MAX_HTML_BYTES
from ms_data.reporting.update_mail_html import prepare_update_mail
from ms_data.reporting.update_mail_model import build_mail_view, localize_mail_body


def _body(report: str) -> str:
    return (
        "- 実行日: 20261008\n- 結果: 成功（差分なし）\n- msData.json変更: false\n"
        + report
    )


def _override_rows(count: int, *, lifecycle: str = "active") -> list[dict]:
    return [
        {
            "MS名": f"表示確認機{i}_LV2",
            "field": "中スロット",
            "status": "protected_by_override",
            "before": 22,
            "raw": 12,
            "current": 22,
            "override": 22,
            "stale": 12,
            "lifecycle": lifecycle,
            "review_after": "2026-10-01",
            "remove_after": "2026-10-08",
            "evidence_status": "mismatch",
            "url": "https://example.test/wiki",
            "attempted_at": "2026-10-08T09:00:00+00:00",
            "fetched_at": "2026-10-08T09:00:01+00:00",
            "http_status": 200,
        }
        for i in range(count)
    ]


def _override_body(rows: list[dict]) -> str:
    report = render_markdown(
        rows,
        Counter(row["status"] for row in rows),
        Counter(row["lifecycle"] for row in rows),
    )
    for source, destination in (
        ("サマリ", "official_overrides監査"),
        ("取得証拠", "登録補正 / 取得証拠"),
        ("適用中", "登録補正 / 適用中"),
        ("要確認", "登録補正 / 要確認"),
        ("期限確認", "登録補正 / 期限確認"),
        ("撤去候補", "登録補正 / 撤去候補"),
    ):
        report = report.replace(f"## {source}", f"## {destination}")
    # CLIが監査の既存説明を除き、表とサマリを残す形を使う。
    lines = [
        line for line in report.splitlines() if line.startswith(("## ", "|", "- "))
    ]
    return _body("\n".join(lines))


@pytest.mark.parametrize(
    "path",
    [
        "tests/fixtures/reports/official_overrides_audit_20260601.md",
        "reports/2026/09/official_overrides_audit_20260918.md",
    ],
)
def test_historical_large_audits_fit_and_keep_every_target(
    tmp_path: Path, path: str
) -> None:
    plain, html = tmp_path / "body.txt", tmp_path / "body.html"
    main(
        [
            "--report-date",
            "20261008",
            "--result",
            "成功（差分なし）",
            "--changed",
            "false",
            "--official-overrides-audit-path",
            path,
            "--detail-url",
            "https://example.test/full",
            "--out",
            str(plain),
            "--html-out",
            str(html),
        ]
    )
    data = html.read_bytes()
    soup = BeautifulSoup(data, "html.parser")
    raw = build_mail_view(
        _body("\n".join(_audit_lines(Path(path), "official_overrides監査", "登録補正")))
    )
    for card in [*raw.attention, *raw.maintenance, *raw.evidence]:
        if card.target:
            assert card.title in soup.get_text()
            assert card.title in plain.read_text(encoding="utf-8")
    assert len(data) <= MAX_HTML_BYTES
    assert soup.find("a").find_next("div", class_="warning") is not None
    assert "共通の説明をまとめて" in plain.read_text(encoding="utf-8")


@pytest.mark.parametrize("lifecycle", ["active", "review_due", "remove_due"])
def test_large_current_producer_retains_status_and_shared_selection(
    lifecycle: str,
) -> None:
    body = (
        _override_body(_override_rows(160, lifecycle=lifecycle))
        + "\n詳細: https://example.test/full\n"
    )
    original = build_mail_view(body)
    selected, html = prepare_update_mail(body)
    text = localize_mail_body(body)
    assert len(html.encode("utf-8")) <= MAX_HTML_BYTES
    assert selected.condensed
    assert bool(selected.attention) == bool(original.attention)
    assert (
        "要確認の項目なし" in text
        if lifecycle == "active"
        else "対応が必要です" in text
    )
    soup = BeautifulSoup(html, "html.parser")
    for card in [*selected.attention, *selected.maintenance, *selected.evidence]:
        if card.target:
            assert card.title in text and card.title in soup.get_text()
    for notice in selected.notices:
        assert notice in text and notice in soup.get_text()
    assert "160項目" in text


def test_many_partial_holds_keep_reason_action_and_omission_count() -> None:
    audit = empty_audit()
    audit.update(status="partial_hold", held_record_count=800)
    audit["findings"] = [
        {
            "MS名": f"保留確認機{i}_LV2",
            "level": 2,
            "field": "中スロット",
            "observed": 12,
            "comparison": 20,
            "previous": 22,
            "adopted": 22,
            "action": "retained_previous",
            "wiki_url": "https://example.test/wiki",
            "reason": "LV内点の谷／数値低下を確認",
        }
        for i in range(800)
    ]
    body = _body(render_source(audit)) + "\n詳細: https://example.test/full\n"
    selected, html = prepare_update_mail(body)
    text = localize_mail_body(body, view=selected)
    assert len(html.encode("utf-8")) <= MAX_HTML_BYTES
    assert "LV単位の部分保留: 800レコード" in text
    assert "LV内点の谷／数値低下を確認" in text
    assert "機体＋LV全体" in text
    assert "要確認の詳細を本文に載せない対象" in text
    assert "機体＋LV＋項目" in text
    assert "保留確認機0_LV2" in text
    assert "LV単位の部分保留: 800項目" not in text


def test_long_japanese_and_url_keep_well_formed_bounded_mail() -> None:
    body = _override_body(_override_rows(1, lifecycle="remove_due"))
    body = body.replace("表示確認機0_LV2", "長い名称" * 10000 + "_LV2")
    body += "\n詳細: https://example.test/" + "長いURL" * 10000 + "\n"
    selected, html = prepare_update_mail(body)
    text = localize_mail_body(body, view=selected)
    assert len(html.encode("utf-8")) <= MAX_HTML_BYTES
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one(".action").get_text().startswith("対応が必要です")
    assert soup.body is not None and soup.html is not None
    assert "完全版の確認リンクなし" in text
    assert "長すぎる確認URL" in text
    assert "存続・撤去を判断してください" in text
    assert soup.select("a") == []


def test_real_repository_and_run_metadata_provide_front_confirmation_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "murakotaro4/MS_data")
    plain, html = tmp_path / "body.txt", tmp_path / "body.html"
    main(
        [
            "--report-date",
            "20261008",
            "--result",
            "成功（差分なし）",
            "--changed",
            "false",
            "--run-id",
            "37649017623",
            "--out",
            str(plain),
            "--html-out",
            str(html),
        ]
    )
    soup = BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser")
    assert (
        soup.find("a")["href"]
        == "https://github.com/murakotaro4/MS_data/actions/runs/37649017623"
    )
    assert "詳細レポート:" in plain.read_text(encoding="utf-8")


def test_oversized_unknown_sections_keep_needed_action_and_real_link() -> None:
    body = _override_body(_override_rows(1, lifecycle="remove_due"))
    body += "\n" + "\n".join(
        f"## 未知の補足{i}\n" + "長い補足" * 300 for i in range(150)
    )
    body += "\n詳細: https://example.test/full\n"
    selected, html = prepare_update_mail(body)
    text = localize_mail_body(body, view=selected)
    assert len(html.encode("utf-8")) <= MAX_HTML_BYTES
    assert "対応が必要です" in text
    assert "存続・撤去を判断してください" in text
    assert "本文は結果の要約です" in text
    assert BeautifulSoup(html, "html.parser").find("a")["href"] == (
        "https://example.test/full"
    )


@pytest.mark.parametrize("repository", ["", "invalid repo", "a/b/c"])
def test_missing_or_invalid_repository_does_not_invent_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository: str
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    html = tmp_path / "body.html"
    main(
        [
            "--report-date",
            "20261008",
            "--result",
            "成功（差分なし）",
            "--changed",
            "false",
            "--run-id",
            "123",
            "--out",
            str(tmp_path / "body.txt"),
            "--html-out",
            str(html),
        ]
    )
    assert (
        BeautifulSoup(html.read_text(encoding="utf-8"), "html.parser").find("a") is None
    )
