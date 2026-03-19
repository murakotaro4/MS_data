# reports ディレクトリ運用ガイド

このディレクトリは、生成レポートと手動レポートを共存させる領域です。  
運用のSSOTはリポジトリ直下の `reports_manifest.yml` です。

## 分類
- `generated`: スクリプト/Workflowが生成する成果物
- `manual`: 手作業で作成するレポート・メモ
- `archive`: 互換期間後に退避した履歴

## 最新導線
- 日次差分: `diff_msdata_YYYYMMDD.md`
- 生成証跡: `provenance_YYYYMMDD.json`
- 監査: `label_audit_YYYYMMDD.md` / `index_ms_audit_YYYYMMDD.md`
- 手動更新レポート: `msdata_update_YYYYMMDD.md`

## 互換期間ポリシー
- 旧パスは最低 1 リリース周期のあいだ互換を維持します。
- 旧導線の撤去は次の条件を満たしたときに実施します。
  - 旧パス参照 consumer が 0
  - 互換期間（1リリース周期）を経過

## CI検証
- CIの `reports` 検証は `reports_manifest.yml` の allowlist に対して実行します。
- `manual` / `archive` は命名規則の厳格チェック対象から除外します。
