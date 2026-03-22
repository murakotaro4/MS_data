# reports 棚卸し（2026-03-20）

> **注**: 2026-03-22 以降の `reports_manifest.yml` では `repo_improvement_*` と `reports/archive` は廃止済み。以下の「manual / retention に関する archive 記述」は当時のスナップショットとして残す。

`reports_manifest.yml` を定義するための現物棚卸しメモ。

## generated（主なパターン）
- `reports/diff_msdata_*.md`（producer: `scripts.report_msdata_diff` / workflow）
- `reports/provenance_*.json`（producer: `scripts.generate_provenance` / `scripts.tasks snapshot`）
- `reports/label_audit_*.md`（producer: `scripts.audit_labels`）
- `reports/index_ms_audit_*.md`（producer: `scripts.audit_index_vs_msdata`）
- `reports/skills_params_audit.json` / `reports/owners_flat_audit.json` / `reports/skill_owners_audit_*.md`

## manual
- `reports/msdata_update_*.md`（手動サマリ）
- `reports/msdata_update_template.md`（テンプレート）
- `reports/actions_timing_comparison_*.md`
- `reports/repo_improvement_*/**`

## consumer
- workflow: `data_update.yml`, `post_merge_notify.yml`, `auto_review_merge.yml`
- scripts: `scripts/tasks.py`, `scripts/scrape_msdata.py`, `scripts/generate_provenance.py`
- docs: `AGENTS.md`, `README.md`

## retention
- generated: 基本 git 保持（snapshot は artifact/release を併用）
- manual: git 保持
- archive: 互換期間後に `reports/archive/` へ退避
