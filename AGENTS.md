# Repository Guidelines

## 言語ポリシー
- 本リポジトリのコミュニケーションは原則「日本語」です（Issue/PR/コメント/ドキュメント/コミットメッセージ）。

## プロジェクト構成
- 目的: 本リポジトリは `msData.json`（バトオペ2の機体ステータス）を管理し、atwiki からの取得・正規化・検証・自動更新を行います。
- 構成:
  - `ms_data/`: Python パッケージ本体
    - `core/`: 共通ユーティリティ（json_io / paths / ms_names / records / env / labels / dates）
    - `net/`: HTTP クライアントとキャッシュ（client / cache_http）
    - `scraping/`: atwiki 取得（scrape_msdata(facade・CLI) / index_page(一覧解析) / detail_page(詳細解析) / fullst(強化リスト) / text_values(値パース) / change_detection(差分検出) / fetch_state(取得状態)）
    - `pipeline/`: 取り込み・正規化（update_msdata / jsonl_to_json / generate_provenance / restore_snapshot / official_overrides）
    - `validation/`: スキーマ・契約検証（validate_* / verify_snapshot_restore）
    - `audit/`: 監査・巻き戻り検出（audit_* / detect_msdata_rollbacks）
    - `reporting/`: レポート生成・整理（report_msdata_diff / msdata_diff_model / rendering / build_atwiki_quality_report / build_update_mail_body / prune_reports）
    - `gh/`: GitHub 連携（auto_review_gate / auto_review_merge / cleanup_auto_update_prs / post_merge_assets / notify_failure / gh_json / outputs）
    - `notify/`: メール送信（send_gmail）
    - `tasks.py`: 全ターゲットのディスパッチャ（ワークフロー・開発者の共通入口）
  - `tests/`: ユニットテスト
  - `schema/`: JSON Schema（対応表は `schema/README.md`）
  - `data/`: 監査許容リスト・公式調整オーバーライド（SSOT）（役割は `data/README.md`）
  - `reports/`: 生成レポート（保持方針は `reports_manifest.json` が SSOT）

## ビルド・テスト・開発コマンド（uv）
- 環境作成: `uv venv` → `uv sync --dev`。実行は基本 `uv run <cmd>`。
- 第一コマンド: `uv run python -m ms_data.tasks <target>`。
- 主要ターゲット:
  - 品質チェック一括: `uv run python -m ms_data.tasks ci`
  - 検証: `validate` / 厳格: `validate-strict`
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
- 取得計測: 実行ごとに `cache/fetch_stats.json` へフェーズ別（index/details）のリクエスト数・200/304件数・失敗数・受信バイト数・所要秒数を記録。`reports/YYYY/MM/atwiki_quality_YYYYMMDD.json` の `fetch` セクションに転記され、負荷削減の検証に使う。`body_bytes` は Content-Encoding 展開後のボディ長（実転送量は圧縮分小さい。実行間の相対比較には影響なし）。index フェーズ書き込み時に前回実行分をリセットする。
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
- 自動レビュー/マージ: `auto review merge` は `data update` 成功後の `workflow_run` で起動する。Codex 側 Automatic reviews を優先し、ファイル指摘が 0 件なら自動マージする。attempt 1 から `@codex review` を投稿する（初回は review マーカー、リトライは retry マーカー）。投稿名義は Secret `CODEX_TRIGGER_PAT`（fine-grained: Issues read/write・Pull requests read/write・Metadata read）があれば PAT（人間）名義、なければ bot（github-actions）名義（2026-07-20〜27 の Codex 側 bot 名義拒絶が解消したことを確認済み。再発時は停止メール→手動 `@codex review` → resume 回収で運用）。merge は常に `github.token`（PAT は使わない）。merge 直前に HEAD SHA を再確認し、不一致ならスキップする。
- 対象PRの解決: `data/auto-update-YYYYMMDD`（workflow_run.created_at の JST 日付）を優先し、無ければ open な最新 `data/auto-update-*` にフォールバック。 PR payload のアクセサ（head/base ref・sha、REST/GraphQL 両キー対応）と `source_run_id:N` マーカー解釈は `ms_data/gh/pr_payload.py` に集約（auto_review / cleanup / post_merge で共用）。
- dry-run: `data update` の `workflow_dispatch` で `dry_run=true` を指定すると、取得・監査・artifact 作成まで実行し PR 作成と通知は行いません。
- 古いPR整理: `cleanup auto update prs` が毎日 20:30 JST に実行され、`keep_days` 超過の open PR を close（head ブランチも削除）。
- レポート整理: `reports prune` が毎月1日 18:00 JST に実行され、`reports_manifest.json` の `prune`（max_age_days / keep_min）に基づき期限切れレポートの削除 PR を作成します。この PR は自動マージ対象外のため人間がレビューしてマージします。
- PRラベル: 自動更新 PR には `data-update` / `rollback-guard` / `official-overrides` / `atwiki-quality` を付与。
- reports 運用SSOT: 命名規約・分類・保持方針は `reports_manifest.json` が正。契約検証は `uv run python -m ms_data.validation.validate_report_contract`、生成物検証は `uv run python -m ms_data.tasks validate-generated-reports`。
- 手動更新レポート: 手動でデータ更新した場合は `reports/YYYY/MM/msdata_update_YYYYMMDD.md` を `reports/msdata_update_template.md` に沿って作成（新規追加機体は主要パラメータを網羅、既存更新は変更前後の値を明記）。
- 失敗時の挙動: findings / no_response / disconnected で停止した場合は自動マージせず PR を残し、`GMAIL_ADDRESS` 宛（本人のみ）に停止メールを送信して手動対応。
- 翌朝レスキュー: `resume auto review` が毎朝 09:00 JST（cron `0 0 * * *`）と `workflow_dispatch` で起動し、停止 PR を自動回収する（手動 `@codex review` 後のマージ回収を含む）。`auto review merge` と同一 concurrency group（`msdata-auto-review-merge`）を共有。
- Codexレビュー待ち: 既定 3 回まで試行。調整は repository variables の `CODEX_REVIEW_MAX_ATTEMPTS` / `CODEX_REVIEW_ATTEMPT_TIMEOUT_SECONDS` / `CODEX_REVIEW_POLL_SECONDS` / `CODEX_REVIEW_SETTLE_SECONDS`。
- 通知: マージ後に `post merge notify` が Release アセット作成とメール送信を行います。本文は `reports/YYYY/MM/diff_msdata_YYYYMMDD.md` から生成、添付は `msData.json`。差分ゼロの定期実行時は `data update` から「差分なし」報告メールを送信。idempotency キーは `source_run_id + head_ref`。
- メール秘匿運用（重要）: `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `GMAIL_TO` / `CODEX_TRIGGER_PAT` は必ず GitHub **Secrets** 経由で渡します（public リポジトリではログが公開されるため、`vars.` への変更や `echo` でのデバッグ出力は禁止。Secrets はログで自動マスクされます）。`GMAIL_TO` はカンマ区切りで複数宛先可。値の参照は不可のため変更時は最終文字列で上書き。自動レビュー停止メールは宛先を `GMAIL_ADDRESS`（本人のみ）に固定する。
- 生成元追跡: 実行ごとに `reports/YYYY/MM/provenance_YYYYMMDD.json`（index/details/html のハッシュ・件数・source_run_id）を生成。
- 巻き戻り対策: `reports/YYYY/MM/rollback_guard_YYYYMMDD.md` と `reports/YYYY/MM/official_overrides_audit_YYYYMMDD.md` を生成。protected rollback は自動更新を失敗させます。
- 生データアーカイブ: 実行ごとに `raw_snapshot_*.tar.xz` を artifact（90日）へ、マージ後に Release tag `raw-snapshot-YYYYMMDD-run-<run_id>` へ恒久保存。
- 復元手順: 対象コミットの provenance から `release.tag` を取得し、`uv run python -m ms_data.tasks restore-snapshot SNAPSHOT=... OUT_DIR=restore_tmp` で `cache/` と `reports/` を再構成（ファイルが HEAD から prune 済みでも `git log -- <path>` + `git show` で provenance 自体を辿れます）。復元CI: `verify-snapshot-restore`。
- official_overrides 期限管理: 各 entry に `review_after` / `remove_after` を設定。期限到達時は `data update` が Step Summary に件数を出し、protected rollback 0 件なら Issue `official_overrides 期限確認` を作成/追記。スキーマは `schema/official_overrides.schema.json`（`MS名` / `values` / `stale_values` 必須）。
- official_overrides 期限確認 Issue の対応手順（大規模調整のたびに繰り返す）: 監査レポートの状態別に、`upstream_current`（atwiki 反映済み）と `source_changed`（stale 不一致で不発化）は entry を撤去、`protected_by_override`（未反映）は存続させ `review_after` を延長。全 entry 撤去後はファイルごと削除する（ディレクトリは `.gitkeep` で維持。空でも `validate-official-overrides-schema` は OK）。例: Issue #113 → PR #145。
- atwiki取得品質: `reports/YYYY/MM/atwiki_quality_YYYYMMDD.json` に HTTP 状態・304件数・失敗推定・レコード数・差分件数を記録。しきい値超過は warnings として PR 本文・Step Summary に警告（`ATWIKI_QUALITY_*` 変数で調整）。
- notify failure: `workflow_run` で 6 ワークフロー（`data update` / `auto review merge` / `resume auto review` / `post merge notify` / `cleanup auto update prs` / `reports prune`）の `failure` / `timed_out` / `startup_failure` / `action_required` を監視し、GMAIL Secrets によるメール送信と `pipeline-failure` ラベル付き Issue 起票を行う（`ms_data/gh/notify_failure.py`、stdlib のみで動作、重複 Issue の自己修復あり）。
- ci の changes ジョブ: PR がデータ・レポート・md のみの変更なら checks（ubuntu/windows マトリクス）をスキップ。`tests/` 配下と削除は `code=true`。changes ジョブ自身が report-contract / msData / generated-reports の軽量検証を実施。actionlint は checks ジョブ（ubuntu）で実行。
- `.github/actions/resolve-codex-pat`: `CODEX_TRIGGER_PAT` のログイン解決（`pat_available` / `pat_login` を出力、失敗時は警告のみで bot 名義へフォールバック）。`auto review merge` / `resume auto review` で共用。
- `.github/actions/setup-uv-env`: Python 3.11 + uv + `uv sync --dev` の composite action。`ci` / `data update` / `auto review merge` / `resume auto review` / `post merge notify` / `reports prune` で共用（Python バージョン変更はここが主変更点）。`notify failure` と `cleanup auto update prs` は uv 不要のため未使用。
- CI runner: Windows は `windows-2025-vs2026` を明示使用。`windows-latest` へ戻す場合は GitHub の runner image 移行状況を確認。
- 互換期間: レポート再編時の旧パス互換は原則検討するが、v3 の年月階層化（`reports/YYYY/MM/`）は破壊的移行として実施済み（`legacy_path_support: false`、旧パスへの転送なし）。日付付きレポートの旧フラット `path_patterns` は撤去済み（直下に残す undated / テンプレートのみ許容）。

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

## Cursor Cloud specific instructions
- 本プロジェクトは Web アプリや常駐サービスを持たない **CLI／データ管理ツール**です。「アプリを起動する」= `uv run python -m ms_data.tasks <target>` を実行すること。起動しっぱなしにする dev サーバーやポートは存在しない。
- パッケージ管理は `uv`。VM 起動時の update script で `uv sync --dev` 済みなので、追加のインストールは不要。コマンドは常に `uv run <cmd>`（例: `uv run python -m ms_data.tasks ci`）で実行する。標準コマンド一覧は本ファイル上部「ビルド・テスト・開発コマンド」と `README.md` を参照。
- 環境の総合ヘルスチェックは `uv run python -m ms_data.tasks ci`（lint + カバレッジ付きテスト + 各種 validate を一括実行）。単発なら `lint` / `test` / `validate-strict`。
- Python バージョン差異に注意: cloud VM のローカル venv は Python 3.12 で動く（`requires-python >=3.11` のため問題なし）が、GitHub Actions CI は Python 3.11 を使う。バージョン固有の挙動を疑う場合はこの差を考慮する。
- スクレイピング系ターゲット（`scrape-index` / `scrape-details` 等）は外部 atwiki へ実アクセスし、既定 2 req/sec のレート制限がかかる。cloud 上でのライブ取得は原則避け、オフライン検証は `NO_NET=1`（キャッシュのみ利用）を付ける。`ci` とユニットテストはネットワーク非依存で完結する。
