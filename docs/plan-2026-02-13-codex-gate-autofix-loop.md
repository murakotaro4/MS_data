# Codexレビュー起点の自動修正・マージゲート運用計画（v1）

最終更新: 2026-02-13
対象リポジトリ: `murakotaro4/MS_data`
対象PR: `data/auto-update-*` ブランチのみ

## 1. 目的

自動更新PRに対して、Codexレビュー結果を取り込み、次を自動化する。

- P1/P2 指摘の残存中はマージをブロックする
- P1/P2 がある場合は Codex に自動修正依頼を出す
- 指摘の重複投稿を除外する
- 自動修正ループを最大2回に制限する

## 2. 全体フロー

1. `data update` ワークフローが自動更新PRを作成
2. CodexがPRをレビュー（自動レビュー設定済み）
3. `codex_gate.yml` がレビューコメントを収集し、P1/P2を判定
4. P1/P2ありなら `codex-gate` チェックを失敗させる（マージ不可）
5. `codex_autofix.yml` が `@codex address that feedback` を投稿
6. Codexが修正コミットを提案・反映
7. 再度 `codex_gate.yml` 判定
8. P1/P2解消で `codex-gate` 成功、マージ可能

## 3. 追加ワークフロー

### 3.1 `codex_gate.yml`

#### トリガー

- `pull_request`: `opened`, `reopened`, `synchronize`, `ready_for_review`
- `pull_request_review`
- `pull_request_review_comment`
- `issue_comment`

#### 対象フィルタ

- `base` が `main`
- `head.ref` が `data/auto-update-` で始まる
- Draft PR は除外

#### 判定ロジック

- GitHub API から以下を取得
  - `pulls/{number}/reviews`
  - `pulls/{number}/comments`（行コメント）
  - `issues/{number}/comments`
- 投稿者が `chatgpt-codex-connector` 系のコメントのみ対象
- 本文中の `P1` または `P2` を高優先度指摘としてカウント
- 本文正規化後に SHA256 を計算し重複除外
- `high_count > 0` ならジョブ失敗

#### 出力

- ジョブ出力
  - `high_count`
  - `findings_json`
- PR要約コメント（upsert）
  - `<!-- codex-gate-summary -->` を固定マーカー化

### 3.2 `codex_autofix.yml`

#### トリガー

- `workflow_run`（`codex_gate` が `failure` のとき）

#### 実行条件

- 対象PRが `data/auto-update-*`
- `high_count > 0`
- 自動修正サイクルが 2 未満

#### 処理

- PRコメント履歴から `<!-- codex-autofix-cycle:N -->` を抽出
- `N < 2` の場合
  - `@codex address that feedback` を投稿
  - 次サイクル番号をコメントに埋め込む
- `N == 2` の場合
  - 以降は自動投稿せず、手動対応エスカレーションを投稿

## 4. ブランチ保護

`main` の Required checks に `codex-gate` を追加する。

## 5. 権限設計

### `codex_gate.yml`

- `contents: read`
- `pull-requests: write`

### `codex_autofix.yml`

- `contents: read`
- `pull-requests: write`

## 6. 失敗時の扱い

- API取得失敗時は `codex-gate` を失敗にして保守的運用
- `codex_autofix` の投稿失敗はPRへ失敗通知コメントを残す

## 7. 既知リスク

- Codexのコメント形式が変わると `P1/P2` 抽出が外れる
- `GITHUB_TOKEN` 投稿で `@codex` が反応しない場合がある
- `workflow_run` 連鎖で過剰起動する可能性がある

## 8. 軽減策

- 優先度抽出は正規表現を関数化し、テストを用意
- 将来のトークン切替用に `CODEX_REVIEW_TOKEN` 分岐を残す
- `concurrency` でPR単位の同時実行を防止

## 9. 検証ケース

1. P1が1件あるPR: `codex-gate` 失敗
2. 同文コメントが2件: カウントは1件
3. 修正後にP1/P2が0件: `codex-gate` 成功
4. 2サイクル後も未解決: 自動修正停止・手動対応通知
5. auto-update以外PR: ワークフローはスキップ

## 10. 段階導入

1. ワークフロー追加のみ（required check未設定）
2. 1週間は観測運用
3. 誤検知が許容内なら `codex-gate` を required check に昇格

---

## レビュー反映ログ

### Cycle 1

- 状態: 未実施
- 指摘サマリ:
- 対応:
- 未解決:

### Cycle 2

- 状態: 未実施
- 指摘サマリ:
- 対応:
- 未解決:

### Cycle 3

- 状態: 未実施
- 指摘サマリ:
- 対応:
- 未解決:
