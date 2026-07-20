# data/

スキル定義・所持データ・監査許容リスト・公式オーバーライドの置き場です。

## JSON ファイル

| ファイル | 生成 or 手動 | 役割 | 生成ターゲット | 対応スキーマ |
| --- | --- | --- | --- | --- |
| `skills_catalog.json` | 生成 | スキル一覧カタログ | `build-skills` | `schema/skills_catalog.schema.json` |
| `skill_owners.json` | 生成 | スキル所持機体（シリーズ単位） | `build-skills` | `schema/skill_owners.schema.json` |
| `skill_owners_flat.json` | 生成 | スキル×機体 Lv 展開した所持データ | `build-owners-flat` | `schema/skill_owners_flat.schema.json` |
| `skills_params.json` | 生成 | パラメータ変化スキルの定義 | `build-param-skills` | `schema/skills_params.schema.json` |
| `skills_policy.json` | 手動 | 抽出対象スキルの方針（SSOT） | — | — |
| `field_completeness_allowlist.json` | 手動 | フィールド完全性監査の許容リスト（SSOT） | — | — |

生成ターゲットは `uv run python -m ms_data.tasks <target>` で実行します。生成 4 ファイルのスキーマ検証は `validate-skills` です。

## official_overrides/

公式バランス調整を atwiki 反映前に先行適用するオーバーライド置き場です。

**通常は空（`.gitkeep` のみ）が正常です。** atwiki へ反映され次第 entry を撤去し、全 entry 撤去後はファイルごと削除する運用のためです。期限管理は各 entry の `review_after` / `remove_after` で行います。詳細は [AGENTS.md](../AGENTS.md) を参照してください。
