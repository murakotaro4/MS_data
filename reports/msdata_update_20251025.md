# msData 更新レポート（2025-10-25）

## 取得・処理概要
- 取得日: 2025-10-25
- ソース: atwiki モビルスーツ一覧（index）および各機体ページ
- 実行手順:
  - `TTL=1d FORCE=1 make scrape-index`
  - `TTL=1d FORCE=1 make scrape-details`
  - `uv run python - <<'PY' ...`（`cache/details.jsonl` を配列 JSON へ変換）
  - `uv run python -m scripts.update_msdata -i cache/details.json`
  - `uv run python -m scripts.update_msdata -i`
  - `make validate-strict`
  - `make audit-labels`
  - `make audit-index`
- 差分サマリ: `records: 1525 -> 1532 | +7 -0 ~21`

## 追加・更新内容
### 新規追加
- ペイルライダー・デュラハン_LV3（コスト500／強襲）: Lv3 を登録。主要パラメータと強化リストを補完。
- アマクサ_LV1（コスト700／汎用）: 新規機体。宇宙適正あり、格闘補正50／高速移動225を確認。
- Hi-νガンダム_LV2（コスト750／汎用）: Lv2 を追加、再出撃16秒・宇宙適正あり。
- MSN-04FF サザビー_LV2（コスト750／支援）: Lv2 を追加、射撃補正44・高速移動210を登録。
- RX-93ff νガンダム_LV2（コスト750／強襲）: Lv2 を追加、スピード140／高速移動225。
- νガンダム［HWS装備］_LV2（コスト750／支援）: Lv2 を追加、射撃補正50。
- ゲーマルク_LV3（コスト750／支援）: Lv3 を登録、スピード110／高速移動210。

### 既存レコードの主な更新
- ジムⅢ（LV1〜4）: スピード・高速移動・スラスター・旋回・スロットを一律強化。
- ゼク・アイン［第3種兵装］（LV1〜4）: HPと全スロット構成を上方修正。
- ゲーマルク（LV1〜2）: スピード/高速移動/スラスター/旋回/スロットを上方修正。
- ガズエル・グラウ（LV1〜2）: HPとスロット（LV2は射撃補正含む）を調整。
- リガズィード（LV1〜2）: HPをそれぞれ +1000/+2500。
- ザク・マシーナリー（EB）（LV1〜2）: HPをそれぞれ +2000/+2500。
- キュベレイMk-Ⅱ_LV1: HPを +1000。
- RX-93ff νガンダム_LV1: スピードを 140 に上方修正。
- フルアーマー・アレックス_LV2: 強化リストの必要ポイントを数値化し、リサチケ175を登録。
- EWACネロ_LV1: リサチケ135を登録。
- ジェダキャノン_LV2: 必要階級（中尉10）とDP 147,800を補完。

## 監査
- `reports/label_audit_20251025.md`: ページ535件、normalized 42種、unknown=0 を確認。
- `reports/index_ms_audit_20251025.md`: index 535件 / msData 538件（PC版3件を除き差異なし、属性・コスト不一致0）。

## 検証結果
- `make validate-strict`: OK（1532件）
- 追加監査: ラベル揺らぎ監査 unknown=0、index vs msData 監査で不整合なし。

## 差分ファイル
- `msData.json`（+516 / -79）
- キャッシュ: `cache/index.json`, `cache/details.jsonl`, `cache/details.json`
- レポート: `reports/label_audit_20251025.md`, `reports/index_ms_audit_20251025.md`, `reports/msdata_update_20251025.md`

## 備考
- `jq` 非導入環境のため、JSONL→JSON 変換は Python ワンライナーで実施。
