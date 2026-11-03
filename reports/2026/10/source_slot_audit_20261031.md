# 取得元スロット監査

## 取得元スロット監査

- status: ok
- held_record_count: 0
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
| なし |  |  |  |  |  |  |  |  |  |  |  |  |  |
