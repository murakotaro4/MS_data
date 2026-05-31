import json
from pathlib import Path

import httpx
import pytest

import scripts.scrape_msdata as sm


def _resp(
    html: str,
    etag: str | None = None,
    last_modified: str | None = None,
    status: int = 200,
):
    headers = {}
    if etag is not None:
        headers["ETag"] = etag
    if last_modified is not None:
        headers["Last-Modified"] = last_modified
    return httpx.Response(status_code=status, headers=headers, text=html)


def test_details_changed_only_skips_when_only_comments(monkeypatch, tmp_path: Path):
    url = "https://example.test/ms/1"
    index = [{"name": "Dummy", "url": url, "cost": 300, "属性": "汎用"}]
    idx_path = tmp_path / "index.json"
    idx_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    # Minimal HTML (内容は parse_details では使わない。今回はスタブに置換する)
    html_base = """
    <html><head><title>テストMS</title></head>
    <body>
      <div id="table_hanyou"><table><thead><tr><th></th><th>LV1</th></tr></thead>
      <tbody><tr><th>HP</th><td>10000</td></tr></tbody></table></div>
      <h2>コメント</h2>
      <div class="plugin-comment">初期コメント</div>
    </body></html>
    """
    html_only_comment_changed = html_base.replace("初期コメント", "コメント更新")
    html_status_changed = html_base.replace("10000", "11000")

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _resp(html_base, etag="A")
        elif calls["n"] == 2:
            return _resp(html_only_comment_changed, etag="B")
        else:
            return _resp(html_status_changed, etag="C")

    # Mock client
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=True)

    def fake_get_client(*args, **kwargs):
        return client

    monkeypatch.setattr(sm, "get_client", fake_get_client)

    # Stub parse_details to avoid HTML-dependent parsing complexity
    def fake_parse_details(_text: str):
        return {1: {"MS名": "Dummy_LV1"}}

    monkeypatch.setattr(sm, "parse_details", fake_parse_details)

    out = tmp_path / "details.jsonl"

    # Run 1: initial (should write 1 record)
    detail_state = tmp_path / "detail_fetch_state.json"
    args = type(
        "Args",
        (),
        {
            "input": str(idx_path),
            "out": str(out),
            "rate": 100.0,  # effectively no wait
            "limit": 0,
            "ttl": "0s",
            "no_network": False,
            "force": False,
            "changed_only": True,
            "detail_fetch_state_out": str(detail_state),
        },
    )()
    rc1 = sm.cmd_details(args)
    assert rc1 == 0
    lines1 = out.read_text(encoding="utf-8").splitlines()
    assert len(lines1) == 1
    assert json.loads(lines1[0])["wiki_url"] == url

    # Run 2: only comments changed (should skip -> 0 records in new file)
    rc2 = sm.cmd_details(args)
    assert rc2 == 0
    # File is overwritten each run; when skipped entirely, it will be empty
    content2 = out.read_text(encoding="utf-8")
    assert content2.strip() == ""
    state2 = json.loads(detail_state.read_text(encoding="utf-8"))
    assert state2["items"][url]["http_status"] == 200
    assert state2["items"][url]["semantic_sha256"]

    # Run 3: status changed (should write again)
    rc3 = sm.cmd_details(args)
    assert rc3 == 0
    lines3 = out.read_text(encoding="utf-8").splitlines()
    assert len(lines3) == 1


def test_cmd_details_records_current_fetch_failure(monkeypatch, tmp_path: Path):
    url = "https://example.test/ms/failed"
    idx_path = tmp_path / "index.json"
    idx_path.write_text(
        json.dumps([{"name": "Failed", "url": url, "cost": 300, "属性": "汎用"}]),
        encoding="utf-8",
    )
    detail_state = tmp_path / "detail_fetch_state.json"

    class FailingCache:
        def __init__(self, *_args, **_kwargs):
            pass

        def get(self, _url: str):
            raise RuntimeError("timeout")

    monkeypatch.setattr(sm, "get_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(sm, "CacheHTTP", FailingCache)

    args = type(
        "Args",
        (),
        {
            "input": str(idx_path),
            "out": str(tmp_path / "details.jsonl"),
            "rate": 100.0,
            "limit": 0,
            "ttl": "0s",
            "no_network": False,
            "force": False,
            "changed_only": False,
            "detail_fetch_state_out": str(detail_state),
        },
    )()

    assert sm.cmd_details(args) == 0
    state = json.loads(detail_state.read_text(encoding="utf-8"))
    assert state["run_started_at"]
    assert state["items"][url]["ok"] is False
    assert state["items"][url]["attempted_at"]
    assert state["items"][url]["error"] == "timeout"
    assert "fetched_at" not in state["items"][url]
