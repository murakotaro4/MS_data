"""ネットワーク取得統計（fetch stats）とレート制限の挙動を検証する。"""

import json
from pathlib import Path

import httpx
import pytest

import ms_data.net.cache_http as cache_http
import ms_data.scraping.scrape_msdata as sm
from ms_data.net.cache_http import CacheConfig, CacheHTTP


HTML = (
    "<html><title>T</title><table><tr><th></th><th>LV1</th></tr>"
    "<tr><th>機体HP</th><td>10000</td></tr></table></html>"
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_stats_counts_200_and_cache_hit(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text=HTML)

    cache = CacheHTTP(_client(handler), CacheConfig(root=tmp_path, ttl_seconds=3600))

    cache.get("https://example.test/page")
    assert cache.stats["network_requests"] == 1
    assert cache.stats["status_200"] == 1
    assert cache.stats["body_bytes"] == len(HTML.encode("utf-8"))
    assert cache.stats["cache_hits"] == 0

    # TTL内の2回目はキャッシュヒット（ネットワークに行かない）
    cache.get("https://example.test/page")
    assert cache.stats["network_requests"] == 1
    assert cache.stats["cache_hits"] == 1


def test_stats_counts_304(tmp_path: Path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(status_code=200, headers={"ETag": "A"}, text=HTML)
        return httpx.Response(status_code=304)

    cache = CacheHTTP(_client(handler), CacheConfig(root=tmp_path, ttl_seconds=0))
    cache.get("https://example.test/page")
    cache.get("https://example.test/page")
    assert cache.stats["network_requests"] == 2
    assert cache.stats["status_200"] == 1
    assert cache.stats["status_304"] == 1
    # 304 では body を受信しない
    assert cache.stats["body_bytes"] == len(HTML.encode("utf-8"))


def test_stats_counts_failures(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, text="error")

    cache = CacheHTTP(_client(handler), CacheConfig(root=tmp_path, ttl_seconds=0))
    with pytest.raises(httpx.HTTPStatusError):
        cache.get("https://example.test/page")
    assert cache.stats["failures"] == 1
    assert cache.stats["status_200"] == 0


def test_rate_limit_waits_only_for_network_requests(monkeypatch, tmp_path: Path):
    sleeps: list[float] = []
    monkeypatch.setattr(cache_http.time, "sleep", lambda s: sleeps.append(s))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text=HTML)

    cache = CacheHTTP(
        _client(handler),
        CacheConfig(root=tmp_path, ttl_seconds=3600, min_interval_seconds=0.5),
    )

    cache.get("https://example.test/a")
    assert sleeps == []  # 初回リクエストは待機しない

    cache.get("https://example.test/b")
    assert len(sleeps) == 1  # 2回目のネットワーク取得は間隔を保つ

    cache.get("https://example.test/a")  # キャッシュヒット
    assert len(sleeps) == 1  # キャッシュヒットでは待機しない


def test_cache_hit_skips_semantic_recompute(monkeypatch, tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text=HTML)

    cache = CacheHTTP(_client(handler), CacheConfig(root=tmp_path, ttl_seconds=3600))
    _text, meta1 = cache.get("https://example.test/page")

    calls = {"n": 0}
    original = cache_http._semantic_sha256

    def counting(html: str) -> str:
        calls["n"] += 1
        return original(html)

    monkeypatch.setattr(cache_http, "_semantic_sha256", counting)

    _text2, meta2 = cache.get("https://example.test/page")
    assert calls["n"] == 0  # 内容が同一ならセマンティック再計算しない
    assert meta2["semantic_sha256"] == meta1["semantic_sha256"]
    assert meta2["semantic_changed"] is False


def test_write_fetch_stats_merges_phases_and_totals(tmp_path: Path):
    from datetime import datetime, timezone

    path = tmp_path / "fetch_stats.json"
    started = datetime(2026, 6, 11, 9, 0, tzinfo=timezone.utc)

    sm.write_fetch_stats(
        path,
        "index",
        {"network_requests": 1, "status_200": 1, "body_bytes": 100},
        started_at=started,
        duration_seconds=1.5,
    )
    sm.write_fetch_stats(
        path,
        "details",
        {"network_requests": 10, "status_200": 9, "body_bytes": 900},
        started_at=started,
        duration_seconds=20.0,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["phases"]) == {"index", "details"}
    assert data["totals"]["network_requests"] == 11
    assert data["totals"]["status_200"] == 10
    assert data["totals"]["body_bytes"] == 1000
    assert data["totals"]["duration_seconds"] == pytest.approx(21.5)
    assert data["generated_at"]


def test_cmd_details_writes_fetch_stats(monkeypatch, tmp_path: Path):
    url = "https://example.test/ms/1"
    idx_path = tmp_path / "index.json"
    idx_path.write_text(
        json.dumps([{"name": "Dummy", "url": url, "cost": 300, "属性": "汎用"}]),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text=HTML)

    monkeypatch.setattr(sm, "get_client", lambda *a, **k: _client(handler))
    monkeypatch.setattr(sm, "parse_details", lambda _text: {1: {"MS名": "Dummy_LV1"}})
    monkeypatch.chdir(tmp_path)

    stats_path = tmp_path / "cache/fetch_stats.json"
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
            "detail_fetch_state_out": str(tmp_path / "detail_fetch_state.json"),
            "fetch_stats_out": str(stats_path),
        },
    )()

    assert sm.cmd_details(args) == 0
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    assert data["phases"]["details"]["network_requests"] == 1
    assert data["phases"]["details"]["status_200"] == 1
    assert data["phases"]["details"]["body_bytes"] == len(HTML.encode("utf-8"))
    assert data["phases"]["details"]["duration_seconds"] >= 0


def test_write_fetch_stats_reset_discards_previous_run(tmp_path: Path):
    from datetime import datetime, timezone

    path = tmp_path / "fetch_stats.json"
    started = datetime(2026, 6, 11, 9, 0, tzinfo=timezone.utc)

    # 前回実行: index + details
    sm.write_fetch_stats(
        path,
        "index",
        {"network_requests": 1, "body_bytes": 100},
        started_at=started,
        duration_seconds=1.0,
        reset=True,
    )
    sm.write_fetch_stats(
        path,
        "details",
        {"network_requests": 600, "body_bytes": 999999},
        started_at=started,
        duration_seconds=300.0,
    )

    # 今回実行: index のみ（details が走らないケース）。reset で前回分を破棄
    sm.write_fetch_stats(
        path,
        "index",
        {"network_requests": 1, "body_bytes": 200},
        started_at=started,
        duration_seconds=2.0,
        reset=True,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["phases"]) == {"index"}  # 前回の details が混入しない
    assert data["totals"]["network_requests"] == 1
    assert data["totals"]["body_bytes"] == 200


def test_304_without_cached_html_raises_and_counts_failure(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=304)

    cache = CacheHTTP(_client(handler), CacheConfig(root=tmp_path, ttl_seconds=0))
    with pytest.raises(RuntimeError):
        cache.get("https://example.test/page")
    assert cache.stats["failures"] == 1
    assert cache.stats["status_200"] == 0
    assert cache.stats["status_304"] == 0
