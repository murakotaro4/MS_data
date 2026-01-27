# Plans.md - タスク管理

## 現在のタスク

<!-- タスクは以下の形式で管理します -->
<!-- - [ ] cc:TODO タスク名 -->
<!-- - [x] 完了したタスク -->
<!-- - [ ] cc:WIP 作業中のタスク -->
<!-- - [ ] cc:blocked ブロック中のタスク -->

### 未着手

#### Issue #2: 強行出撃を持つ機体の fullst オブジェクトが作成されない問題 `[bugfix:reproduce-first]` `[feature:tdd]`

**概要**: 必要強化ポイントが「-」（ハイフン）の強化リスト項目が fullst から除外される

**根本原因**: `scripts/scrape_msdata.py` 579行目の `if points_by_ms:` 条件で、数値がない行が除外される

**修正方針**: 案A（points がない場合も行を採用、points=None で記録）

##### テストケース設計（実装前に合意）

| テストケース | 入力 | 期待出力 | 備考 |
|-------------|------|---------|------|
| 正常系: 数値あり | `<td>2580</td>` | `points: 2580` | 従来通り |
| 正常系: ハイフン | `<td>-</td>` | `points: None` | 強行出撃ケース |
| 正常系: 空セル | `<td></td>` | `points: None` | 空セルケース |
| ソート順: 混在 | 数値 + None | None が先頭 | 解放済みスキル優先 |

##### 実装タスク

- [x] テストファイル作成（`tests/test_fullst_no_points.py`）`cc:完了`
- [x] 579行目の条件修正（`if points_by_ms:` 削除） `cc:完了`
- [x] 後続処理で空の points_by_ms を考慮 `cc:完了`
- [x] ソートロジック修正（None を先頭に） `cc:完了`
- [x] 既存テスト通過確認 `cc:完了`
- [x] Codex Code Reviewer レビュー → **APPROVE** `cc:完了`
- [x] main ブランチへ cherry-pick (b137404) `cc:完了`
- [x] Issue #2 クローズ `cc:完了`

### 作業中
_現在タスクなし_

### 完了
_現在タスクなし_

---

## マーカー凡例

| マーカー | 状態 | 説明 |
|---------|------|------|
| `cc:TODO` | 未着手 | 実行予定 |
| `cc:WIP` | 作業中 | 実装中 |
| `cc:blocked` | ブロック中 | 依存タスク待ち |
| `pm:依頼中` | PM から依頼 | 2-Agent 運用時 |

---

## セッション履歴

### 2026-01-13
- harness-init によるプロジェクトセットアップ完了
- Issue #2 調査: Codex Architect に委任して根本原因を特定
  - 原因: 579行目 `if points_by_ms:` で数値なし行が除外
  - 方針: 案A（points=None で記録）を採用
  - Plans.md にタスクとして計画化完了
- Issue #2 実装完了: Task ツールで並列実装 + Codex Code Reviewer で APPROVE
  - `tests/test_fullst_no_points.py` 新規作成（5テスト）
  - `scripts/scrape_msdata.py` 修正（579行目条件削除、ソート修正）
  - 全16テスト通過
- Issue #2 完了: main ブランチへ cherry-pick + Issue クローズ
  - コミット b137404 を main に cherry-pick（コンフリクトなし）
  - 全22テスト通過
  - Issue #2 クローズ済み
