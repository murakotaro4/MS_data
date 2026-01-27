# CLAUDE.md - MS_data プロジェクト設定

## プロジェクト概要
本リポジトリは `msData.json`（ゲーム内MS機体データ）を管理する Python プロジェクトです。
atwiki からのスクレイピング、データ正規化、検証を行います。

## 言語ポリシー
- 日本語を原則とします（Issue/PR/コメント/ドキュメント/コミットメッセージ）

## ビルド・テストコマンド（uv）

```bash
# 環境作成
uv venv

# テスト
uv run pytest -q

# フォーマット/リンタ
uv run black . && uv run ruff check .

# 検証
make validate          # 通常
make validate-strict   # 厳格

# 品質チェック一括
make ci
```

## スクレイピング手順

```bash
# 一覧取得
make scrape-index TTL=7d

# 詳細取得
make scrape-details TTL=7d RATE=1.0 LIMIT=0

# 取り込み
make import-details

# 監査
make audit-labels
```

## データ更新フロー（推奨）
1. ブランチ作成: `git switch -c data/update-YYYYMMDD`
2. 取得: `make scrape-details TTL=7d RATE=1.0 LIMIT=0`
3. 取り込み: `make import-details`
4. 検証: `make validate-strict`
5. 差分確認: `git diff -- msData.json`
6. コミット/PR

## コーディング規約
- JSON: 2スペース、UTF-8、LF、キーは `snake_case`
- Python: インデント4スペース、型ヒント必須
- 命名: ファイル/関数は lower_snake_case、クラスは CapWords

## コミットメッセージ
Conventional Commits を採用（日本語）:
- `data:` データのみ変更
- `feat:` 新機能
- `fix:` バグ修正
- `docs:` ドキュメント
- `chore:` 雑務
- `refactor:` リファクタリング
- `test:` テスト

## 参照
詳細は `AGENTS.md` を参照してください。
