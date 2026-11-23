# 取得元抜粋

- report_date: 20261124

atwiki は Cloudflare により外部エージェントからの直接閲覧ができないため、Actions が取得した HTML（`cache/html`）から変更項目の該当行を抜粋しています。レビュー時の取得元照合はこの抜粋を使ってください。`不一致` は公式調整オーバーライド・LV単位保留・前LV補完などの後処理が入った可能性を示し、直ちに誤りを意味しません。

## サマリ

- excerpt_rows: 2
- source_pages: 2
- match: 2
- mismatch: 0
- no_row: 0
- html_missing: 0

## 取得元ページ

| 機体 | wiki_url | 取得時刻 | HTTP | content_sha256 |
| --- | --- | --- | --- | --- |
| ディジェ（CA） | https://w.atwiki.jp/battle-operation2/pages/3116.html | 2026-11-23T20:51:23.464977+00:00 | 200 | 508b0c1d6486 |
| フリント | https://w.atwiki.jp/battle-operation2/pages/7780.html | 2026-11-23T20:51:18.410679+00:00 | 200 | 7beda79add0a |

## 変更項目の抜粋

| MS名 | LV | 項目 | 変更前 | 変更後 | 取得元（該当LV） | 照合 | 取得元の行（全LV） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ディジェ（CA）\_LV2 | LV2 | 必要リサイクルチケット | 465 | 85 | 85 | 一致 | 必要リサイクル チケット: LV1=85 / LV2=85 |
| フリント\_LV2 | LV2 | fullst | \[{"name": "プロペラントタンク", "level": 1, "points": null}, {"name": "複合拡張パーツスロット", "level": 1, "points": null}, {"name": "耐実弾装甲補強", "level": 1, "points": null}, {"name": "AD\-PA", "level": 1, "points": null}, {"name": "耐実弾装甲補強", "level": 3, "points": null}, {"name": "AD\-PA", "level": 3, "points": null}\] | \[{"name": "プロペラントタンク", "level": 1, "points": 570}, {"name": "複合拡張パーツスロット", "level": 1, "points": 1150}, {"name": "耐実弾装甲補強", "level": 1, "points": 1730}, {"name": "AD\-PA", "level": 1, "points": 2310}, {"name": "耐実弾装甲補強", "level": 3, "points": 4620}, {"name": "AD\-PA", "level": 3, "points": 6930}\] | \[{\\"name\\": \\"プロペラントタンク\\", \\"level\\": 1, \\"points\\": 570}, {\\"name\\": \\"複合拡張パーツスロット\\", \\"level\\": 1, \\"points\\": 1150}, {\\"name\\": \\"耐実弾装甲補強\\", \\"level\\": 1, \\"points\\": 1730}, {\\"name\\": \\"AD\-PA\\", \\"level\\": 1, \\"points\\": 2310}, {\\"name\\": \\"耐実弾装甲補強\\", \\"level\\": 3, \\"points\\": 4620}, {\\"name\\": \\"AD\-PA\\", \\"level\\": 3, \\"points\\": 6930}\] | 一致 | 強化リスト情報: LV1=\[{\\"name\\": \\"プロペラントタンク\\", \\"level\\": 1, \\"points\\": 490}, {\\"name\\": \\"複合拡張パーツスロット\\", \\"level\\": 1, \\"points\\": 990}, {\\"name\\": \\"耐実弾装甲補強\\", \\"level\\": 1, \\"points\\": 1480}, {\\"name\\": \\"AD\-PA\\", \\"level\\": 1, \\"points\\": 1980}, {\\"name\\": \\"耐実弾装甲補強\\", \\"level\\": 3, \\"points\\": 3960}, {\\"name\\": \\"AD\-PA\\", \\"level\\": 3, \\"points\\": 5940}\] / LV2=\[{\\"name\\": \\"プロペラントタンク\\", \\"level\\": 1, \\"points\\": 570}, {\\"name\\": \\"複合拡張パーツスロット\\", \\"level\\": 1, \\"points\\": 1150}, {\\"name\\": \\"耐実弾装甲補強\\", \\"level\\": 1, \\"points\\": 1730}, {\\"name\\": \\"AD\-PA\\", \\"level\\": 1, \\"points\\": 2310}, {\\"name\\": \\"耐実弾装甲補強\\", \\"level\\": 3, \\"points\\": 4620}, {\\"name\\": \\"AD\-PA\\", \\"level\\": 3, \\"points\\": 6930}\] |
