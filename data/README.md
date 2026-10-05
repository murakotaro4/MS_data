# data/

監査許容リスト・公式オーバーライドの置き場です。

## JSON ファイル

| ファイル | 生成 or 手動 | 役割 | 生成ターゲット | 対応スキーマ |
| --- | --- | --- | --- | --- |
| `field_completeness_allowlist.json` | 手動 | フィールド完全性監査の許容リスト（SSOT） | — | — |

## official_overrides/

公式バランス調整を atwiki 反映前に先行適用するオーバーライド置き場です。

本人確認済みの取得元誤値も、確認日・根拠URL・`stale_values`の一致条件を付けて
期限付きで補正できます。`source_error_confirmed: true`、または正当なスロット谷の
例外承認`allow_source_anomaly: true`には`expires_after`が必要です（entryまたはファイルで指定）。
`expires_after`はJSTで当日まで補正を適用し、以後は適用しません。従来の`review_after`
（再確認日）と`remove_after`（撤去判断日）は通知の期限で、適用停止日には変更しません。
既知誤値の保留根拠は適用期限後も読み込まれるため、取得元の訂正を確認してから定義を撤去します。

`20261005_source_slot_correction.json`はガブスレイLV2中スロット12→22だけが対象です。
本人確認日2026-10-05、再確認日2026-10-12、適用期限・撤去判断日2026-10-19。
第三値を上書きせず、保存HTMLの12と採用値22は別々に監査へ残します。

**通常は空（`.gitkeep` のみ）が正常です。** atwiki へ反映され次第 entry を撤去し、全 entry 撤去後はファイルごと削除する運用のためです。期限管理は各 entry の `review_after` / `remove_after` で行います。詳細は [AGENTS.md](../AGENTS.md) を参照してください。
