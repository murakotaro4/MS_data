# バトオペ2 MS データ（msData.json）

[![CI](https://github.com/murakotaro4/MS_data/actions/workflows/ci.yml/badge.svg)](https://github.com/murakotaro4/MS_data/actions/workflows/ci.yml)
[![data update](https://github.com/murakotaro4/MS_data/actions/workflows/data_update.yml/badge.svg)](https://github.com/murakotaro4/MS_data/actions/workflows/data_update.yml)
[![License](https://img.shields.io/github/license/murakotaro4/MS_data)](LICENSE)

機動戦士ガンダム バトルオペレーション2 の全機体ステータスを atwiki から毎日自動取得・正規化・検証し、`msData.json` として公開する Python プロジェクトです。約 1,670 レコード（機体×レベル）。

## データを使いたい方へ

最新データ（raw）:

```text
https://raw.githubusercontent.com/murakotaro4/MS_data/main/msData.json
```

- 形式: JSON 配列
- 1 要素 = 機体の 1 レベル分のステータス
- 主キー: `MS名`（例: `XXX_LV1`）

フィールド詳細は [docs/msdata_reference.md](docs/msdata_reference.md)、機械検証は [schema/msData.schema.json](schema/msData.schema.json)。`data/skills*.json` は 2026-08 に廃止しました。過去データは git 履歴を参照してください。

Release（`raw-snapshot-*`）は取得時の生 HTML スナップショットと差分レポートの保存先です。`msData.json` 本体は上記 raw URL で取得してください（Release には含まれません）。

## 出典・免責

出典: [バトオペ2 攻略 atwiki](https://w.atwiki.jp/battle-operation2/)。ゲーム内情報の権利は原権利者に帰属します。本リポジトリは非公式で、正確性を保証しません。コードは [MIT](LICENSE) ですが、`msData.json` 等のゲームデータ部分は MIT の対象外です。取得は 2 req/sec のレート制限とキャッシュで取得先へ配慮しています。

## 自動更新の仕組み

毎日 18:00 JST に GitHub Actions が atwiki を取得し、差分があれば PR 作成 → Codex 自動レビュー → 自動マージ → Release 保存・メール通知を行います。失敗時は `notify failure` がメールと Issue で通知します。詳細は [AGENTS.md](AGENTS.md)。

## 開発者向けクイックスタート

前提: Python 3.11+ / [uv](https://github.com/astral-sh/uv)

```bash
uv venv
uv sync --dev
```

第一コマンド: `uv run python -m ms_data.tasks <target>`

| ターゲット | 用途 |
| --- | --- |
| `ci` | 品質チェック一括 |
| `validate` / `validate-strict` | 検証 |
| `scrape-index` / `scrape-details` | 一覧・詳細取得 |
| `import-details` | 取り込み |

環境変数: `TTL`（既定7日）/ `RATE`（既定2.0）/ `LIMIT`（0=全件）/ `NO_NET=1` / `FORCE=1`

手動データ更新:

1. `git switch -c data/update-YYYYMMDD`
2. `uv run python -m ms_data.tasks scrape-details TTL=7d RATE=2.0 LIMIT=0`
3. `uv run python -m ms_data.tasks import-details`
4. `uv run python -m ms_data.tasks validate-strict`
5. `git diff -- msData.json` → コミット / PR

## ディレクトリ構成（抜粋）

- `ms_data/`: Python パッケージ本体
  - `core/` 共通ユーティリティ / `net/` HTTP・キャッシュ / `scraping/` atwiki 取得
  - `pipeline/` 取り込み・正規化 / `validation/` 検証 / `audit/` 監査
  - `reporting/` レポート生成 / `gh/` GitHub 連携 / `notify/` メール
  - `tasks.py`: 全ターゲットのディスパッチャ
- `tests/`: ユニットテスト
- `schema/`: JSON Schema（→ [schema/README.md](schema/README.md)）
- `data/`: 監査許容リスト・公式調整オーバーライド（→ [data/README.md](data/README.md)）
- `docs/`: 利用者向けドキュメント
- `reports/`: 生成レポート（`YYYY/MM` 階層。保持方針は `reports_manifest.json`）
- `msData.json`: データ本体

## コントリビュート

フォーマット/リント/テストは `uv run black .` / `uv run ruff check .` / `uv run pytest -q`。コミットは Conventional Commits（日本語、`data:` はデータのみ変更）。取得時はレート制限（既定 2 req/sec）を守ること。

仕様・抽出ルール・Actions 運用の詳細（SSOT）は [AGENTS.md](AGENTS.md)。
