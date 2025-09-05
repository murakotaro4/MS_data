# Repository Guidelines

## 言語ポリシー
- 本リポジトリのコミュニケーションは原則「日本語」です（Issue/PR/コメント/ドキュメント/コミットメッセージ）。本ガイドも日本語で提供します。

## プロジェクト構成・モジュール整理
- 目的: 本リポジトリは主に `msData.json` を管理します。将来的に更新用の Python スクリプトを追加します。
- 推奨構成:
  - `scripts/`: データ更新・検証スクリプト（Python）。
  - `tests/`: スクリプトのユニットテスト。
  - `schema/`: JSON スキーマ（任意、バリデーション用）。
  - `data/`（任意）: 原データや一時生成物。
  - `pyproject.toml`: 依存とツール設定（uv 管理）。

## ビルド・テスト・開発コマンド（uv）
- 環境作成: `uv venv`（任意で `-p 3.11`）。実行は基本 `uv run <cmd>` を使用。
- 依存追加: `uv add black ruff pytest jsonschema`（`pyproject.toml` に記録）。
- JSON 構文チェック: `jq . msData.json > /dev/null` または `uv run python -m json.tool msData.json > /dev/null`
- 整形・キーソート: `jq -S '.' msData.json > msData.pretty.json`
- テスト: `uv run pytest -q`（`tests/` 配下）
- フォーマット/リンタ: `uv run black . && uv run ruff .`

### Makefile（ショートカット）
- 初期化: `make setup`
- 更新: `make update INPUT=path/to/new.json`（入力なしで正規化のみ）
- 検証: `make validate`（厳格: `make validate-strict`）
- 品質チェック: `make format && make lint && make test` または `make ci`

## スクレイピング手順（atwiki）
- 一覧取得: `uv run python scripts/scrape_msdata.py index --url https://w.atwiki.jp/battle-operation2/pages/377.html --out cache/index.json`
- 詳細取得: `uv run python scripts/scrape_msdata.py details --in cache/index.json --out cache/details.jsonl --rate 1.0`
- 連続実行: `uv run python scripts/scrape_msdata.py all --out cache/details.jsonl`
- 取り込み: `jq -s '.' cache/details.jsonl > cache/details.json && uv run python scripts/update_msdata.py -i cache/details.json`

## コーディング規約・命名
- JSON: 2スペース、UTF-8、LF、キーは `snake_case`。
- Python: インデント4スペース、型ヒント必須、関数は純粋/再利用可能に。
- 命名: ファイル/関数は lower_snake_case、クラスは CapWords。
- データファイル名: `dataset_<topic>_<YYYYMMDD>.json`（例: `dataset_ms_20250115.json`）。
- ツール: `black`（88列）/`ruff`/`pytest` を uv で管理。必要に応じて `mypy`。

## テスト方針
- `tests/` に配置。命名は `test_*.py`。
- 変換/検証ロジックは目安80%以上をカバー。エッジケースと不正入力を含める。
- スキーマ導入時（例: `schema/msData.schema.json`）は CI で `jsonschema` などによる検証を実施。

## データ仕様・取得対象（msData.json）
- 構造: 配列（各要素=MSの1レベル）。主キー相当: `MS名`（例: `XXX_LV1`）。
- 必須項目: `MS名`, `属性`（汎用/強襲/支援）, `コスト`, `HP`, `スピード`, `スラスター`, `高速移動`, `射撃補正`, `格闘補正`, `耐ビーム補正`, `耐実弾補正`, `耐格闘補正`, `近スロット`, `中スロット`, `遠スロット`, `旋回_地上_通常時`（可能なら `旋回_宇宙_通常時`）。
- 追加項目: `カウンター`（文字列）, `再出撃時間`（秒・任意）, `fullst`（`[{name, level}]` の配列）。
- `fullst` 取得ルール: 各機体ページの「強化リスト情報」表から抽出。通常強化の最小Lv（多くはLv1）と上限開放の最大Lv（Lv4以上があれば）を採用します。
- 正規化ルール（表記揺れ吸収）:
  - `射撃補則`/`射撃補生` → `射撃補正`、`格闘補定` → `格闘補正`
  - `旋回_通常時_地上` → `旋回_地上_通常時`、`旋回_通常時_宇宙` → `旋回_宇宙_通常時`
  - `格闘判定力` は原文保持＋任意で正規化（例: 弱/中/強/強+）。
- 値の目安: `コスト` 200–750、`HP` 11,000–34,000、`スピード` 75–160、`高速移動` 150–235（2025-09 時点のデータより）。

## データ更新フロー（推奨）
1) ブランチ作成: `git switch -c data/update-YYYYMMDD`
2) データ取得・変換: `uv run python scripts/update_msdata.py -i [入力JSON…]` で `msData.json` を生成/更新。
3) 整形固定: `jq -S '.' msData.json > msData.json.tmp && mv msData.json.tmp msData.json`
4) 検証: `uv run python scripts/validate_msdata.py msData.json` と `uv run pytest -q`
5) 差分確認: `git diff -- msData.json`（件数/キー変更点を要約）
6) コミット: `data: update msData.json (YYYY-MM-DD; +N/-M records)`
7) PR: 変更概要・データ来歴・統計（件数/キー変更）を記載。

## 取得元と更新頻度（推奨）
- 取得元: 公式リリースノート/ゲーム内ステータス/信頼できる Wiki。
- 更新頻度: 公式アップデートごと。バランス調整時は速やかに反映。
- 監査: 重要指標（補正・耐性・コスト）の差分は PR 説明に数値で記載。

## コミット・プルリクエスト
- Conventional Commits を採用: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `data:`（データのみ変更）。
- PR は小さく焦点を絞る。含める内容:
  - 変更概要とデータ来歴（ソース/取得日/処理手順）。
  - サンプルレコードや前後比較の統計（行数/ハッシュ差分）。
  - 関連 Issue、再現手順、UI/可視化が変わる場合はスクリーンショット。

## セキュリティ・データ運用
- 秘密情報や個人情報をコミットしない。`.env` 等は `.gitignore` へ。
- 10MB 超やバイナリは Git LFS を使用: `git lfs track "data/**" "*.csv" "*.parquet"`。
- 再現性を重視: 依存関係のピン留め、乱数シード固定、デフォルト実行での外部ネットワーク依存を回避。
