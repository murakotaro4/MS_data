# 取得元スロット監査

## 取得元スロット監査

- status: approved_correction
- held_record_count: 0
- approved_record_count: 1
- fallback_corrected_record_count: 0
- previous_unverified_count: 0

未承認異常は対象機体＋LV全体だけ更新を保留し、他レコードは通常継続します。
previous_unverified_retained は正常な前値なし・既存値も未確認／要対応です。
期限切れで22等を保持した場合は再補正ではなく前値保持です。
retained_previous_with_approved_correction は取得候補を保留し、承認済み補正で前値を修復して保持した状態です。
一般のLV比較だけでは取得元誤記と解析バグを確定できません。

## 部分保留エラー・補正証拠

| MS名 | LV | 項目 | 元値 | 比較値 | 前値 | 採用値 | 前値の承認修復 | 処置 | 前値状態 | 期限 | 取得時刻 | WikiURL | 理由 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ガブスレイ_LV2 | 2 | 中スロット | 12 | {"ガブスレイ_LV1": 20, "ガブスレイ_LV3": 24} | 12 | 22 | {} | approved_override | known_invalid | 2026-10-19 | 2026-10-04T14:37:53.324576+00:00 | https://w.atwiki.jp/battle-operation2/pages/2283.html | 本人確認済みの取得元誤記 / LV内点のスロット谷かつ下位LVより合計低下 |
