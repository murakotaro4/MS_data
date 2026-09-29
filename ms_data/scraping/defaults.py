"""atwiki 取得の既定値（URL / TTL / レート）の SSOT。

パス既定は `ms_data.core.paths`、取得系の非パス既定はここに置く。
`tasks.py` と `scrape_msdata` CLI の両方が参照し、二重定義を防ぐ。
"""

from __future__ import annotations

INDEX_URL = "https://w.atwiki.jp/battle-operation2/pages/377.html"

# キャッシュ TTL（parse_ttl 形式）。本番ワークフローは TTL=1h で上書きする。
DEFAULT_TTL = "7d"

# atwiki への負荷を考慮した既定レート（req/sec）。過度な緩和は避ける。
DEFAULT_RATE = 2.0
