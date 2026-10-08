# 日次通知の表示例

送信せずに生成したHTMLとプレーンテキストです。`no-change`は20261008の元メールで確認された件数だけを再現し、監査明細にない機体・LV・値を特定していません。他の例の「表示確認機」は表示検証用の架空データで、本日の取得結果を表すものではありません。

| ケース | HTML | テキスト | 確認する点 |
| --- | --- | --- | --- |
| 差分なし | [no-change.html](no-change.html) | [no-change.txt](no-change.txt) | 結果・対応要否が先頭。補正維持1と選定73ページを区別 |
| 変更あり | [changed.html](changed.html) | [changed.txt](changed.txt) | 機体/LV別の変更前後・増減量 |
| 部分保留 | [partial-hold.html](partial-hold.html) | [partial-hold.txt](partial-hold.txt) | 対象・原値・比較値・前値保持・理由・次の対応 |
| 監査期限あり | [audit-due.html](audit-due.html) | [audit-due.txt](audit-due.txt) | 期限到達は未処理。未取得を踏まえて撤去判断を案内 |
| 監査欠損 | [audit-missing.html](audit-missing.html) | [audit-missing.txt](audit-missing.txt) | 未取得を明示し、0件・確認不要と表示しない |

再生成（Python 3.11・locked依存）:

```sh
uv run --locked python -m scripts.preview_update_mail --out-dir docs/notification_examples
```

`*-390.png`はスマホ幅390px、`*-900.png`はデスクトップ幅900pxのChromiumレンダーです。`*-inline-only-390.png`はheadのCSSを除去した状態です。5例×3条件の横幅・文字サイズ・外部資源検証は`render-checks.json`に記録します。実際のGmailへの試験送信は行っていません。

環境にPlaywrightとChromiumが導入済みの場合、`node scripts/render_update_mail_previews.cjs docs/notification_examples`でレンダーと検証記録を再生成できます。

元メールの監査artifactは[実行37649017623](https://github.com/murakotaro4/MS_data/actions/runs/37649017623)の`operational-reports-20261008-run-37649017623`（ID11494934505）です。作業環境からのZIP取得が通信制限で403となったため、本日の保護対象の特定根拠には使っていません。通常実行では、渡された監査Markdownの明細がある範囲で対象・値・期限・取得証拠を通知へ取り込みます。
