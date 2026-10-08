- 実行日: 20261008
- 結果: 部分保留エラー（対応要・正常な更新候補は通常レビュー継続）
- msData.json変更: false
- candidate_count: 73
- fast_path: true
- age_coverage: 1.0
- fallback_reason: none

# 取得元スロット監査

## 取得元スロット監査

- status: partial_hold
- held_record_count: 1
- approved_record_count: 0
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
| 表示確認機_LV2 | 2 | 中スロット | 12 | {"表示確認機_LV1": 20, "表示確認機_LV3": 24} | 22 | 22 | {} | retained_previous |  |  | 2026-10-08T09:00:00+00:00 | https://example.test/wiki |  / LV内点のスロット谷かつ下位LVより合計低下 |
