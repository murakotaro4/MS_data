# msData 更新レポート（2026-10-01）

## 取得・処理概要

- 確認日: 2026-10-01
- 対応: [Issue #290](https://github.com/murakotaro4/MS_data/issues/290)、[期限確認 #218](https://github.com/murakotaro4/MS_data/issues/218)
- 基準コミット: `33f6a63f82729456eb92d0a98f31fd90b3aedd67`
- ソース: 2026-09-06の全量取得snapshot、2026-10-01の定期取得snapshot、同日の独立した対象7ページの再取得
- データ差分: `records: 1719 -> 1719 | +0 -0 ~0`

## 追加・更新内容

### 一時公式補正の撤去

`data/official_overrides/20260723_balance.json` の全16エントリ・46値を撤去し、
ディレクトリは `.gitkeep` で維持する。新規機体の追加、既存レコードの更新はない。

この補正は2026-07-23の公式調整後、atwikiが一部の値を調整前へ戻したために
導入した一時措置だった。`review_after=2026-08-10`、`remove_after=2026-08-31`。
全対象値が上流に反映され、下記の独立した取得でも一致したため、存続を終了する。

### 撤去対象と確認値

表の値は補正値・保存済み取得値・今回の独立取得値・現在の `msData.json` が
すべて一致した値。`—` は補正の対象外。HP16値とスロット30値の合計46値。

| MS名 | HP | 近スロット | 中スロット | 遠スロット |
| --- | ---: | ---: | ---: | ---: |
| アマクサ_LV1 | 28000 | 25 | 19 | 11 |
| ガンダムMk-Ⅳ_LV1 | 20000 | — | — | — |
| ガンダムMk-Ⅳ_LV2 | 22000 | — | — | — |
| ドライセン_LV1 | 25000 | 19 | 16 | 8 |
| ドライセン_LV2 | 28000 | 21 | 17 | 9 |
| ドライセン_LV3 | 31000 | 25 | 19 | 11 |
| ドライセン_LV4 | 34000 | 27 | 21 | 13 |
| ハンマ・ハンマ_LV1 | 24000 | — | — | — |
| ハンマ・ハンマ_LV2 | 27000 | — | — | — |
| ハンマ・ハンマ_LV3 | 30000 | — | — | — |
| ハンマ・ハンマ_LV4 | 33000 | — | — | — |
| フルアーマー・オーヴェロン_LV1 | 29000 | 14 | 21 | 16 |
| フルアーマー・オーヴェロン_LV2 | 32000 | 15 | 23 | 17 |
| リバウ_LV1 | 24000 | 15 | 20 | 16 |
| リバウ_LV2 | 28000 | 18 | 23 | 19 |
| ローゼン・ズール_LV1 | 31000 | 19 | 21 | 16 |

## 撤去判断の根拠

### 全件再取得条件の確認

補正設定の `remove_when` は「atwiki の全件再取得結果が本オーバーライド値と
一致することを確認できた後に撤去する」だった。

2026-09-06の[品質レポート](../09/atwiki_quality_20260906.json)は
`mode=full`、当時の全591ページをHTTP 200で取得、失敗0件、キャッシュ利用0件を示す。
[監査レポート](../09/official_overrides_audit_20260906.md)でも `upstream_current=46`。
[Releaseのraw snapshot](https://github.com/murakotaro4/MS_data/releases/tag/raw-snapshot-20260906-run-34033450730)
を取得し、indexとdetailsのSHA-256を[provenance](../09/provenance_20260906.json)と照合した。
対象7ページの保存済みHTMLを現行パーサーで再解析し、detailsの値と合わせて46/46一致を確認した。

この保存済みの全量取得で既存の撤去条件を確認し、さらに現在の対象値を以下の2経路で確認した。
今回、全595ページの全量再取得は行っていない。

### 最新の取得証拠

[2026-10-01の定期取得](https://github.com/murakotaro4/MS_data/actions/runs/36737742740)では、
対象7ページを `official_override_due` の理由でネットワーク取得し、全46値が `match`。
取得・解析エラーと証拠不足は0件。保存済みHTMLの再解析でも46/46一致した。

- [監査レポートartifact](https://github.com/murakotaro4/MS_data/actions/runs/36737742740/artifacts/11108595051)
- [raw snapshot artifact](https://github.com/murakotaro4/MS_data/actions/runs/36737742740/artifacts/11107359162)
- [品質レポートartifact](https://github.com/murakotaro4/MS_data/actions/runs/36737742740/artifacts/11106904986)

2026-10-01 03:34:26〜03:34:29 JSTの独立した再取得も、HTTP 200が7/7、解析成功7/7、
一致46/46、不一致・欠損・エラー0件。既定のレート上限2 req/secで取得した。
以下は取得したHTMLボディのSHA-256。

| ページ | 対象値数 | HTML SHA-256 |
| --- | ---: | --- |
| [ハンマ・ハンマ](https://w.atwiki.jp/battle-operation2/pages/2451.html) | 4 | `dbad328bfca191ad6668f648eb54f6c35c718aaa429353b32df3d230787004d9` |
| [ドライセン](https://w.atwiki.jp/battle-operation2/pages/2509.html) | 16 | `adaeea3f5feac7783257313971da1f1ad2cf22a59ff47a66acd546e7d1498390` |
| [リバウ](https://w.atwiki.jp/battle-operation2/pages/4050.html) | 8 | `d75874b35173bb2395e72c249f4cbd45d2825a9f721620e1478b7233c08f4107` |
| [ガンダムMk-Ⅳ](https://w.atwiki.jp/battle-operation2/pages/4998.html) | 2 | `d8a7d55881d129298041c43aab56181efbbb8d68738ab838115413e84bb8d629` |
| [ローゼン・ズール](https://w.atwiki.jp/battle-operation2/pages/5354.html) | 4 | `6f820a88db875f79d62df6c59b376c9ebd7a7284aee084b93c735bda992bc365` |
| [フルアーマー・オーヴェロン](https://w.atwiki.jp/battle-operation2/pages/6505.html) | 8 | `715ce8968cf07ae042f838e5ae97db86ed11c71995b4ff23dda146d3baad680e` |
| [アマクサ](https://w.atwiki.jp/battle-operation2/pages/7116.html) | 4 | `2e11583308f266457d5cedcd835712c9a84d307efb745d6f89df2bd1fc5c514b` |

## 監査

- 撤去後の公式補正監査: 対象値0、`review_due=0`、`remove_due=0`、取得証拠不足0。
- 今日の実取得details（41レコード）を同じ基準データへ取り込み、撤去前・撤去後の補正設定で
  それぞれ出力した結果は、基準の1,719レコードとバイト単位で一致した。
- 基準データ・撤去前の出力・撤去後の出力のSHA-256:
  `140dbd9a9621eea0cd3a786558e3cdc85f420fec7b1579b46f2f5fd8f6506d91`
- この変更による `msData.json` の変更はない。

## 検証結果

- Python 3.11.12、`uv.lock` で同期した依存関係を使用。
- `env -u NO_NET uv run --locked python -m ms_data.tasks ci`: 成功、683テスト通過、カバレッジ88.37%。
  レポート契約・生成物・空の公式補正ディレクトリ・snapshot復元・Ruff・厳格なデータ検証を含む。
- `validate-strict`: 1,719レコード成功。`records: 1719 -> 1719 | +0 -0 ~0`。
- 撤去後の監査レポートを使って通知のテキスト本文とHTML本文を生成し、
  「公式補正の撤去判断期限到達」と「要確認」枠が出ないことを確認した。

生成本文での検証であり、定期通知の実際の配信結果はマージ後の定期実行で確認する。
