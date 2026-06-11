#!/usr/bin/env python3
"""
HTTP 取得のキャッシュ層（ETag/Last-Modified + TTL）。

役割
- URLごとに HTML とメタ情報（etag/last_modified/sha256 など）を保存
- TTL内はキャッシュヒット、TTL超過時は条件付きGET（304で不更新）
- 強制更新/オフラインモード対応
- ネットワーク取得の統計（stats）とレート制限（min_interval_seconds）

使用側は httpx.Client を渡す。保存先は `cache/html/` を既定とする。
注意: atwiki は ETag/Last-Modified を返さない（2026-06 実測）ため、
条件付きGETは送るが 304 は期待できない。負荷軽減は取得対象の絞り込みで行う。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import datetime as dt
import hashlib
import json
import re
import time
import urllib.parse

import httpx
from bs4 import BeautifulSoup, Comment


@dataclass
class CacheConfig:
    root: Path = Path("cache/html")
    ttl_seconds: int = 7 * 24 * 3600  # 7日
    no_network: bool = False
    force: bool = False
    # ネットワーク取得の最小間隔（秒）。キャッシュヒット時は待機しない。
    min_interval_seconds: float = 0.0


def new_fetch_stats() -> dict[str, int]:
    return {
        "network_requests": 0,
        "status_200": 0,
        "status_304": 0,
        "failures": 0,
        "body_bytes": 0,
        "cache_hits": 0,
    }


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
    def __init__(self, client: httpx.Client, config: CacheConfig | None = None) -> None:
        self.client = client
        self.cfg = config or CacheConfig()
        self.cfg.root.mkdir(parents=True, exist_ok=True)
        self.stats = new_fetch_stats()
        self._last_request_monotonic: float | None = None

    def _wait_rate_limit(self) -> None:
        if self.cfg.min_interval_seconds <= 0:
            return
        now = time.monotonic()
        if self._last_request_monotonic is not None:
            wait = self.cfg.min_interval_seconds - (now - self._last_request_monotonic)
            if wait > 0:
                time.sleep(wait)

    def _request(self, url: str, headers: dict[str, str]) -> httpx.Response:
        self._wait_rate_limit()
        self.stats["network_requests"] += 1
        self._last_request_monotonic = time.monotonic()
        try:
            return self.client.get(url, headers=headers)
        except Exception:
            self.stats["failures"] += 1
            raise

    def _paths(self, url: str) -> tuple[Path, Path]:
        slug = url_to_slug(url)
        html = self.cfg.root / f"{slug}.html"
        meta = self.cfg.root / f"{slug}.meta.json"
        return html, meta

    @staticmethod
    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_meta(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _write_meta(p: Path, meta: dict) -> None:
        p.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _is_ttl_ok(self, meta: dict, now: dt.datetime) -> bool:
        """前回取得時刻が TTL 内かを判定する（時刻が読めない場合は失効扱い）。"""
        if not meta.get("fetched_at"):
            return False
        try:
            fetched_at = dt.datetime.fromisoformat(meta["fetched_at"])
            return (now - fetched_at).total_seconds() < self.cfg.ttl_seconds
        except Exception:
            return False

    def _serve_from_cache(
        self, html_path: Path, meta_path: Path, meta: dict
    ) -> tuple[str, dict]:
        """キャッシュ済み HTML を返す（ネットワークなし）。

        semantic_changed は「ネットワーク取得していない」ため原則 False。
        ただし保存済み HTML が変わっていた（content_sha256 不一致）場合は
        セマンティックハッシュを再計算し、前回値があり差があれば True。
        初回（prev_sem なし）は False に倒す。
        last_semantic_change_at はネットワーク経路でのみ更新する（ここでは
        読み取りのみ）。semantic_sha256 が欠落していた場合の書き戻しは行う。
        """
        self.stats["cache_hits"] += 1
        text = html_path.read_text(encoding="utf-8")
        content_sha = self._sha256_text(text)
        if meta.get("semantic_sha256") and meta.get("content_sha256") == content_sha:
            # 内容が前回保存時と同一なら、セマンティックハッシュの再計算
            # （BeautifulSoup パース）を省略してそのまま返す。
            # トレードオフ: 抽出アルゴリズム変更は TTL 失効か次回 200 取得まで
            # 保存済み semantic_sha256 に反映されない（その時点で旧値と不一致
            # になり semantic_changed=True として保守的に再処理される）
            meta["semantic_changed"] = False
            return text, meta
        meta["content_sha256"] = content_sha
        # セマンティックハッシュを計算してメタに反映（コメント等を無視した本体の変化検出）
        prev_sem = meta.get("semantic_sha256")
        cur_sem = _semantic_sha256(text)
        meta["semantic_sha256"] = cur_sem
        meta["semantic_changed"] = bool(prev_sem) and (prev_sem != cur_sem)
        try:
            self._write_meta(meta_path, meta)
        except Exception:
            pass
        return text, meta

    def _serve_not_modified(
        self,
        url: str,
        html_path: Path,
        meta_path: Path,
        meta: dict,
        now: dt.datetime,
    ) -> tuple[str, dict]:
        """304 応答: 既存 HTML を使い、メタ情報のみ更新して返す。

        semantic_changed は保存済みハッシュとの単純比較（初回でも prev=None と
        cur の比較で True になり得る点が _serve_from_cache と異なる。
        ネットワークで「未変更」を確認済みのため、差があれば抽出アルゴリズム
        変更等の正当な差分として扱う）。
        """
        self.stats["status_304"] += 1
        text = html_path.read_text(encoding="utf-8")
        prev_sem = meta.get("semantic_sha256")
        cur_sem = _semantic_sha256(text)
        semantic_changed = prev_sem != cur_sem
        meta.update(
            {
                "url": url,
                "fetched_at": now.isoformat(),
                "http_status": 304,
                "content_sha256": self._sha256_text(text),
                "size": len(text.encode("utf-8")),
                "semantic_sha256": cur_sem,
                "semantic_changed": semantic_changed,
                "last_semantic_change_at": (
                    now.isoformat()
                    if semantic_changed
                    else meta.get("last_semantic_change_at")
                ),
            }
        )
        self._write_meta(meta_path, meta)
        return text, meta

    def _store_response(
        self,
        url: str,
        r: httpx.Response,
        html_path: Path,
        meta_path: Path,
        meta: dict,
        now: dt.datetime,
    ) -> tuple[str, dict]:
        """200 応答: 取得本文を保存し、メタ情報を作り直して返す。"""
        self.stats["status_200"] += 1
        self.stats["body_bytes"] += len(r.content)
        text = r.text
        cur_sem = _semantic_sha256(text)
        prev_sem = meta.get("semantic_sha256")
        semantic_changed = prev_sem != cur_sem
        meta_new = {
            "url": url,
            "fetched_at": now.isoformat(),
            "http_status": r.status_code,
            "etag": r.headers.get("ETag"),
            "last_modified": r.headers.get("Last-Modified"),
            "content_sha256": self._sha256_text(text),
            "size": len(text.encode("utf-8")),
            "semantic_sha256": cur_sem,
            "semantic_changed": semantic_changed,
            "last_semantic_change_at": (
                now.isoformat()
                if semantic_changed
                else meta.get("last_semantic_change_at")
            ),
        }
        html_path.write_text(text, encoding="utf-8")
        self._write_meta(meta_path, meta_new)
        return text, meta_new

    def get(self, url: str) -> tuple[str, dict]:
        """キャッシュ対応のGET。戻り値は (text, meta)。

        経路は3つ:
        1. キャッシュ供給（オフライン or TTL内）: _serve_from_cache
        2. 条件付きGET → 304: _serve_not_modified
        3. 条件付きGET → 200: _store_response

        meta には最低限以下を含める:
          - url, fetched_at (ISO8601 UTC), http_status
          - etag, last_modified (あれば)
          - content_sha256, size
          - semantic_sha256, last_semantic_change_at, semantic_changed（追加）
        """
        html_path, meta_path = self._paths(url)
        meta = self._read_meta(meta_path)
        now = _now_utc()
        ttl_ok = self._is_ttl_ok(meta, now)

        # オフライン or TTL内: キャッシュ優先（force は TTL 判定を無視）
        if (
            self.cfg.no_network or (ttl_ok and not self.cfg.force)
        ) and html_path.exists():
            return self._serve_from_cache(html_path, meta_path, meta)

        if self.cfg.no_network and not html_path.exists():
            raise RuntimeError("no-network かつキャッシュ未存在のため取得不可: " + url)

        # 条件付きGET（atwiki は ETag/Last-Modified 非対応のため 304 は期待できない）
        headers: dict[str, str] = {}
        if not self.cfg.force:
            if et := meta.get("etag"):
                headers["If-None-Match"] = et
            if lm := meta.get("last_modified"):
                headers["If-Modified-Since"] = lm

        r = self._request(url, headers)
        if r.status_code == 304 and not html_path.exists():
            # requests 系クライアントは 3xx で raise_for_status が例外を出さないため、
            # 空ボディを 200 としてキャッシュしてしまう前に明示的に失敗させる
            self.stats["failures"] += 1
            raise RuntimeError("304 応答だがキャッシュHTMLが存在しない: " + url)
        if r.status_code == 304 and html_path.exists():
            return self._serve_not_modified(url, html_path, meta_path, meta, now)

        try:
            r.raise_for_status()
        except Exception:
            self.stats["failures"] += 1
            raise
        return self._store_response(url, r, html_path, meta_path, meta, now)


# ==========================
# セマンティック抽出・ハッシュ
# ==========================

_ID_RE_TABLE = re.compile(r"^table_(kyoushu|hanyou|sien)$")
_RE_LV = re.compile(r"LV\d+", re.IGNORECASE)
_RE_SORTIE = re.compile(r"^label_sortie_([GSn])_([GSn])$")
_RE_ENV = re.compile(r"^label_env_([Gn])_([Sn])(?:_([Wn]))?$")


def _extract_semantic_text(html: str) -> str:
    """ステータス本体のみを抽出し、空白を正規化したテキストを返す。

    - コメント/掲示板/スクリプト等は除去
    - ステータステーブル、パーツスロット、強化リスト、出撃/環境適正のIDを含める
    """
    soup = BeautifulSoup(html, "lxml")

    # 1) ノイズの除去: script/style/コメントノード
    for tag in soup(["script", "style"]):
        tag.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()

    # 2) コメント/掲示板ブロックの除去（見出し以降など）
    def decompose_if_noise(tag, *, text_markers: bool = False) -> None:
        if tag is None or not hasattr(tag, "get_text") or not hasattr(tag, "get"):
            return
        txt = ""
        try:
            txt = tag.get_text(" ")
        except Exception:
            pass
        try:
            cls = tag.get("class", []) or []
        except Exception:
            cls = []
        try:
            ident = ((tag.get("id") or "") + " " + " ".join(cls)).lower()
        except Exception:
            ident = ""
        if re.search(
            r"comment|plugin[_-]?comment|bbs|lastmod|recent|counter|sns|social|tweet|footer|foot",
            ident,
        ) or (text_markers and txt and ("コメント" in txt or "掲示板" in txt)):
            tag.decompose()

    for h in soup.find_all(["h2", "h3", "h4"]):
        t = (h.get_text(" ") or "").strip()
        if "コメント" in t or "掲示板" in t:
            # 次の同格見出し手前までを除去
            cur = h
            while True:
                nxt = cur.find_next_sibling()
                if not nxt or (getattr(nxt, "name", "").startswith("h")):
                    break
                decompose_if_noise(nxt, text_markers=True)
                cur = nxt
            # 見出し自身も除去
            h.decompose()

    for tag in list(soup.find_all(True)):
        decompose_if_noise(tag)

    parts: list[str] = []

    # タイトル
    if soup.title and soup.title.get_text():
        parts.append(soup.title.get_text(" ").strip())

    # ステータステーブル（優先: div#table_* 配下）
    table = None
    tbl_div = soup.find(id=_ID_RE_TABLE)
    if tbl_div:
        table = tbl_div.find("table")
    if not table:
        for t in soup.find_all("table"):
            if t.find(string=_RE_LV):
                table = t
                break
    if table:
        parts.append(table.get_text(" ", strip=True))

    # パーツスロット表
    for h3 in soup.find_all("h3"):
        if "パーツスロット" in (h3.get_text(" ") or ""):
            t = h3.find_next_sibling("table")
            if t:
                parts.append(t.get_text(" ", strip=True))
            break

    # 強化リスト情報表
    header = None
    for hx in soup.find_all(["h2", "h3"]):
        if "強化リスト情報" in (hx.get_text(" ") or ""):
            header = hx
            break
    if header:
        t = header.find_next("table")
        if t:
            parts.append(t.get_text(" ", strip=True))

    # 出撃/環境適正の固定ID（ID自体が情報を持つためID文字列を含める）
    lab_sortie = soup.find(id=_RE_SORTIE)
    if lab_sortie and lab_sortie.get("id"):
        parts.append(lab_sortie.get("id"))
    lab_env = soup.find(id=_RE_ENV)
    if lab_env and lab_env.get("id"):
        parts.append(lab_env.get("id"))

    # 連結して空白を正規化
    text = " \n ".join([p for p in parts if p])
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _semantic_sha256(html: str) -> str:
    text = _extract_semantic_text(html)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
