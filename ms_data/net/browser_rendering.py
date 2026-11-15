"""Cloudflare Browser Rendering（REST API `/content`）による atwiki 取得の代替経路。

atwiki は GitHub Actions からの直接取得に Cloudflare の bot チャレンジ（HTTP 403）を
返すことがある（2026-11-13〜、Issue #405）。`CacheHTTP` は直接取得が 403 で終わった
ときだけ、本モジュールの `BrowserRenderingFetcher` で同じ URL を取り直す。

- 有効化: 環境変数 `CLOUDFLARE_API_TOKEN` と `CLOUDFLARE_ACCOUNT_ID` の両方が
  設定されているときだけ（`from_env`）。未設定なら従来どおり 403 で失敗する。
- 無料枠: Workers Free のブラウザ時間は 1 日 10 分。1 ページ数秒かかるため、
  1 プロセスあたりの取得件数を `MSDATA_BROWSER_RENDERING_MAX_PAGES`（既定 40）で
  打ち切り、REST API のレート制限に合わせて取得間隔を空ける。
- 秘密情報: トークンはログや例外メッセージに出さない。
"""

from __future__ import annotations

import math
import os
import sys
import time

import httpx

API_BASE = "https://api.cloudflare.com/client/v4"

# 1 プロセスあたりの代替取得の上限（無料枠のブラウザ時間 10 分/日に収める）。
DEFAULT_MAX_PAGES = 40
# 代替取得どうしの最小間隔（秒）。無料プランの REST API レート制限に合わせる。
DEFAULT_MIN_INTERVAL_SECONDS = 10.0
# 429 応答時に待ってから 1 回だけ取り直す既定の待機（Retry-After が無い場合）。
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 20.0
# 描画は DOM 構築まで待てば足りる（一覧・詳細とも表は静的 HTML）。画像等は読まない。
REQUEST_OPTIONS: dict[str, object] = {
    "gotoOptions": {"waitUntil": "domcontentloaded", "timeout": 45000},
    "rejectResourceTypes": ["image", "media", "font", "stylesheet"],
}
# チャレンジ画面が返ってきた場合の目印（本文として保存しない）。
CHALLENGE_MARKERS = ("challenge-platform", "cf-chl-", "<title>Just a moment")


class BrowserRenderingError(RuntimeError):
    """代替取得に失敗した（上限到達・API エラー・チャレンジ画面など）。"""


class BrowserRenderingFetcher:
    """Browser Rendering の `/content` で描画後の HTML を取得する。"""

    def __init__(
        self,
        account_id: str,
        api_token: str,
        *,
        client: httpx.Client | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        rate_limit_wait_seconds: float = DEFAULT_RATE_LIMIT_WAIT_SECONDS,
        timeout: float = 90.0,
    ) -> None:
        self.endpoint = f"{API_BASE}/accounts/{account_id}/browser-rendering/content"
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self.client = client or httpx.Client(timeout=timeout)
        self.max_pages = max(max_pages, 0)
        self.min_interval_seconds = max(min_interval_seconds, 0.0)
        self.rate_limit_wait_seconds = max(rate_limit_wait_seconds, 0.0)
        self.used_pages = 0
        self._last_request_monotonic: float | None = None

    @property
    def remaining(self) -> int:
        return max(self.max_pages - self.used_pages, 0)

    def _wait_interval(self) -> None:
        if self._last_request_monotonic is None or self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_monotonic
        wait = self.min_interval_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _post(self, url: str) -> httpx.Response:
        self._wait_interval()
        self._last_request_monotonic = time.monotonic()
        try:
            return self.client.post(
                self.endpoint,
                headers=self._headers,
                json={"url": url, **REQUEST_OPTIONS},
            )
        except httpx.HTTPError as exc:
            raise BrowserRenderingError(
                f"browser rendering request failed ({type(exc).__name__}): {url}"
            ) from None

    def _retry_after(self, r: httpx.Response) -> float:
        """429 の待機秒数。Retry-After が有限の数値でなければ既定の待機を使う。"""
        try:
            wait = float(r.headers.get("Retry-After", ""))
        except ValueError:
            return self.rate_limit_wait_seconds
        # inf は time.sleep が OverflowError、nan は待機なしの即時再試行になる。
        if not math.isfinite(wait):
            return self.rate_limit_wait_seconds
        return max(wait, 0.0)

    def fetch(self, url: str) -> str:
        """URL を描画して HTML を返す。失敗時は BrowserRenderingError。"""
        if self.remaining <= 0:
            raise BrowserRenderingError(
                f"browser rendering page budget exhausted ({self.max_pages}): {url}"
            )
        self.used_pages += 1
        r = self._post(url)
        if r.status_code == 429:
            wait = self._retry_after(r)
            print(
                f"warning: browser rendering rate limited; retry in {wait:g}s: {url}",
                file=sys.stderr,
            )
            if wait > 0:
                time.sleep(wait)
            r = self._post(url)
        if r.status_code != 200:
            raise BrowserRenderingError(
                f"browser rendering HTTP {r.status_code}: {url}"
            )
        try:
            payload = r.json()
        except ValueError:
            raise BrowserRenderingError(
                f"browser rendering returned non-JSON: {url}"
            ) from None
        html = payload.get("result") if isinstance(payload, dict) else None
        if not (isinstance(payload, dict) and payload.get("success")) or not (
            isinstance(html, str) and html.strip()
        ):
            raise BrowserRenderingError(f"browser rendering returned no HTML: {url}")
        if any(marker in html for marker in CHALLENGE_MARKERS):
            raise BrowserRenderingError(
                f"browser rendering returned a challenge page: {url}"
            )
        return html


def _env_number(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    # inf / nan は int() 変換や time.sleep で例外になるため、不正値として扱う。
    if not math.isfinite(value):
        print(f"warning: invalid {name}={raw!r}; using {default:g}", file=sys.stderr)
        return default
    return value


def from_env() -> BrowserRenderingFetcher | None:
    """環境変数から代替取得を組み立てる。認証情報が揃わなければ None（無効）。"""
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not api_token:
        return None
    return BrowserRenderingFetcher(
        account_id,
        api_token,
        max_pages=int(
            _env_number("MSDATA_BROWSER_RENDERING_MAX_PAGES", DEFAULT_MAX_PAGES)
        ),
        min_interval_seconds=_env_number(
            "MSDATA_BROWSER_RENDERING_MIN_INTERVAL", DEFAULT_MIN_INTERVAL_SECONDS
        ),
    )
