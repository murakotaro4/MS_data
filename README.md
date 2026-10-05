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

更新通知は、機体ごとのカードに LV 別の変更前・変更後と数値の増減量を載せる HTML メールです。追加・削除レコードの主要ステータスと fullst 明細も、差分レポートに記載された内容を省略せず掲載します。要確認の監査結果は上部に、監査サマリと実行情報は末尾に表示します。差分なしの日は短い結果通知になります。テキスト版を同じメールに併記し、マージ後の `msData.json` 添付も維持します。

送信せずにプレビューを作成する場合は、`uv run python -m ms_data.reporting.build_update_mail_body` の既存引数に `--html-out <出力先.html>` を追加してください。送信 CLI は任意の `--html-body <本文.html>` に対応し、省略時は従来どおりテキストのみ送信します。

### 取得元スロット異常の部分保留

連続する3つのLVで属性・形態・Wiki URLが一致し、コストが50ずつ増える場合に、
中間LVの単一スロットが両隣より小さく、合計も下位LVより減る候補を検出します。
端点・LV欠損・合計が増える配分変更はこの限定検査の対象外です。
この比較だけでは取得元の誤記と解析バグを確定できず、正解値も推測しません。

未承認の異常はその機体＋LVの更新候補全体を不採用とし、正常と確認できる前値を
保持します。前値がない新規レコードは追加を保留します。前値も異常の場合は公開済み
レコードを推測修正・削除せず、`previous_unverified_retained`（正常な前値なし・既存値も
未確認／要対応）として区別します。他の正常候補は従来のレビュー・マージゲートへ進みます。
schema・意味検証・既存protected rollbackによる全体停止は維持します。
期限切れの本人確認済み補正で、更新候補を拒否して公開済みの未確認値を変更せず保持した場合は
後段監査でも`source_hold_unverified_previous`として要対応に分類します。旧overrideと実際の22→12等の巻き戻りは全体停止します。

`source_slot_audit_YYYYMMDD.md` に元値・比較値・前値・採用値・取得時刻・URL・処置を
記録し、補正前JSONと監査JSONをraw snapshot/artifactに保存します。保留だけで差分がない日も
証拠を保存し、本人（`GMAIL_ADDRESS`）だけへ「部分保留エラー・対応要」を通知します。
通知失敗はStep Summaryに記録し、正常候補のPR作成を妨げません。dry-runは送信しません。

本人確認済みの限定補正は、元値との一致条件と`expires_after`（JST、その日まで有効）を
必須とします。ガブスレイLV2中スロットは12の場合だけ22へ補正します（[Issue #296](https://github.com/murakotaro4/MS_data/issues/296)）。
2026-10-19の適用期限後も既知の誤値12の候補は保留し、前回採用済み22を保持します。
保持は新たな補正と区別します。取得元が22へ直れば通常取り込みに戻り、第三値には22を強制しません。
期限後の既知誤値検出に定義ファイルを使うため、撤去は取得証拠を確認してから判断します。

### official_overrides の期限確認

`review_after` / `remove_after` に到達した値の対象ページは、通常の差分候補に
`official_override_due` の理由で追加します。対象だけTTLを無視して再取得・解析し、
`NO_NET=1` の場合はキャッシュを使いますが、上流確認済みの撤去候補にはしません。

監査は `cache/index.json`、`cache/index_changed_meta.json` と
`cache/detail_fetch_state.json` を照合し、今回未取得・取得失敗・解析失敗・値欠損・
キャッシュのみ・一致／不一致を区別します。取得状態にはURLごとの試行時刻、取得時刻、
HTTP結果とoverride適用前の解析値を保存し、選定記録とともにraw snapshotへ含めます。
期限到達値がある日は、データ差分がなくてもsnapshotをartifactへ保存します。
旧形式の取得記録や `--raw` ファイルだけでは撤去候補にしません。

`remove_after` 到達値の取得証拠が不足すると、品質レポートに
`official_override_evidence_missing` が出ます。overrideの削除は自動化しません。
独立した次回取得の結果も確認してから判断してください。

期限確認 Issue は、直前の通知と件数・期限対象・補正値・期限設定が同じなら
日次の追記を抑止します。同じ件数でも対象が入れ替わると通知します。
監査出力の `due_fingerprint` を通知マーカーに記録し、識別子のない旧通知には
一度追記して比較基準を確立します。完了済み Issue は再開せず、次の期限到達時に
新しい Issue を作成します。

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
