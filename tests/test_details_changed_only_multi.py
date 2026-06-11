import json
from pathlib import Path

import httpx
import ms_data.scraping.scrape_msdata as sm


def _resp(html: str, status: int = 200, etag: str | None = None):
    headers = {}
    if etag:
        headers["ETag"] = etag
    return httpx.Response(status_code=status, headers=headers, text=html)


def test_changed_only_with_two_urls(monkeypatch, tmp_path: Path):
    url1 = "https://example.test/ms/1"
    url2 = "https://example.test/ms/2"
    index = [
        {"name": "A", "url": url1, "cost": 300, "属性": "汎用"},
        {"name": "B", "url": url2, "cost": 400, "属性": "強襲"},
    ]
    idx_path = tmp_path / "index.json"
    idx_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    base = """
    <html><head><title>X</title></head><body>
      <div id=\"table_hanyou\"><table><thead><tr><th></th><th>LV1</th></tr></thead>
      <tbody><tr><th>機体HP</th><td>10000</td></tr></tbody></table></div>
      <h2>コメント</h2><div class=\"plugin-comment\">c1</div>
    </body></html>
    """
    only_comment = base.replace("c1", "c2")
    changed = base.replace("10000", "11000")

    seq = []
    # 1st round: url1->200(base), url2->200(base)
    seq.append((url1, _resp(base, etag="A1")))
    seq.append((url2, _resp(base, etag="A2")))
    # 2nd round: url1->200(only_comment), url2->200(changed)
    seq.append((url1, _resp(only_comment, etag="B1")))
    seq.append((url2, _resp(changed, etag="B2")))

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        # Pop first matching scheduled response
        for i, (u, resp) in enumerate(seq):
            if u == url:
                seq.pop(i)
                return resp
        # Default
        return _resp(base, etag="Z")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=True)

    def fake_get_client(*args, **kwargs):
        return client

    monkeypatch.setattr(sm, "get_client", fake_get_client)

    # Stub parse_details to avoid heavy parsing
    def fake_parse_details(_text: str):
        return {1: {"MS名": "Dummy_LV1"}}

    monkeypatch.setattr(sm, "parse_details", fake_parse_details)

    out = tmp_path / "details.jsonl"
    args = type(
        "Args",
        (),
        {
            "input": str(idx_path),
            "out": str(out),
            "rate": 100.0,
            "limit": 0,
            "ttl": "0s",
            "no_network": False,
            "force": False,
            "changed_only": True,
        },
    )()

    # Run 1: both write -> 2 records
    rc1 = sm.cmd_details(args)
    assert rc1 == 0
    lines1 = out.read_text(encoding="utf-8").splitlines()
    assert len(lines1) == 2

    # Run 2: only url2 changed -> 1 record
    rc2 = sm.cmd_details(args)
    assert rc2 == 0
    lines2 = out.read_text(encoding="utf-8").splitlines()
    assert len(lines2) == 1
