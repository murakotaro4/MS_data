"""atwiki アクセス用 HTTP クライアントのファクトリ。

get_scraper_client: 機体一覧・詳細スクレイピング用（cloudscraper 優先、bot UA）。
Cloudflare 対策が不要な環境では `MSDATA_HTTP_CLIENT=httpx` で素の httpx に切替可。
"""

from __future__ import annotations

import functools
import os
import sys

import httpx


def get_scraper_client(timeout: float = 30.0) -> httpx.Client:
    headers = {"User-Agent": "msdata-scraper/0.1 (+https://github.com/; contact=local)"}
    # Cloudflare対策: cloudscraper が利用可能な場合は優先して使う。
    if os.getenv("MSDATA_HTTP_CLIENT", "cloudscraper").lower() == "cloudscraper":
        try:
            import cloudscraper

            scraper = cloudscraper.create_scraper()
            scraper.headers.update(headers)
            scraper.request = functools.partial(scraper.request, timeout=timeout)
            return scraper
        except Exception as exc:  # cloudscraperが使えない場合は httpx へフォールバック
            print(
                f"[warn] cloudscraper unavailable, fallback to httpx: {exc}",
                file=sys.stderr,
            )
    return httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)
