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
from typing import Dict, Optional, Tuple, List
import datetime as dt
import hashlib
import json
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup, Comment


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
          - semantic_sha256, last_semantic_change_at, semantic_changed（追加）
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
            # セマンティックハッシュを計算してメタに反映（コメント等を無視した本体の変化検出）
            prev_sem = meta.get("semantic_sha256")
            cur_sem = _semantic_sha256(text)
            meta["semantic_sha256"] = cur_sem
            # TTL内では取得していないため、変化フラグは False（初回は prev_sem が無くても False にする）
            meta["semantic_changed"] = bool(prev_sem) and (prev_sem != cur_sem)
            # last_semantic_change_at は TTL内では更新しない（読み取りのみ）
            # ただし初回で semantic_sha256 が欠落していた場合は書き戻しておく
            try:
                self._write_meta(meta_path, meta)
            except Exception:
                pass
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
            prev_sem = meta.get("semantic_sha256")
            cur_sem = _semantic_sha256(text)
            semantic_changed = (prev_sem != cur_sem)
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
                        now.isoformat() if semantic_changed else meta.get("last_semantic_change_at")
                    ),
                }
            )
            self._write_meta(meta_path, meta)
            return text, meta

        r.raise_for_status()
        text = r.text
        # 200: 新規または内容変更
        cur_sem = _semantic_sha256(text)
        prev_sem = meta.get("semantic_sha256")
        semantic_changed = (prev_sem != cur_sem)
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
                now.isoformat() if semantic_changed else meta.get("last_semantic_change_at")
            ),
        }
        html_path.write_text(text, encoding="utf-8")
        self._write_meta(meta_path, meta_new)
        return text, meta_new


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
    def decompose_if_noise(tag) -> None:
        txt = ""
        try:
            txt = tag.get_text(" ")
        except Exception:
            pass
        ident = ((tag.get("id") or "") + " " + " ".join(tag.get("class", []))).lower()
        if (
            (txt and ("コメント" in txt or "掲示板" in txt))
            or re.search(r"comment|plugin[_-]?comment|bbs|lastmod|recent|counter|sns|social|tweet|footer|foot", ident)
        ):
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
                decompose_if_noise(nxt)
                cur = nxt
            # 見出し自身も除去
            h.decompose()

    for tag in list(soup.find_all(True)):
        decompose_if_noise(tag)

    parts: List[str] = []

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
