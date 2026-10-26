import datetime as dt
from pathlib import Path

import httpx
import pytest

from ms_data.net.cache_http import (
    CacheConfig,
    CacheHTTP,
    _extract_semantic_text,
    _semantic_sha256,
)


def _resp(
    html: str,
    status: int = 200,
    etag: str | None = None,
    last_modified: str | None = None,
):
    headers = {}
    if etag:
        headers["ETag"] = etag
    if last_modified:
        headers["Last-Modified"] = last_modified
    return httpx.Response(status_code=status, headers=headers, text=html)


def test_conditional_get_304_updates_meta(tmp_path: Path):
    url = "https://example.test/page"

    # First 200, then 304
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _resp(
                "<html><title>T</title><table><tr><th></th><th>LV1</th></tr><tr><th>機体HP</th><td>10000</td></tr></table></html>",
                status=200,
                etag="A",
                last_modified="X",
            )
        return _resp("", status=304)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=True)
    cache = CacheHTTP(client, CacheConfig(root=tmp_path, ttl_seconds=0))

    text1, meta1 = cache.get(url)
    assert meta1["http_status"] == 200
    assert meta1.get("etag") == "A"
    assert "semantic_sha256" in meta1

    text2, meta2 = cache.get(url)
    assert meta2["http_status"] == 304
    # 304でも semantic_* が維持/再計算される
    assert meta2["semantic_sha256"] == meta1["semantic_sha256"]
    assert meta2.get("semantic_changed") is False


def test_read_meta_missing_file_is_quiet_cache_miss(tmp_path: Path, capsys):
    missing = tmp_path / "missing.meta.json"

    assert CacheHTTP._read_meta(missing) == {}
    assert capsys.readouterr().err == ""


def test_read_meta_invalid_utf8_warns_and_falls_back(tmp_path: Path, capsys):
    broken = tmp_path / "broken.meta.json"
    broken.write_bytes(b"\xff")

    assert CacheHTTP._read_meta(broken) == {}
    assert "warning: failed to read cache metadata" in capsys.readouterr().err


_STATUS_HTML = """<html><head><title>テストMS</title></head><body>
<div id="table_hanyou"><table><tr><th>機体HP</th><td>10000</td></tr></table></div>
{noise}</body></html>"""
_NESTED_NOISE = """<div class="plugin-comment"><div id="recent">
<table><tr><th>LV1</th><td>ノイズ</td></tr></table>
<span>コメント</span></div></div>"""


@pytest.mark.parametrize(
    "noise",
    [
        _NESTED_NOISE,
        '<div id="bbs"><div><span>掲示板</span></div></div>',
        '<footer class="footer"><ul><li><a>リンク</a></li></ul></footer>',
    ],
)
def test_nested_noise_keeps_semantic_text_and_hash_without_warnings(
    noise: str, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_html = _STATUS_HTML.format(noise="")
    noisy_html = _STATUS_HTML.format(noise=noise)

    assert _extract_semantic_text(noisy_html) == _extract_semantic_text(clean_html)
    assert _extract_semantic_text(noisy_html) == "テストMS 機体HP 10000"
    assert _semantic_sha256(noisy_html) == _semantic_sha256(clean_html)
    # 修正前の抽出結果から記録したハッシュも維持する。
    assert _semantic_sha256(noisy_html) == (
        "4c0afe71b307a50f3f6b4114efa701012872c6cb0e3b6a3723cb58283fd39f64"
    )
    assert capsys.readouterr().err == ""


def test_nested_noise_change_is_ignored_but_content_change_is_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    html_base = _STATUS_HTML.format(noise=_NESTED_NOISE)
    html_noise_changed = html_base.replace("ノイズ", "新しいノイズ")
    html_content_changed = html_noise_changed.replace("10000", "11000")
    responses = iter([html_base, html_noise_changed, html_content_changed])

    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(next(responses))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cache = CacheHTTP(client, CacheConfig(root=tmp_path, ttl_seconds=0))
        url = "https://example.test/nested-noise"
        text1, meta1 = cache.get(url)
        text2, meta2 = cache.get(url)
        text3, meta3 = cache.get(url)

    assert (text1, text2, text3) == (
        html_base,
        html_noise_changed,
        html_content_changed,
    )
    assert meta1["semantic_changed"] is True
    assert meta2["semantic_changed"] is False
    assert meta3["semantic_changed"] is True
    assert meta1["content_sha256"] != meta2["content_sha256"]
    assert meta1["semantic_sha256"] == meta2["semantic_sha256"]
    assert meta2["semantic_sha256"] != meta3["semantic_sha256"]
    assert meta1["last_semantic_change_at"] == meta2["last_semantic_change_at"]
    assert meta2["last_semantic_change_at"] != meta3["last_semantic_change_at"]
    assert cache.stats["network_requests"] == 3
    assert capsys.readouterr().err == ""


def test_semantic_hash_ignores_comments(tmp_path: Path):
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
    cache = CacheHTTP(client, CacheConfig(root=tmp_path, ttl_seconds=0))

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


# --- get() の各経路（キャッシュ供給・失敗系）---

_URL = "https://example.test/page"
_BODY = "<html><title>T</title><div id='table_hanyou'><table><tr><th>機体HP</th><td>1</td></tr></table></div></html>"


def _cache(tmp_path: Path, handler, **cfg) -> CacheHTTP:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CacheHTTP(client, CacheConfig(root=tmp_path, **cfg))


def test_ttl_hit_serves_cache_without_network(tmp_path: Path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _resp(_BODY)

    cache = _cache(tmp_path, handler, ttl_seconds=3600)
    cache.get(_URL)
    text, meta = cache.get(_URL)

    assert calls["n"] == 1
    assert text == _BODY
    assert meta["semantic_changed"] is False
    assert cache.stats["cache_hits"] == 1


def test_force_ignores_ttl_and_conditional_headers(tmp_path: Path):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        return _resp(_BODY, etag="A")

    _cache(tmp_path, handler, ttl_seconds=3600).get(_URL)
    forced = _cache(tmp_path, handler, ttl_seconds=3600, force=True)
    forced.get(_URL)

    assert len(seen) == 2
    assert "if-none-match" not in seen[1]
    assert forced.stats["status_200"] == 1


def test_no_network_without_cache_raises(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("ネットワークに出てはならない")

    cache = _cache(tmp_path, handler, no_network=True)

    with pytest.raises(RuntimeError, match="no-network"):
        cache.get(_URL)


def test_serve_from_cache_detects_edited_html(tmp_path: Path):
    cache = _cache(tmp_path, lambda r: _resp(_BODY), ttl_seconds=3600)
    cache.get(_URL)
    html_path, _ = cache._paths(_URL)
    html_path.write_text(_BODY.replace(">1<", ">2<"), encoding="utf-8")

    _, meta = cache.get(_URL)

    assert meta["semantic_changed"] is True


def test_304_without_cached_html_fails(tmp_path: Path):
    cache = _cache(tmp_path, lambda r: _resp("", status=304))

    with pytest.raises(RuntimeError, match="304"):
        cache.get(_URL)
    assert cache.stats["failures"] == 1


def test_http_error_counts_failure(tmp_path: Path):
    cache = _cache(tmp_path, lambda r: _resp("x", status=500))

    with pytest.raises(httpx.HTTPStatusError):
        cache.get(_URL)
    assert cache.stats["failures"] == 1
    assert not cache._paths(_URL)[0].exists()


def test_transport_error_counts_failure(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    cache = _cache(tmp_path, handler)

    with pytest.raises(httpx.ConnectError):
        cache.get(_URL)
    assert cache.stats["network_requests"] == 1
    assert cache.stats["failures"] == 1


def test_invalid_fetched_at_is_expired_with_warning(tmp_path: Path, capsys):
    cache = _cache(tmp_path, lambda r: _resp(_BODY), ttl_seconds=3600)
    now = dt.datetime.now(dt.timezone.utc)

    assert cache._is_ttl_ok({}, now) is False
    assert cache._is_ttl_ok({"fetched_at": "not-a-date"}, now) is False
    assert "invalid cache fetched_at" in capsys.readouterr().err
