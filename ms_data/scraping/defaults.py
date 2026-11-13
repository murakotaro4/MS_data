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

# 直接CLIの既定は従来の1 req/secを維持（tasksは2 req/sec）。
DEFAULT_CLI_RATE = 1.0

# 一覧ページ取得の再試行。一覧は実行全体の起点で、一過性の 403（Cloudflare）や
# 5xx の 1 回で自動更新全体が失敗するため、少数回だけ間隔を空けて再試行する。
# 詳細ページは件数が多く負荷が増えるため再試行しない（失敗は品質レポートで監視）。
INDEX_FETCH_RETRIES = 2
INDEX_RETRY_WAIT_SECONDS = 10.0
