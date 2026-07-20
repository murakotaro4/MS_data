# reports ディレクトリ運用ガイド

このディレクトリは、生成レポートと手動レポートを共存させる領域です。  
運用のSSOTはリポジトリ直下の `reports_manifest.json` です。

## レイアウト（v3）
- 日付付き生成レポートの正: `reports/YYYY/MM/<name>_YYYYMMDD.*`
- 直下に残すもの: `README.md` / `index.md` / `msdata_update_template.md` と undated（`skills_params_audit.json` / `owners_flat_audit.json` / `label_audit_latest.md` / `auto_review_*.json`）

## 分類
- `generated`: スクリプト/Workflowが生成する成果物
- `manual`: 手作業で作成するレポート・メモ

## 最新導線
- 日次差分: `YYYY/MM/diff_msdata_YYYYMMDD.md`
- 生成証跡: `YYYY/MM/provenance_YYYYMMDD.json`
- 監査: `YYYY/MM/label_audit_YYYYMMDD.md` / `YYYY/MM/index_ms_audit_YYYYMMDD.md`
- 手動更新レポート: `YYYY/MM/msdata_update_YYYYMMDD.md`

## 互換ポリシー（v3）
- v3 で年月階層へ破壊的移行済み（旧フラットパスの転送なし）。
- `compatibility.legacy_path_support` は `false`。新規書き出し・検証・Release 添付はすべて `reports/YYYY/MM/` を使う。

## CI検証
- CIの `reports` 検証は `reports_manifest.json` の allowlist に対して実行します。
- `manual` タイプのパスは生成物と別枠で allowlist に照合します（失敗時は stderr に `report file not listed in manifest allowlist:` と違反パスが出ます）。
