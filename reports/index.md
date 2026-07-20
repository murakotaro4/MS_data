# reports インデックス

`reports_manifest.json` に基づく `reports` の参照入口です。

日付付き成果物は `reports/YYYY/MM/<name>_YYYYMMDD.*` が正です。直下は README/index/template と undated のみです。

## generated
- `YYYY/MM/diff_msdata_YYYYMMDD.md` : 日次の msData 差分
- `YYYY/MM/provenance_YYYYMMDD.json` : 生成元証跡（復元情報を含む）
- `YYYY/MM/label_audit_YYYYMMDD.md` : ラベル監査
- `YYYY/MM/index_ms_audit_YYYYMMDD.md` : index と msData の整合監査
- `skills_params_audit.json` / `owners_flat_audit.json` : skills系監査（直下・undated）

## manual
- `YYYY/MM/msdata_update_YYYYMMDD.md` : 週次/都度の人手更新レポート
- `README.md` / `index.md` / `msdata_update_template.md` : 運用メモ（直下）

## 参照先
- PR本文: `reports/YYYY/MM/diff_msdata_YYYYMMDD.md`
- Release asset: `raw_snapshot_YYYYMMDD_run<run_id>.tar.xz`
- provenance: `reports/YYYY/MM/provenance_YYYYMMDD.json`
