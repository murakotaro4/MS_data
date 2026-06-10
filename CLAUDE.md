# CLAUDE.md - MS_data プロジェクト設定

`msData.json`（バトオペ2の機体データ）を atwiki から取得・正規化・検証・自動更新する Python プロジェクトです。

**コマンド・データ仕様・抽出ルール・GitHub Actions 運用・コミット規約は、すべて [AGENTS.md](AGENTS.md) を単一の参照先とします。** 重複記載を避けるため、本ファイルには Claude 固有の注意のみを記載します。

## Claude 向けの注意
- 言語: 日本語を原則とします（Issue/PR/コメント/ドキュメント/コミットメッセージ）
- 第一コマンド: `uv run python -m ms_data.tasks <target>`（品質チェック一括は `ci`）
- 毎日 18:00 JST に自動更新パイプラインが稼働中。`msData.json` と `reports/` を手動で触る変更は自動更新 PR と競合し得るため注意
- メール関連の値（`GMAIL_*`）は GitHub Secrets 経由のみ。ワークフローで `vars.` への変更や `echo` 出力をしない（public リポジトリのためログが公開される）
