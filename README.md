# バトオペ2 MS データ管理（msData.json）

機動戦士ガンダム バトルオペレーション2（バトオペ2）の機体ステータスを JSON（`msData.json`）で管理し、atwiki からの取得・正規化・検証・自動更新を行うリポジトリです。**運用・設計の詳細（仕様・抽出ルール・GitHub Actions 運用）は [AGENTS.md](AGENTS.md) を参照してください。** 本 README はクイックスタートです。

## ディレクトリ構成（抜粋）
- `ms_data/`: Python パッケージ本体
  - `core/` 共通ユーティリティ / `net/` HTTP・キャッシュ / `scraping/` atwiki 取得
  - `pipeline/` 取り込み・正規化 / `validation/` 検証 / `audit/` 監査
  - `reporting/` レポート生成 / `skills/` スキルデータ / `gh/` GitHub 連携 / `notify/` メール
  - `tasks.py`: 全ターゲットのディスパッチャ
- `tests/`: ユニットテスト
- `schema/`: JSON Schema（`msData.schema.json` ほか）
- `data/`: スキル定義・公式調整オーバーライド（SSOT）
- `reports/`: 生成レポート（保持方針は `reports_manifest.yml`）
- `msData.json`: データ本体

## セットアップ
```bash
uv venv
uv sync --dev
```

## よく使うコマンド
第一コマンドは `uv run python -m ms_data.tasks <target>`。

- 品質チェック一括: `uv run python -m ms_data.tasks ci`
- 検証: `uv run python -m ms_data.tasks validate`（厳格: `validate-strict`、skills系: `validate-skills`）
- 一覧取得: `uv run python -m ms_data.tasks scrape-index TTL=7d`
- 詳細取得: `uv run python -m ms_data.tasks scrape-details TTL=7d RATE=2.0 LIMIT=0`
- 取り込み: `uv run python -m ms_data.tasks import-details`
- ラベル監査: `uv run python -m ms_data.tasks labels LIMIT=0` → `audit-labels`

環境変数: `TTL`（既定7日）/ `RATE`（既定2.0 req/sec）/ `LIMIT`（0=全件）/ オフライン `NO_NET=1` / 強制更新 `FORCE=1`

## データ更新
毎日 18:00 JST に GitHub Actions が自動更新（PR 作成 → Codex 自動レビュー → マージ → メール通知）します。手動で更新する場合:

1. ブランチ作成: `git switch -c data/update-YYYYMMDD`
2. 取得: `uv run python -m ms_data.tasks scrape-details TTL=7d RATE=2.0 LIMIT=0`
3. 取り込み: `uv run python -m ms_data.tasks import-details`
4. 検証: `uv run python -m ms_data.tasks validate-strict`
5. 差分確認: `git diff -- msData.json` → コミット / PR

## コントリビュート
- フォーマット/リント/テスト: `uv run black .` / `uv run ruff check .` / `uv run pytest -q`
- コミット規約: Conventional Commits（日本語、`data:` はデータのみ変更）
- 取得時はレート制限（既定 2 req/sec）と取得先の利用規約・礼節を守ること

詳細な仕様・抽出ルール・Actions 運用・スキルデータの扱いは [AGENTS.md](AGENTS.md) を参照してください。
