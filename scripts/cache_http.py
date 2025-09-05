#!/usr/bin/env python3
"""
HTTP 取得のキャッシュ層（ETag/Last-Modified + TTL）。

役割
- URLごとに HTML とメタ情報（etag/last_modified/sha256 など）を保存
- TTL内はキャッシュヒット、TTL超過時は条件付きGET（304で不更新）
- 強制更新/オフラインモード対応

使用側は httpx.Client を渡す。保存先は `cache/html/` を既定とする。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
import datetime as dt
import hashlib
import json
import re
import urllib.parse

import httpx


@dataclass
class CacheConfig:
    root: Path = Path("cache/html")
    ttl_seconds: int = 7 * 24 * 3600  # 7日
    no_network: bool = False
    force: bool = False


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "page"


def url_to_slug(url: str) -> str:
    """URL から保存用の slug を作る。末尾に短いハッシュを付けて衝突回避。"""
    p = urllib.parse.urlparse(url)
    base = _slugify(Path(p.path).name or p.netloc)
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{base}-{h}"


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class CacheHTTP:
    def __init__(
        self, client: httpx.Client, config: Optional[CacheConfig] = None
    ) -> None:
        self.client = client
        self.cfg = config or CacheConfig()
        self.cfg.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, url: str) -> Tuple[Path, Path]:
        slug = url_to_slug(url)
        html = self.cfg.root / f"{slug}.html"
        meta = self.cfg.root / f"{slug}.meta.json"
        return html, meta

    @staticmethod
    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_meta(p: Path) -> Dict:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _write_meta(p: Path, meta: Dict) -> None:
        p.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def get(self, url: str) -> Tuple[str, Dict]:
        """キャッシュ対応のGET。戻り値は (text, meta)。

        meta には最低限以下を含める:
          - url, fetched_at (ISO8601 UTC), http_status
          - etag, last_modified (あれば)
          - content_sha256, size
        """
        html_path, meta_path = self._paths(url)
        meta = self._read_meta(meta_path)

        # TTL 判定
        now = _now_utc()
        fetched_at = None
        ttl_ok = False
        if meta.get("fetched_at"):
            try:
                fetched_at = dt.datetime.fromisoformat(meta["fetched_at"])
                ttl_ok = (now - fetched_at).total_seconds() < self.cfg.ttl_seconds
            except Exception:
                ttl_ok = False

        # オフライン or TTL内: キャッシュ優先
        if (self.cfg.no_network or ttl_ok) and html_path.exists():
            text = html_path.read_text(encoding="utf-8")
            if not meta.get("content_sha256"):
                meta["content_sha256"] = self._sha256_text(text)
            # 軽くメタ更新（アクセス時刻更新までは不要）
            return text, meta

        if self.cfg.no_network and not html_path.exists():
            raise RuntimeError("no-network かつキャッシュ未存在のため取得不可: " + url)

        # 条件付きGET
        headers: Dict[str, str] = {}
        if not self.cfg.force:
            if et := meta.get("etag"):
                headers["If-None-Match"] = et
            if lm := meta.get("last_modified"):
                headers["If-Modified-Since"] = lm

        r = self.client.get(url, headers=headers)
        if r.status_code == 304 and html_path.exists():
            # HTMLは既存を使う
            text = html_path.read_text(encoding="utf-8")
            meta.update(
                {
                    "url": url,
                    "fetched_at": now.isoformat(),
                    "http_status": 304,
                    "content_sha256": self._sha256_text(text),
                    "size": len(text.encode("utf-8")),
                }
            )
            self._write_meta(meta_path, meta)
            return text, meta

        r.raise_for_status()
        text = r.text
        meta_new = {
            "url": url,
            "fetched_at": now.isoformat(),
            "http_status": r.status_code,
            "etag": r.headers.get("ETag"),
            "last_modified": r.headers.get("Last-Modified"),
            "content_sha256": self._sha256_text(text),
            "size": len(text.encode("utf-8")),
        }
        html_path.write_text(text, encoding="utf-8")
        self._write_meta(meta_path, meta_new)
        return text, meta_new
