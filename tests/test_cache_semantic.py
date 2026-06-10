import json
from pathlib import Path

import httpx
import pytest

from ms_data.net.cache_http import CacheHTTP, CacheConfig, _extract_semantic_text


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


@pytest.mark.parametrize("ttl", [0])
def test_semantic_hash_ignores_comments(tmp_path: Path, ttl: int):
    url = "https://example.test/page"

    html_base = """
    <html><head><title>テストMS</title></head>
    <body>
      <div id="table_hanyou">
        <table>
          <thead><tr><th></th><th>LV1</th></tr></thead>
          <tbody>
            <tr><th>HP</th><td>10000</td></tr>
          </tbody>
        </table>
      </div>
      <h2>コメント</h2>
      <div class="plugin-comment">初期コメント</div>
    </body></html>
    """
    html_only_comment_changed = html_base.replace("初期コメント", "別のコメントが追加")
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

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=True)
    cache = CacheHTTP(client, CacheConfig(root=tmp_path, ttl_seconds=ttl))

    # 1st: initial fetch
    text, meta1 = cache.get(url)
    assert meta1["http_status"] == 200
    assert "semantic_sha256" in meta1
    assert meta1.get("semantic_changed") is True  # 初回は変更として扱う

    # 2nd: only comment changed
    text, meta2 = cache.get(url)
    assert meta2["http_status"] == 200
    assert meta2.get("semantic_changed") is False
    assert meta2["semantic_sha256"] == meta1["semantic_sha256"]

    # 3rd: status changed
    text, meta3 = cache.get(url)
    assert meta3["http_status"] == 200
    assert meta3.get("semantic_changed") is True
    assert meta3["semantic_sha256"] != meta2["semantic_sha256"]


def test_extract_semantic_text_keeps_status_table_when_outer_has_comment_text():
    html = """
    <html><head><title>テストMS</title></head>
    <body>
      <div id="wiki-body">
        <nav>目次 コメント欄</nav>
        <div id="table_hanyou">
          <table>
            <thead><tr><th></th><th>LV1</th></tr></thead>
            <tbody><tr><th>機体HP</th><td>10000</td></tr></tbody>
          </table>
        </div>
        <h2>コメント欄</h2>
        <div class="plugin-comment">コメントだけが変わる領域</div>
      </div>
    </body></html>
    """

    text = _extract_semantic_text(html)

    assert "機体HP" in text
    assert "10000" in text
    assert "コメントだけが変わる領域" not in text
