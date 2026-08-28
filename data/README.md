# data/

監査許容リスト・公式オーバーライドの置き場です。

## JSON ファイル

| ファイル | 生成 or 手動 | 役割 | 生成ターゲット | 対応スキーマ |
| --- | --- | --- | --- | --- |
| `field_completeness_allowlist.json` | 手動 | フィールド完全性監査の許容リスト（SSOT） | — | — |

## official_overrides/

公式バランス調整を atwiki 反映前に先行適用するオーバーライド置き場です。

**通常は空（`.gitkeep` のみ）が正常です。** atwiki へ反映され次第 entry を撤去し、全 entry 撤去後はファイルごと削除する運用のためです。期限管理は各 entry の `review_after` / `remove_after` で行います。詳細は [AGENTS.md](../AGENTS.md) を参照してください。
