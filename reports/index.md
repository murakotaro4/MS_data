# reports インデックス

`reports_manifest.yml` に基づく `reports` の参照入口です。

## generated
- `diff_msdata_YYYYMMDD.md` : 日次の msData 差分
- `provenance_YYYYMMDD.json` : 生成元証跡（復元情報を含む）
- `label_audit_YYYYMMDD.md` : ラベル監査
- `index_ms_audit_YYYYMMDD.md` : index と msData の整合監査
- `skills_params_audit.json` / `owners_flat_audit.json` : skills系監査

## manual
- `msdata_update_YYYYMMDD.md` : 週次/都度の人手更新レポート
- `README.md` / `index.md` : 運用メモ

## 参照先
- PR本文: `reports/diff_msdata_YYYYMMDD.md`
- Release asset: `raw_snapshot_YYYYMMDD_run<run_id>.tar.xz`
- provenance: `reports/provenance_YYYYMMDD.json`
