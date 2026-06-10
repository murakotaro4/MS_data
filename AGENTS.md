# Repository Guidelines

## 言語ポリシー
- 本リポジトリのコミュニケーションは原則「日本語」です（Issue/PR/コメント/ドキュメント/コミットメッセージ）。

## プロジェクト構成
- 目的: 本リポジトリは `msData.json`（バトオペ2の機体ステータス）を管理し、atwiki からの取得・正規化・検証・自動更新を行います。
- 構成:
  - `ms_data/`: Python パッケージ本体
    - `core/`: 共通ユーティリティ（json_io / paths / ms_names / records / env / labels）
    - `net/`: HTTP クライアントとキャッシュ（client / cache_http）
    - `scraping/`: atwiki 取得（scrape_msdata / extract_skills）
    - `pipeline/`: 取り込み・正規化（update_msdata / jsonl_to_json / generate_provenance / restore_snapshot）
    - `validation/`: スキーマ・契約検証（validate_* / verify_snapshot_restore）
    - `audit/`: 監査・巻き戻り検出（audit_* / detect_msdata_rollbacks）
    - `reporting/`: レポート生成・整理（report_msdata_diff / build_atwiki_quality_report / build_update_mail_body / prune_reports）
    - `skills/`: スキルデータ生成（build_skills / build_param_skills / build_owners_flat / preview_params）
    - `gh/`: GitHub 連携（auto_review_gate / auto_review_merge / cleanup_auto_update_prs / post_merge_assets）
    - `notify/`: メール送信（send_gmail）
    - `tasks.py`: 全ターゲットのディスパッチャ（Makefile / ワークフローの入口）
  - `tests/`: ユニットテスト
  - `schema/`: JSON Schema
  - `data/`: スキル定義・公式調整オーバーライド（SSOT）
  - `reports/`: 生成レポート（保持方針は `reports_manifest.yml` が SSOT）

## ビルド・テスト・開発コマンド（uv）
- 環境作成: `uv venv` → `uv sync --dev`。実行は基本 `uv run <cmd>`。
- 第一コマンド: `uv run python -m ms_data.tasks <target>`。`make <target>` は Linux/macOS 向けの薄いラッパー（Windows では ms_data.tasks を優先）。
- 主要ターゲット:
  - 品質チェック一括: `uv run python -m ms_data.tasks ci`
  - 検証: `validate` / 厳格: `validate-strict` / skills系: `validate-skills`
  - 一覧取得: `scrape-index TTL=7d` / 詳細取得: `scrape-details TTL=7d RATE=2.0 LIMIT=0`
  - 取り込み: `import-details` / 正規化のみ: `normalize`
  - ラベル監査: `labels LIMIT=0` → `audit-labels` / index監査: `audit-index`
- 環境変数: `TTL`（キャッシュ既定7日）/ `RATE`（既定2.0 req/sec）/ `LIMIT`（0=全件）/ `NO_NET=1`（オフライン）/ `FORCE=1`（強制再取得）/ `FORCE_FULL=1`（差分検出を無視して全量）/ `REVALIDATE=1`（週次再検証: 一覧の更新経過と前回取得時刻の比較で対象を絞る）/ `STALE_DETAIL_DAYS`（詳細キャッシュ陳腐化しきい値・既定14日、本番は40日）
- フォーマット/リンタ/テスト: `uv run black .` / `uv run ruff check .` / `uv run pytest -q`
- カバレッジ: `test-cov`（CI の `ci` ターゲットはこちらを実行）。`pyproject.toml` の `fail_under` を下回ると失敗します。閾値はテスト追加 PR ごとに「実測 -2pt」へ引き上げる運用（自動更新 PR の CI を巻き添えにしないため、実測より必ず低く保つ）

## スクレイピングとデータ仕様
- SSOT: index（`cache/index.json`）の `name` を真実のソースとし、詳細抽出の `MS名` も index 表記で固定（LVは `_LVn` を付与）。読み込み・マージ時にも index 準拠へ正規化します。
- キャッシュ: `ms_data/net/cache_http.py`（TTL・If-None-Match/If-Modified-Since 対応）。保存先 `cache/html/<slug>.html` + `*.meta.json`。注意: atwiki は ETag/Last-Modified を返さない（2026-06 実測）ため 304 は期待できず、負荷軽減は取得対象の絞り込み（`detect-changed` / `REVALIDATE`）で行う。
- レート制限: 既定 2.0 req/sec。atwiki への負荷を考慮し過度な緩和は避ける。待機は実際のネットワーク取得時のみ（キャッシュヒットは待機しない）。2回目以降は `NO_NET=1` でキャッシュのみ利用可。
- 取得計測: 実行ごとに `cache/fetch_stats.json` へフェーズ別（index/details）のリクエスト数・200/304件数・失敗数・受信バイト数・所要秒数を記録。`reports/atwiki_quality_*.json` の `fetch` セクションに転記され、負荷削減の検証に使う。`body_bytes` は Content-Encoding 展開後のボディ長（実転送量は圧縮分小さい。実行間の相対比較には影響なし）。index フェーズ書き込み時に前回実行分をリセットする。
- データ構造: 配列（各要素=MSの1レベル）。主キー相当は `MS名`（例: `XXX_LV1`）。
- 必須項目: `MS名`, `属性`（汎用/強襲/支援）, `コスト`, `HP`, `スピード`, `スラスター`, `高速移動`, `射撃補正`, `格闘補正`, `耐ビーム補正`, `耐実弾補正`, `耐格闘補正`, `近/中/遠スロット`。旋回は anyOf（`旋回_地上_通常時` または `旋回_宇宙_通常時`）で宇宙専用機を許容。
- 主な抽出・正規化ルール:
  - 行見出しの軽正規化: 余白圧縮、半角()注記のみ除去（全角（）は保持）。FIELD_MAP で正規キーへ、KEY_ALIASES で誤記キー（射撃補則/射撃補生→射撃補正 等）を補正。
  - 旋回値: `78（盾装備時：75.7）` → 先頭整数（78）を採用。
  - 出撃可否・環境適正: atwiki 固有ID（`label_sortie_*`, `label_env_*`）を最優先で解析。不明時は旋回項目の有無から補完。宇宙専用/地上専用で単一見出しが逆側にある場合は適切側へ寄せ替え。
  - fullst（強化リスト）: `[{name, level, points?}]`。「MSレベル毎必要強化値」に数値がある行のみ採用。高Lv未掲載は直前Lvで補完（`points: null`）。「強行出撃」は `-`/空欄でも `points: null` で生成。
  - MS名の正規化: `[]`→`［］`、`II/III`→`Ⅱ/Ⅲ`、`Z/ZZ`→`Ζ/ΖΖ`（ガンダム直前のみ）、`Ｖ`→`V`。
- PC版のみの機体（index未収載）は例外として維持（監査では msData のみとして残る想定）。

## GitHub Actions 運用
- 定期実行: `data update` は毎日 18:00 JST に実行（cron は月〜土 `0 9 * * 1-6` と日曜 `0 9 * * 0` の2本）で実行し、差分があれば `data/auto-update-YYYYMMDD` の PR を作成します。日曜は第1日曜（JST）のみ真の全量取得（`FORCE_FULL=1`+`FORCE=1`）、それ以外の日曜は週次再検証（`REVALIDATE=1`: 更新があったページのみ再取得）で atwiki への負荷を抑えます（判定は Prepare ステップの `UPDATE_MODE`）。`workflow_dispatch` の `mode` 入力（auto/full/revalidate）で手動指定も可能。注意: 第1日曜判定は実行時の日付に基づくため、失敗した第1日曜の run を後日 re-run すると revalidate になります。その場合は `mode=full` の手動 dispatch で全量を補完してください（補完しなくても `STALE_DETAIL_DAYS` 超過後に平日更新が順次取り直す自己修復はあります）。
- 自動レビュー/マージ: `auto review merge` は `data update` 成功後の `workflow_run` で起動し、対象 PR に `@codex review` を自動実行。Codex のファイル指摘が 0 件なら自動マージします（同一 HEAD SHA では重複依頼を抑止）。
- 対象PRの解決: `data/auto-update-YYYYMMDD`（workflow_run.created_at の JST 日付）を優先し、無ければ open な最新 `data/auto-update-*` にフォールバック。
- dry-run: `data update` の `workflow_dispatch` で `dry_run=true` を指定すると、取得・監査・artifact 作成まで実行し PR 作成と通知は行いません。
- 古いPR整理: `cleanup auto update prs` が毎日 20:30 JST に実行され、`keep_days` 超過の open PR を close（head ブランチも削除）。
- レポート整理: `reports prune` が毎月1日 18:00 JST に実行され、`reports_manifest.yml` の `prune`（max_age_days / keep_min）に基づき期限切れレポートの削除 PR を作成します。この PR は自動マージ対象外のため人間がレビューしてマージします。
- PRラベル: 自動更新 PR には `data-update` / `rollback-guard` / `official-overrides` / `atwiki-quality` を付与。
- reports 運用SSOT: 命名規約・分類・保持方針は `reports_manifest.yml` が正。契約検証は `uv run python -m ms_data.validation.validate_report_contract`、生成物検証は `uv run python -m ms_data.tasks validate-generated-reports`。
- 手動更新レポート: 手動でデータ更新した場合は `reports/msdata_update_YYYYMMDD.md` を `reports/msdata_update_template.md` に沿って作成（新規追加機体は主要パラメータを網羅、既存更新は変更前後の値を明記）。
- 失敗時の挙動: Codex が応答しない、または指摘が 1 件以上ある場合は自動マージせず PR を残して手動対応。
- Codexレビュー待ち: 既定 3 回まで試行。調整は repository variables の `CODEX_REVIEW_MAX_ATTEMPTS` / `CODEX_REVIEW_ATTEMPT_TIMEOUT_SECONDS` / `CODEX_REVIEW_POLL_SECONDS` / `CODEX_REVIEW_SETTLE_SECONDS`。
- 通知: マージ後に `post merge notify` が Release アセット作成とメール送信を行います。本文は `reports/diff_msdata_YYYYMMDD.md` から生成、添付は `msData.json`。差分ゼロの定期実行時は `data update` から「差分なし」報告メールを送信。idempotency キーは `source_run_id + head_ref`。
- メール秘匿運用（重要）: `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `GMAIL_TO` は必ず GitHub **Secrets** 経由で渡します（public リポジトリではログが公開されるため、`vars.` への変更や `echo` でのデバッグ出力は禁止。Secrets はログで自動マスクされます）。`GMAIL_TO` はカンマ区切りで複数宛先可。値の参照は不可のため変更時は最終文字列で上書き。
- 生成元追跡: 実行ごとに `reports/provenance_YYYYMMDD.json`（index/details/html のハッシュ・件数・source_run_id）を生成。
- 巻き戻り対策: `reports/rollback_guard_YYYYMMDD.md` と `reports/official_overrides_audit_YYYYMMDD.md` を生成。protected rollback は自動更新を失敗させます。
- 生データアーカイブ: 実行ごとに `raw_snapshot_*.tar.xz` を artifact（90日）へ、マージ後に Release tag `raw-snapshot-YYYYMMDD-run-<run_id>` へ恒久保存。
- 復元手順: 対象コミットの provenance から `release.tag` を取得し、`uv run python -m ms_data.tasks restore-snapshot SNAPSHOT=... OUT_DIR=restore_tmp` で `cache/` と `reports/` を再構成（ファイルが HEAD から prune 済みでも `git log -- <path>` + `git show` で provenance 自体を辿れます）。復元CI: `verify-snapshot-restore`。
- official_overrides 期限管理: 各 entry に `review_after` / `remove_after` を設定。期限到達時は `data update` が Step Summary に件数を出し、protected rollback 0 件なら Issue `official_overrides 期限確認` を作成/追記。スキーマは `schema/official_overrides.schema.json`（`MS名` / `values` / `stale_values` 必須）。
- atwiki取得品質: `reports/atwiki_quality_YYYYMMDD.json` に HTTP 状態・304件数・失敗推定・レコード数・差分件数を記録。しきい値超過は warnings として PR 本文・Step Summary に警告（`ATWIKI_QUALITY_*` 変数で調整）。
- CI runner: Windows は `windows-2025-vs2026` を明示使用。`windows-latest` へ戻す場合は GitHub の runner image 移行状況を確認。
- 互換期間: レポート再編時は旧パスを最低 1 リリース周期維持し、参照 consumer が 0 かつ互換期間経過後に撤去。

## スキルデータ（params / owners）
- 方針: msData.json は恒常値のみ。スキルは別ファイル管理（アプリ側で合成）。定義（`data/skills_params.json`）と所有（`data/skill_owners_flat.json`）を分離し SSOT 化。
- コマンド:
  - `skills-table` … スキル一覧表の厳格抽出 → `cache/skills_table.json`
  - `owners-table` … 所持機体逆引きの厳格抽出 → `cache/owners_table.json`
  - `build-param-skills` … パラメータ変化スキルのみ抽出 → `data/skills_params.json`
  - `build-owners-flat` … シリーズ×機体Lv展開 → `data/skill_owners_flat.json`
  - `preview-params` … 合成プレビュー → `derived/ms_params_preview.json`（msData へは埋め込まない）
- 抽出ポリシー: 対象は能力UP系ホワイトリスト（EXAM/HADES/ALICE/ZEUS/バイオセンサー各種/覚醒 など）。対象パラメータはスピード/高速移動/補正/旋回/各耐性/スラスター消費/被ダメージ係数。シリーズ名は軽正規化（括弧全角化・空白圧縮）で JOIN 安定化、unknown=0 を維持。

## コーディング規約・テスト
- JSON: 2スペース、UTF-8、LF、キーは `snake_case`。
- Python: インデント4スペース、型ヒント必須（`str | None` 形式を推奨）。命名はファイル/関数 lower_snake_case、クラス CapWords。
- ツール: `black`（88列）/ `ruff` / `pytest` を uv で管理。
- テスト: `tests/test_*.py`。変換/検証ロジックは目安80%以上をカバーし、エッジケースと不正入力を含める。
- 共通処理は `ms_data/core` 等の既存ユーティリティを再利用し、コピペ実装を作らない。

## コミット・プルリクエスト
- コミットメッセージは日本語。Conventional Commits を採用: `feat:` `fix:` `docs:` `chore:` `refactor:` `test:` `data:`（データのみ変更）。
  - 例: `data: msData.json を更新（2025-09-05; +123/-45 件）` / `fix(update): 宇宙専用時の旋回値を宇宙側へ寄せ替え`
- PR は小さく焦点を絞り、変更概要・データ来歴・検証結果（`validate-strict` / 差分統計 `records: A -> B | +X -Y ~Z`）・影響範囲を記載。
- `gh pr create` で本文にバッククォートを含める場合は `--body-file` を推奨。
- Issue / PR テンプレート: `.github/ISSUE_TEMPLATE/` と `.github/PULL_REQUEST_TEMPLATE.md` を使用（すべて日本語）。

### Codexレビュー実行手順
- 非対話レビューは `codex exec` を使い、`-m`（モデル）と `-c model_reasoning_effort="..."` を同時指定。基本は `medium`。
- reasoning effort はモデル仕様に合わせる（`gpt-5.3-codex` 系は `low`/`medium`/`high`/`xhigh`、`gpt-5.4` は `none` も可）。
- 正式モデル名は `gpt-5.3-codex-spark` / `gpt-5.4` / `gpt-5.4-mini`（`SPARC` ではなく `spark`）。
- 実行例: `codex exec -m gpt-5.4 -c model_reasoning_effort="medium" "このブランチの差分をレビューし、重大度順に指摘してください。"`

## セキュリティ・データ運用
- 秘密情報や個人情報をコミットしない。認証情報はすべて GitHub Secrets / 環境変数経由（上記メール秘匿運用を参照）。
- 10MB 超やバイナリは Git LFS を使用。
- 再現性を重視: 依存はピン留め、デフォルト実行での外部ネットワーク依存を回避（`NO_NET=1` で検証可能に保つ）。
