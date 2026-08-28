from pathlib import Path

import httpx

from ms_data.net.cache_http import CacheConfig, CacheHTTP


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
