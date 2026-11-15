"""Browser Rendering 代替取得と CacheHTTP のフォールバックのテスト。"""

from __future__ import annotations

import json
import traceback
from pathlib import Path

import httpx
import pytest

from ms_data.net import browser_rendering as br
from ms_data.net.browser_rendering import (
    BrowserRenderingError,
    BrowserRenderingFetcher,
)
from ms_data.net.cache_http import CacheConfig, CacheHTTP

URL = "https://w.atwiki.jp/battle-operation2/pages/377.html"
TOKEN = "dummy-token-value"
ACCOUNT = "dummy-account-id"
PAGE = "<html><head><title>MS一覧</title></head><body><table></table></body></html>"


def _api_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(html: str = PAGE) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "result": html})


def _fetcher(handler, **kwargs) -> BrowserRenderingFetcher:
    kwargs.setdefault("min_interval_seconds", 0.0)
    kwargs.setdefault("rate_limit_wait_seconds", 0.0)
    return BrowserRenderingFetcher(
        ACCOUNT, TOKEN, client=_api_client(handler), **kwargs
    )


def test_fetch_posts_url_with_bearer_and_returns_html():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()

    fetcher = _fetcher(handler)
    assert fetcher.fetch(URL) == PAGE
    req = seen[0]
    assert req.method == "POST"
    assert req.url.path == f"/client/v4/accounts/{ACCOUNT}/browser-rendering/content"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    body = json.loads(req.content)
    assert body["url"] == URL
    assert body["gotoOptions"]["waitUntil"] == "domcontentloaded"
    assert fetcher.used_pages == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"success": False, "errors": [{"code": 1}]}),
        httpx.Response(200, json={"success": True, "result": "  "}),
        httpx.Response(200, json=["unexpected"]),
        _ok("<html><title>Just a moment...</title></html>"),
        _ok('<script src="/cdn-cgi/challenge-platform/x.js"></script>'),
    ],
)
def test_fetch_rejects_errors_and_challenge_pages(response: httpx.Response):
    fetcher = _fetcher(lambda _req: response)
    with pytest.raises(BrowserRenderingError) as exc_info:
        fetcher.fetch(URL)
    # 例外メッセージに認証情報・アカウントIDを含めない（公開ログ対策）
    assert TOKEN not in str(exc_info.value)
    assert ACCOUNT not in str(exc_info.value)


def test_fetch_wraps_transport_errors_without_secrets():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    fetcher = _fetcher(handler)
    with pytest.raises(BrowserRenderingError) as exc_info:
        fetcher.fetch(URL)
    assert "ConnectError" in str(exc_info.value)
    # 例外連鎖を切り、整形済みトレースバックにも API URL・認証情報を出さない
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    formatted = "".join(traceback.format_exception(exc_info.value))
    assert "ConnectError" in formatted
    assert ACCOUNT not in formatted
    assert TOKEN not in formatted
    assert "api.cloudflare.com" not in formatted


def test_fetch_retries_once_after_rate_limit():
    responses = [httpx.Response(429, headers={"Retry-After": "0"}), _ok()]
    fetcher = _fetcher(lambda _req: responses.pop(0))
    assert fetcher.fetch(URL) == PAGE
    assert responses == []
    # 429 後の取り直しは 1 件として数える
    assert fetcher.used_pages == 1


def test_fetch_gives_up_after_second_rate_limit():
    fetcher = _fetcher(lambda _req: httpx.Response(429, headers={"Retry-After": "x"}))
    with pytest.raises(BrowserRenderingError, match="HTTP 429"):
        fetcher.fetch(URL)


def test_fetch_stops_at_page_budget():
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _ok()

    fetcher = _fetcher(handler, max_pages=2)
    fetcher.fetch(URL)
    fetcher.fetch(URL)
    assert fetcher.remaining == 0
    with pytest.raises(BrowserRenderingError, match="budget exhausted"):
        fetcher.fetch(URL)
    assert calls["n"] == 2


def test_fetch_waits_min_interval_between_requests(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []
    monkeypatch.setattr(br.time, "sleep", sleeps.append)
    fetcher = _fetcher(lambda _req: _ok(), min_interval_seconds=10.0)
    fetcher.fetch(URL)
    fetcher.fetch(URL)
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 10.0


@pytest.mark.parametrize(
    ("account", "token"),
    [("", ""), (ACCOUNT, ""), ("", TOKEN), ("  ", TOKEN)],
)
def test_from_env_disabled_without_credentials(
    monkeypatch: pytest.MonkeyPatch, account: str, token: str
):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", account)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", token)
    assert br.from_env() is None


def test_from_env_reads_limits(monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    monkeypatch.setenv("MSDATA_BROWSER_RENDERING_MAX_PAGES", "5")
    monkeypatch.setenv("MSDATA_BROWSER_RENDERING_MIN_INTERVAL", "oops")
    fetcher = br.from_env()
    assert fetcher is not None
    assert fetcher.max_pages == 5
    assert fetcher.min_interval_seconds == br.DEFAULT_MIN_INTERVAL_SECONDS
    err = capsys.readouterr().err
    assert "MSDATA_BROWSER_RENDERING_MIN_INTERVAL" in err
    assert TOKEN not in err


# ---------------------------------------------------------------------------
# CacheHTTP との結合
# ---------------------------------------------------------------------------


class FakeFallback:
    def __init__(self, html: str = PAGE, error: Exception | None = None) -> None:
        self.html = html
        self.error = error
        self.urls: list[str] = []

    def fetch(self, url: str) -> str:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.html


def _cache(tmp_path: Path, status: int, fallback: FakeFallback | None) -> CacheHTTP:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _req: httpx.Response(status, text="x"))
    )
    return CacheHTTP(
        client, CacheConfig(root=tmp_path, ttl_seconds=0), fallback=fallback
    )


def test_cache_uses_fallback_only_after_direct_403(tmp_path: Path):
    fallback = FakeFallback()
    cache = _cache(tmp_path, 403, fallback)
    text, meta = cache.get(URL)
    assert text == PAGE
    assert fallback.urls == [URL]
    assert meta["http_status"] == 200
    assert meta["fetched_via"] == "browser_rendering"
    assert cache.stats["failures"] == 1
    assert cache.stats["status_200"] == 1
    assert cache.stats["body_bytes"] == len(PAGE.encode("utf-8"))
    # 代替取得の本文も通常どおりキャッシュに残る（weapons 等が読み直す）
    html_path, _ = cache._paths(URL)
    assert html_path.read_text(encoding="utf-8") == PAGE


def test_cache_does_not_use_fallback_when_direct_succeeds(tmp_path: Path):
    fallback = FakeFallback()
    cache = _cache(tmp_path, 200, fallback)
    _text, meta = cache.get(URL)
    assert fallback.urls == []
    assert "fetched_via" not in meta


def test_cache_does_not_use_fallback_for_other_errors(tmp_path: Path):
    fallback = FakeFallback()
    cache = _cache(tmp_path, 500, fallback)
    with pytest.raises(httpx.HTTPStatusError):
        cache.get(URL)
    assert fallback.urls == []


def test_cache_403_without_fallback_still_fails(tmp_path: Path):
    cache = _cache(tmp_path, 403, None)
    with pytest.raises(httpx.HTTPStatusError):
        cache.get(URL)
    assert cache.stats["failures"] == 1


def test_cache_propagates_fallback_failure(tmp_path: Path):
    fallback = FakeFallback(error=BrowserRenderingError("nope"))
    cache = _cache(tmp_path, 403, fallback)
    with pytest.raises(BrowserRenderingError):
        cache.get(URL)
    html_path, _ = cache._paths(URL)
    assert not html_path.exists()
    assert cache.stats["status_200"] == 0


# ---------------------------------------------------------------------------
# ワークフロー契約（公開リポジトリのため認証情報は secrets 経由のみ）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("- name: Fetch and import", "- id: source_slots"),
        ("- id: custom_parts", "- id: weapons"),
    ],
)
def test_data_update_passes_cloudflare_credentials_via_secrets(start: str, end: str):
    from workflow_contract import assert_absent, assert_contains, workflow_step

    block = workflow_step("data_update.yml", start=start, end=end)
    assert_contains(
        block,
        [
            "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}",
            "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}",
        ],
    )
    assert_absent(
        block,
        ["vars.CLOUDFLARE", "echo \"$CLOUDFLARE", "echo $CLOUDFLARE", "set -x"],
    )
