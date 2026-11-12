"""scrape_msdata の index / labels サブコマンドのテスト（ネットワークは MockTransport）。"""

import json
from pathlib import Path

import httpx
import pytest

import ms_data.scraping.scrape_msdata as sm

INDEX_HTML = """
<html><body>
  <div id="menu_hanyou">
    <h4>300</h4>
    <ul>
      <li><a href="/battle-operation2/pages/101.html" title="ジム (1日前)">ジム</a></li>
      <li><a href="/battle-operation2/pages/102.html">陸戦型ジム</a></li>
    </ul>
  </div>
  <div id="menu_sien">
    <h4>350</h4>
    <ul>
      <li><a href="/battle-operation2/pages/201.html">ジム・キャノン</a></li>
    </ul>
  </div>
</body></html>
"""


def _detail_html(title: str, rows: list[str]) -> str:
    body = "".join(f"<tr><th>{label}</th><td>1</td></tr>" for label in rows)
    return (
        f"<html><head><title>{title}</title></head><body>"
        '<div id="table_hanyou"><table>'
        "<thead><tr><th></th><th>LV1</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div></body></html>"
    )


@pytest.fixture
def mock_site(monkeypatch, tmp_path: Path):
    """URL → HTML の対応表で応答する httpx クライアントを差し込む。

    CacheHTTP の既定 root（cache/html）をリポジトリではなく tmp_path 配下に置く。
    対応表に無い URL は 500 を返す。戻り値はリクエストされた URL の記録リスト。
    """
    monkeypatch.chdir(tmp_path)
    pages: dict[str, str] = {}
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url not in pages:
            return httpx.Response(status_code=500, text="error")
        return httpx.Response(status_code=200, text=pages[url])

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    monkeypatch.setattr(sm, "get_client", lambda *a, **k: client)
    return pages, requested


def _write_index(path: Path, items: object) -> Path:
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def test_index_writes_items_and_resets_fetch_stats(mock_site, tmp_path, capsys):
    pages, requested = mock_site
    url = "https://example.test/index"
    pages[url] = INDEX_HTML
    out = tmp_path / "nested" / "index.json"
    stats_out = tmp_path / "fetch_stats.json"
    # 前回実行の details フェーズが残っていても、index は先頭フェーズとして破棄する
    stats_out.write_text(
        json.dumps({"phases": {"details": {"network_requests": 99}}}),
        encoding="utf-8",
    )

    rc = sm.main(
        [
            "index",
            "--url",
            url,
            "--out",
            str(out),
            "--fetch-stats-out",
            str(stats_out),
        ]
    )

    assert rc == 0
    assert requested == [url]
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [(i["name"], i["cost"], i["属性"]) for i in items] == [
        ("ジム", 300, "汎用"),
        ("陸戦型ジム", 300, "汎用"),
        ("ジム・キャノン", 350, "支援"),
    ]
    assert out.read_text(encoding="utf-8").endswith("\n")
    stats = json.loads(stats_out.read_text(encoding="utf-8"))
    assert set(stats["phases"]) == {"index"}
    assert stats["phases"]["index"]["network_requests"] == 1
    assert f"index: 3 items -> {out}" in capsys.readouterr().out


def test_index_skips_fetch_stats_when_disabled(mock_site, tmp_path):
    pages, _requested = mock_site
    url = "https://example.test/index"
    pages[url] = INDEX_HTML
    out = tmp_path / "index.json"

    rc = sm.main(["index", "--url", url, "--out", str(out), "--fetch-stats-out", ""])

    assert rc == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 3
    assert not (tmp_path / "cache" / "fetch_stats.json").exists()


def test_labels_rejects_non_array_input(mock_site, tmp_path, capsys):
    _pages, requested = mock_site
    src = _write_index(tmp_path / "index.json", {"url": "https://example.test/1"})
    out = tmp_path / "labels.jsonl"

    rc = sm.main(["labels", "--in", str(src), "--out", str(out)])

    assert rc == 2
    assert "input must be a JSON array" in capsys.readouterr().err
    assert requested == []
    assert not out.exists()


def test_labels_writes_rows_and_continues_after_failure(mock_site, tmp_path, capsys):
    pages, requested = mock_site
    ok_url = "https://example.test/ms/1"
    ng_url = "https://example.test/ms/broken"
    ok_url2 = "https://example.test/ms/2"
    # 重複した行見出しは 1 件にまとめ、出現順を保つ
    pages[ok_url] = _detail_html("ジム", ["HP", "スピード", "HP"])
    pages[ok_url2] = "<html><body><p>表なし</p></body></html>"
    src = _write_index(
        tmp_path / "index.json",
        [
            {"name": "URLなし", "属性": "汎用"},
            {"name": "ジム", "url": ok_url, "属性": "汎用"},
            {"name": "壊れたページ", "url": ng_url, "属性": "強襲"},
            {"name": "表なし", "url": ok_url2, "属性": "支援"},
        ],
    )
    out = tmp_path / "audit" / "labels.jsonl"

    rc = sm.main(["labels", "--in", str(src), "--out", str(out), "--rate", "1000"])

    assert rc == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["url"] for r in rows] == [ok_url, ok_url2]
    assert rows[0]["title"] == "ジム"
    assert rows[0]["attr"] == "汎用"
    assert rows[0]["raw_labels"] == ["HP", "スピード"]
    assert rows[0]["normalized_labels"] == ["HP", "スピード"]
    assert rows[0]["content_sha256"]
    # ステータス表もタイトルも無いページは空のラベルで 1 行出力する
    assert rows[1]["title"] == ""
    assert rows[1]["raw_labels"] == []
    assert rows[1]["normalized_labels"] == []
    assert ng_url in requested
    captured = capsys.readouterr()
    assert f"WARN: labels failed {ng_url}" in captured.err
    assert f"labels: wrote 2 pages -> {out}" in captured.out


def test_labels_stops_at_limit(mock_site, tmp_path):
    pages, requested = mock_site
    urls = [f"https://example.test/ms/{n}" for n in range(1, 4)]
    for url in urls:
        pages[url] = _detail_html("MS", ["HP"])
    src = _write_index(tmp_path / "index.json", [{"url": url} for url in urls])
    out = tmp_path / "labels.jsonl"

    rc = sm.main(
        [
            "labels",
            "--in",
            str(src),
            "--out",
            str(out),
            "--rate",
            "1000",
            "--limit",
            "2",
        ]
    )

    assert rc == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2
    assert requested == urls[:2]
