# msData 更新レポート（2025-10-23）

## 取得・処理概要
- 取得日: 2025-10-23
- ソース: atwiki モビルスーツ一覧（index）および各機体ページ
- 実行手順:
  - `make scrape-index`
  - `make scrape-details`
  - `uv run python - <<'PY' ...`（`cache/details.jsonl` を配列 JSON へ変換）
  - `PYTHONPATH=. uv run python -m scripts.update_msdata -i cache/details.json`
  - `make validate-strict`
  - `make audit-index`
- 差分サマリ: `records: 1524 -> 1525 | +1 -0 ~11`

## 追加・更新内容
### 新規追加
- ジェガン［バーナム所属機］_LV1（コスト600／汎用）  
  出撃適性・主要ステータス・強化リスト・wiki URL を登録。

### 既存レコードの主な更新
- ザクⅠ（GS）_LV1: 必要DP=59,800 を補完。
- ザクⅠ（GS）_LV4: 必要階級を「曹長10」に補完。
- ゲルググG_LV1 / ガンキャノン重装型タイプD_LV1: 必要リサイクルチケットを35に修正。
- ネモ_LV4: 必要リサイクルチケットを140に設定。
- アクト・ザク_LV4: 必要リサイクルチケットを115に設定。
- ジム［WD隊仕様］_LV4: 必要階級を「少尉10」、必要DPを76,500に補完。
- ジム・スナイパーⅡ［WD隊仕様］_LV4: 必要階級を「少尉10」、必要DPを78,400に補完。
- ギャン・エーオース_LV4: 必要階級を「少尉10」、必要DPを78,400に補完。
- パラス・アテネ_LV2: 必要リサイクルチケットを75に修正。
- Ζガンダム［HML］_LV1: HPを16,000に修正。
- リ・ガズィ・カスタム_LV4: 強化リストの必要ポイントを具体値で補完。

### 監査
- `reports/index_ms_audit_20251023.md` を生成。index との差分（名称・属性・コスト・収載）の不整合は無し。

## 検証結果
- `make validate-strict`: OK（1525件）
- `scripts/update_msdata.py` による整形済み（2スペース、キー順固定）
- 追加監査: index vs msData 監査で差異無し

## 差分ファイル
- `msData.json`（+84 / -17）
- キャッシュ: `cache/index.json`, `cache/details.jsonl`, `cache/details.json`（再取得）
- レポート: `reports/index_ms_audit_20251023.md`, `reports/msdata_update_20251023.md`
