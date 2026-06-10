"""atwiki アクセス用 HTTP クライアントのファクトリ。

用途別に2種類あり、ヘッダ・Cloudflare 対策の有無が異なる（統合すると
スクレイピング挙動が変わるため、意図的に分離したまま管理する）:
- get_scraper_client: 機体詳細スクレイピング用（cloudscraper 優先、bot UA）
- get_browser_client: スキル一覧テーブル取得用（ブラウザ風ヘッダの素の httpx）
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


def get_browser_client(timeout: float = 30.0) -> httpx.Client:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    }
    return httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)
