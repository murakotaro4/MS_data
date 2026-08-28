"""リポジトリ内の既定パス定数。

すべてリポジトリルートからの相対パス（各タスクはルートを cwd として実行する前提）。
CLI の `--xxx` 引数で上書きできるため、ここは「既定値」の一元管理のみを担う。
"""

from __future__ import annotations

from pathlib import Path

MSDATA = Path("msData.json")

SCHEMA_DIR = Path("schema")
MSDATA_SCHEMA = SCHEMA_DIR / "msData.schema.json"
OFFICIAL_OVERRIDES_SCHEMA = SCHEMA_DIR / "official_overrides.schema.json"
REPORT_SCHEMAS_DIR = SCHEMA_DIR / "reports"

CACHE_DIR = Path("cache")
INDEX_JSON = CACHE_DIR / "index.json"
CHANGED_INDEX_JSON = CACHE_DIR / "index_changed.json"
CHANGED_INDEX_META_JSON = CACHE_DIR / "index_changed_meta.json"
DETAILS_JSONL = CACHE_DIR / "details.jsonl"
DETAILS_JSON = CACHE_DIR / "details.json"
HTML_CACHE_DIR = CACHE_DIR / "html"
LABELS_RAW_JSONL = CACHE_DIR / "labels_raw.jsonl"
DETAIL_FETCH_STATE_JSON = CACHE_DIR / "detail_fetch_state.json"
FETCH_STATS_JSON = CACHE_DIR / "fetch_stats.json"

DATA_DIR = Path("data")
OFFICIAL_OVERRIDES_DIR = DATA_DIR / "official_overrides"
FIELD_COMPLETENESS_ALLOWLIST = DATA_DIR / "field_completeness_allowlist.json"

REPORTS_DIR = Path("reports")
REPORTS_MANIFEST = Path("reports_manifest.json")


def reports_month_dir(report_date: str, base_dir: str = "reports") -> str:
    """日付付きレポートの年月ディレクトリ（例: reports/2026/07）。

    report_date は YYYYMMDD 前提。base_dir で REPORTS_DIR オーバーライドを維持する。
    """
    return f"{base_dir}/{report_date[:4]}/{report_date[4:6]}"
