# 2025-10-11 週次更新レポート

## 実施概要
- `msData.json`: 1522 → 1524 レコード（+2 / -0 / ~4）
- 基底MS数: 535 → 536（新規1機体追加）
- atwiki の index/details/labels を FORCE=1 で再取得し、`scripts.update_msdata` で取り込み（JSONL→JSON は Python ワンライナーを使用）
- 取り込み結果: `records: 1522 -> 1524 | +2 -0 ~4`

## 実行コマンド
- `make scrape-index FORCE=1 TTL=1d`
- `make scrape-details FORCE=1 TTL=1d RATE=1.0 LIMIT=0`（約9分・1516件取得）
- `uv run python - <<'PY' ...`（JSONL → JSON 変換）
- `uv run python -m scripts.update_msdata -i cache/details.json`
- `make validate-strict`
- `make labels FORCE=1 LIMIT=0 TTL=1d`
- `make audit-labels`
- `make audit-index`

## 新規追加・レベル拡張
- **Gキャノン・マグナ_LV1**（支援/650）: HP 22,000・スピード130・高速移動210、宇宙適正〇／地上可。強化リストは耐ビ・AD-FCS・プロペラント・複合（各ポイント付）を確認。
- **ガンダムデルタアンス_LV2**（汎用/650）: HP 22,000・スピード135・高速移動215、両戦場対応。強化リストは耐ビ・AD-PA・プロペラント・複合（ポイント付）。

## 既存機体の更新点
- **ショップ関連**
  - グフ・フライトタイプ_LV4: 必要リサイクルチケット `160`
  - ジェガン（CH）_LV1: 必要DP `132,400`, 必要階級 `中尉01`
- **強化リスト補完**
  - RFグフ_LV2: AD-PA/耐格/冷却/複合の各ポイント値を追加
  - ΖプラスA1型_LV4: AD-PA/冷却補助/プロペラント/複合の各ポイント値を追加

## 検証結果
- `make validate-strict`: OK（1524 レコード）
- `reports/label_audit_20251011.md`: ページ数 533 / normalized 42 / unknown 0
- `reports/index_ms_audit_20251011.md`: index 533 件 / msData 535 件、差分は PC 版3件のみ（属性・コスト不一致なし）

## 備考
- FORCE=1 指定によりキャッシュを無視して再取得。スクレイピングはタイムアウト扱いだが JSONL 出力は完了。
- `make import-details` 相当は Python ワンライナーで代替（`jq` 未導入のため）。
