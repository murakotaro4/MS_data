# schema/

JSON Schema とレポート契約スキーマの置き場です。検証は `uv run python -m ms_data.tasks <target>` で実行します。

| スキーマ | 検証対象 | 検証コマンド |
| --- | --- | --- |
| `msData.schema.json` | `msData.json` | `validate` / `validate-strict` |
| `official_overrides.schema.json` | `data/official_overrides/*.json` | `validate-official-overrides-schema` |
| `reports_manifest.schema.json` | `reports_manifest.json` | `validate-report-contract`（JSON Schema を直接使用せず手書き検証） |
| `reports/atwiki_quality.schema.json` | `reports/atwiki_quality_*.json` | `validate-generated-reports` |
| `reports/provenance.schema.json` | `reports/provenance_*.json` | `validate-generated-reports` |
| `reports/auto_review.schema.json` | `reports/auto_review_*.json` | `validate-generated-reports` |

レポート生成物のファイル名パターンは、現行の `reports_manifest.json` 表記に合わせています。

`msData.json` の人間可読なフィールド解説は [docs/msdata_reference.md](../docs/msdata_reference.md) を参照してください。
