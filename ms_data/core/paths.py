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

CACHE_DIR = Path("cache")
INDEX_JSON = CACHE_DIR / "index.json"
DETAILS_JSONL = CACHE_DIR / "details.jsonl"
DETAILS_JSON = CACHE_DIR / "details.json"
HTML_CACHE_DIR = CACHE_DIR / "html"
LABELS_RAW_JSONL = CACHE_DIR / "labels_raw.jsonl"

DATA_DIR = Path("data")
OFFICIAL_OVERRIDES_DIR = DATA_DIR / "official_overrides"
SKILLS_CATALOG_JSON = DATA_DIR / "skills_catalog.json"
SKILLS_PARAMS_JSON = DATA_DIR / "skills_params.json"
SKILL_OWNERS_JSON = DATA_DIR / "skill_owners.json"
SKILL_OWNERS_FLAT_JSON = DATA_DIR / "skill_owners_flat.json"
SKILLS_POLICY_JSON = DATA_DIR / "skills_policy.json"

REPORTS_DIR = Path("reports")


def reports_month_dir(report_date: str, base_dir: str = "reports") -> str:
    """日付付きレポートの年月ディレクトリ（例: reports/2026/07）。

    report_date は YYYYMMDD 前提。base_dir で REPORTS_DIR オーバーライドを維持する。
    """
    return f"{base_dir}/{report_date[:4]}/{report_date[4:6]}"
