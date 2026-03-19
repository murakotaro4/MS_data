# バトオペ2 MS データ管理（msData.json）

本リポジトリは、機動戦士ガンダム バトルオペレーション2（バトオペ2）の機体ステータスを JSON（msData.json）で管理し、取得・正規化・検証・更新するためのスクリプト群を提供します。運用・設計の詳細は AGENTS.md を参照してください（本 README は要点を凝縮したクイックスタートです）。

## 特長
- atwiki の機体ページからステータスを抽出（キャッシュ対応、レート制御）
- 行見出し（項目名）の表記揺れを吸収して正規キーへ変換（FIELD_MAP）
- 出力 JSON の誤記キーを正規キーへ補正（KEY_ALIASES）
- 追加抽出: 出撃可否（地上/宇宙）・環境適正（地上/宇宙/水中）
- 旋回値の注記処理（例: 78（盾装備時：75.7）→ 78 を採用）
- 宇宙専用/地上専用の単一見出しを適切側に寄せる回転値の補正
- JSON Schema による検証（構造/型、別名キーの検出）

## ディレクトリ構成（抜粋）
- scripts/: 取得・更新・検証・監査スクリプト
  - scrape_msdata.py（index/details/labels）
  - update_msdata.py（正規化/マージ/出力）
  - validate_msdata.py（スキーマ/重複/別名）
  - audit_labels.py（ラベル揺れの集計）
  - cache_http.py（HTTPキャッシュ層）
  - label_utils.py（FIELD_MAP/KEY_ALIASES/正規化）
- schema/msData.schema.json: JSON Schema
- cache/: 取得物（HTMLキャッシュ/インデックス/詳細）
  - html/: ページキャッシュ（.html/.meta.json）
  - index.json / details.jsonl / details.json
  - samples/: サンプル出力（参考用）
- msData.json: データ本体
- AGENTS.md: 運用・設計の詳細（推奨参照）

## セットアップ
```bash
uv venv
uv sync --dev
```

## よく使うコマンド（推奨）
- 品質チェック: `uv run python -m scripts.tasks ci`
- 検証: `uv run python -m scripts.tasks validate`
- 厳格検証: `uv run python -m scripts.tasks validate-strict`
- skills 系検証: `uv run python -m scripts.tasks validate-skills`
- 一覧取得: `uv run python -m scripts.tasks scrape-index TTL=7d`
- 詳細取得: `uv run python -m scripts.tasks scrape-details TTL=7d RATE=2.0 LIMIT=0`
- 取り込み: `uv run python -m scripts.tasks import-details`
- ラベル監査: `uv run python -m scripts.tasks labels LIMIT=0` → `uv run python -m scripts.tasks audit-labels`
- スキル抽出: `uv run python -m scripts.tasks skills TTL=7d`
- 整形のみ: `uv run python -m scripts.tasks normalize`
- reports 契約検証: `uv run python -m scripts.validate_report_contract --mode ci --manifest reports_manifest.yml --reports-dir reports`

## reports 運用（要点）
- 生成物/手動レポートの分類と命名契約は `reports_manifest.yml` を SSOT とします。
- `reports/index.md` と `reports/README.md` は運用導線（latest 参照先・互換期間・撤去条件）を記載します。
- workflow/CI は `scripts.validate_report_contract` で命名・整合性を検証します。

## Makefile（補助）
- `make` は Linux/macOS 向けの薄いラッパーです。Windows では `uv run python -m scripts.tasks <target>` を優先してください。
- 例: `make ci`, `make validate-strict`, `make scrape-details RATE=2.0`

TTL: 既定 7日（`TTL=7d`）。オフライン時は `NO_NET=1`、強制更新は `FORCE=1` を付与。

## スキーマ要点（msData.schema.json）
- 必須（抜粋）: `MS名`, `属性`（汎用/強襲/支援）, `コスト`, `HP`, `スピード`, `スラスター`, `高速移動`, `射撃補正`, `格闘補正`, `耐*補正`, `近/中/遠スロット`
- 旋回の必須条件: anyOf（`旋回_地上_通常時` または `旋回_宇宙_通常時` のどちらか必須）
- 任意の追加項目（抜粋）:
  - 速度系: `スピード_変形時`, `高速移動_変形時`
  - 旋回系: `旋回_地上_変形時`, `旋回_宇宙_変形時`, `旋回_変形時`
  - 補正系: `射撃補正_変形時`, `射撃補正_変身時`, `格闘補正_変形時`, `格闘補正_変身時`
  - 購入系: `レアリティ`, `必要階級`, `必要DP`, `必要リサイクルチケット`
  - 出撃可否: `出撃_地上可`, `出撃_宇宙可`
  - 環境適正: `環境適正_地上`, `環境適正_宇宙`, `環境適正_水中`

## 正規化・補正ポリシー（抜粋）
- 行見出しの軽正規化: 余白圧縮、半角()注記の除去（全角（）は保持）
- 数値抽出: 整数に統一（単位・記号を除去）。例: 78（盾装備時：75.7）→ 78
- 出撃可否の推定: label_sortie が無い場合は旋回の有無から補完
- 回転値の補正: 宇宙専用/地上専用で単一見出しが逆側に入っている場合は適切側に寄せ替え
- 誤記キー補正（KEY_ALIASES）: 例）射撃補則/射撃補生 → 射撃補正

## 取得時の注意
- レート制限: 推奨 2 req/sec（`RATE=...` または `--rate` で調整）
- キャッシュ: TTL=7日、304対応、`--no-network` でオフライン解析可
- robots.txt/サイトの利用規約・礼節を守った取得を推奨

## コントリビュート
- フォーマット: `uv run black .`
- リント: `uv run ruff check .`
- テスト: `uv run pytest -q`
- 統合チェック: `uv run python -m scripts.tasks ci`
- コミット規約: Conventional Commits（feat/fix/docs/chore/data…）
- ブランチ運用: 大きめ変更時は `data/update-YYYYMMDD` 等を推奨（小変更は main 直でも可）

## ライセンス
-（プロジェクトのポリシーに合わせて追記してください）

---
詳細は AGENTS.md を参照ください（仕様・設計・運用の全体像を網羅）。
