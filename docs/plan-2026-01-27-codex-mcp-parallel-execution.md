# Codex MCP 並列実行機能 - 作業計画書

## 背景・目的

Claude Code環境において、Codex MCPを使用したコードレビューを並列実行することで、大規模プロジェクトのレビュー時間を短縮し、CI/CDパイプラインの効率化を実現する。

現在、Codex MCPは単発実行のみで使用しており、複数ファイルのレビューは順次実行となっている。これを並列化することで、5-10倍の高速化を目指す。

### 決定事項

深掘りセッションで以下が確定した：

- **並列化レベル**: 単一MCPサーバー内でのツール並列呼び出し
- **ユースケース**: 複数ファイルの同時レビュー、異なる観点での同時分析、大規模プロジェクトの高速化、CI/CD最適化
- **クライアント環境**: Claude Code (CLI)
- **制御レイヤー**: MCPクライアント側で制御
- **実現方法**:
  - Task内でサブエージェントがMCP呼び出し
  - Bashでcodex CLIを並列実行
- **並列度**: 5-10並列を想定
- **結果統合**: 統合サマリーレポート + ファイル単位の個別レポート
- **懸念事項**: リソース消費、エラーハンドリング
- **監視方法**: リアルタイムプログレス表示

---

## 技術仕様

### MCP並列実行の制約と公式仕様

MCP公式ドキュメント（2025-11-25仕様）の調査結果：

1. **JSON-RPC 2.0ベース**: MCPはJSON-RPC 2.0を使用し、リクエストIDで応答をマッチング
2. **並列実行の明示的サポートなし**: 公式仕様では`tools/call`のバッチ処理や並列実行に関する明示的な規定がない
3. **クライアント主導の並列化**: 複数の`tools/call`リクエストを同時に送信することはプロトコル上可能
4. **サーバー実装依存**: 並列処理の可否はサーバー実装に依存

### 推奨アプローチ

#### アプローチ1: Bashでcodex CLIを並列実行（推奨）

MCP経由ではなく、codex CLIを直接並列実行する。これが最も確実で制御しやすい方法。

```bash
# 基本形：xargsによる並列実行
find src -name "*.py" | xargs -P 5 -I {} codex exec "Review {} for security issues"

# GNU parallelを使用（より高機能）
find src -name "*.py" | parallel -j 5 'codex exec "Review {} for security and performance"'

# バックグラウンド実行による並列化
for file in src/*.py; do
  codex exec "Review $file" > "reports/$(basename $file .py)_review.md" &
done
wait
```

**長所**:
- シンプルで実装が容易
- 並列度の制御が直接的
- エラーハンドリングが標準的なシェルの方法で対応可能

**短所**:
- MCPの利点（セッション管理、コンテキスト共有）を活かせない
- Claude Codeの統合された体験から外れる

#### アプローチ2: Task内サブエージェントによるMCP呼び出し

Claude CodeのTaskツールを使用し、各サブエージェントがCodex MCPを呼び出す。

```
# Claude Codeでの実行イメージ
[1つのメッセージで複数のTaskを並列起動]
Task 1: "src/main.py をCodex MCPでセキュリティレビュー"
Task 2: "src/utils.py をCodex MCPでセキュリティレビュー"
Task 3: "src/api.py をCodex MCPでセキュリティレビュー"
```

**長所**:
- Claude Code内で完結
- MCPの機能をフル活用
- 結果の統合が容易

**短所**:
- サブエージェントのMCPアクセス権限に依存
- オーバーヘッドが大きい可能性

### データフロー

```
[入力]                    [並列処理]                [出力]
対象ファイル一覧    →    Codex並列実行      →    個別レポート
  - file1.py              ├─ Codex (file1)         - file1_review.md
  - file2.py              ├─ Codex (file2)         - file2_review.md
  - file3.py              └─ Codex (file3)         - file3_review.md
                                   ↓
                          結果統合処理      →    統合サマリー
                                                   - summary.md
```

### 進捗表示の実装

リアルタイムプログレス表示の実装案：

```bash
#!/bin/bash
# parallel_codex_review.sh

TOTAL=$(find "$TARGET_DIR" -name "*.py" | wc -l)
DONE=0

for file in $(find "$TARGET_DIR" -name "*.py"); do
  (
    codex exec "Review $file" > "reports/$(basename $file .py)_review.md" 2>&1
    echo "DONE: $file"
  ) &

  # 並列度制御
  [ $(jobs -p | wc -l) -ge $MAX_PARALLEL ] && wait -n

  ((DONE++))
  printf "\rProgress: %d/%d (%d%%)" $DONE $TOTAL $((DONE * 100 / TOTAL))
done

wait
echo -e "\nAll reviews completed."
```

### エラーハンドリング

```bash
#!/bin/bash
# 失敗したタスクを記録し、リトライ可能にする

FAILED_LOG="reports/failed_reviews.log"
> "$FAILED_LOG"

for file in $(find "$TARGET_DIR" -name "*.py"); do
  if ! codex exec "Review $file" > "reports/$(basename $file .py)_review.md" 2>&1; then
    echo "$file" >> "$FAILED_LOG"
    echo "FAILED: $file"
  fi
done &

# 失敗したファイルのリトライ
if [ -s "$FAILED_LOG" ]; then
  echo "Retrying failed reviews..."
  while read file; do
    codex exec "Review $file" > "reports/$(basename $file .py)_review.md" 2>&1 || \
      echo "PERMANENT FAILURE: $file"
  done < "$FAILED_LOG"
fi
```

---

## タスクリスト

### Phase 1: 基盤整備

- [ ] codex CLIの並列実行テスト（2-3ファイルで動作確認）
- [ ] レポート出力ディレクトリ構造の設計
- [ ] 並列実行スクリプトの基本実装

### Phase 2: コア機能実装

- [ ] `parallel_codex_review.sh` スクリプトの作成
- [ ] リアルタイムプログレス表示の実装
- [ ] エラーハンドリング・リトライ機能の実装
- [ ] 並列度制御パラメータの実装

### Phase 3: 結果統合

- [ ] 個別レポートのフォーマット標準化
- [ ] 統合サマリーレポート生成機能の実装
- [ ] 問題のあるファイルのみフィルタリング機能

### Phase 4: 最適化・運用

- [ ] リソース監視機能の追加
- [ ] CI/CD統合用のラッパースクリプト作成
- [ ] ドキュメント作成（使用方法、設定項目）

### Phase 5: Claude Code統合（オプション）

- [ ] Taskベースの並列実行パターンの検証
- [ ] カスタムスキルとしての実装検討

---

## 受入条件

- [ ] 5-10ファイルを同時に並列レビューできる
- [ ] 各ファイルのレビュー結果が個別ファイルに出力される
- [ ] 全レビュー完了後に統合サマリーが生成される
- [ ] 進捗状況がリアルタイムで確認できる
- [ ] 一部のタスクが失敗しても他のタスクは継続する
- [ ] 失敗したタスクの自動リトライが行われる
- [ ] CPU/メモリ使用量が許容範囲内に収まる

---

## 制約・リスク

### 制約

- **MCP仕様の制約**: MCPプロトコル自体に並列実行のネイティブサポートがない
- **Codex APIレート制限**: OpenAI APIのレート制限に注意が必要
- **Claude Code環境**: MCPツールの直接並列呼び出しは不可（Taskツール経由が必要）

### リスク

| リスク | 影響度 | 対策 |
|--------|--------|------|
| APIレート制限 | 高 | 並列度の動的調整、exponential backoff |
| メモリ不足 | 中 | 並列度の制限、監視の実装 |
| 部分的な失敗 | 中 | リトライ機構、失敗ログの保存 |
| 結果の不整合 | 低 | 排他制御、一時ファイルの使用 |

---

## コンテキスト

### 関連ファイル

- `.claude/settings.json` - MCP設定
- `scripts/` - 既存スクリプト群（参考実装）
- `Makefile` - ビルド・タスク自動化

### 既存アーキテクチャ

- Claude Code CLI環境
- Codex MCP (`mcp__codex__codex`) が設定済み
- Bashツールによるシェルコマンド実行が可能

### 依存関係

- codex CLI（インストール済み）
- GNU parallel または xargs（システム標準）
- jq（JSON処理、オプション）

### 前提条件

- OpenAI APIキーが設定されている
- Codex MCPが正常に動作している
- 十分なシステムリソース（CPU、メモリ）がある

---

## 代替案

### 検討した他のアプローチ

1. **カスタムMCPサーバー作成**
   - Codexをラップし、バッチ実行機能を提供するMCPサーバーを作成
   - 却下理由: 実装コストが高く、メンテナンス負荷が増加

2. **外部オーケストレーター（Python/Node.js）**
   - MCP SDKを使用してカスタムクライアントを実装
   - 保留: 将来的に検討の余地あり

3. **GitHub Actions並列ジョブ**
   - CI/CDパイプライン内で並列ジョブとして実行
   - 補完的アプローチ: CI/CD用途では有効

---

## スコープ外

以下の項目は今回の作業計画の対象外とする：

- Codex MCP自体の機能拡張
- 他のMCPサーバー（Context7等）の並列化
- GUIベースの進捗表示
- 分散処理（複数マシンでの並列実行）
- レビュー結果の自動修正適用

---

## 参考リソース

### 公式ドキュメント

- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [OpenAI Agents SDK - MCP](https://openai.github.io/openai-agents-python/mcp/)

### 関連ガイド

- [MCP Client Development Guide](https://github.com/cyanheads/model-context-protocol-resources/blob/main/guides/mcp-client-development-guide.md)
- [MCP Server Development Guide](https://github.com/cyanheads/model-context-protocol-resources/blob/main/guides/mcp-server-development-guide.md)

---

生成日時: 2026-01-27 22:15
