# Repository Guidelines

## 言語ポリシー
- 本リポジトリのコミュニケーションは原則「日本語」です（Issue/PR/コメント/ドキュメント/コミットメッセージ）。

## プロジェクト構成
- 目的: 本リポジトリは `msData.json`（バトオペ2の機体ステータス）を管理し、atwiki からの取得・正規化・検証・自動更新を行います。
- 構成:
  - `ms_data/`: Python パッケージ本体
    - `core/`: 共通ユーティリティ（json_io / paths / ms_names / records / env / labels / dates）
    - `net/`: HTTP クライアントとキャッシュ（client / cache_http）
    - `scraping/`: atwiki 取得（scrape_msdata(facade・CLI) / index_page(一覧解析) / detail_page(詳細解析) / fullst(強化リスト) / text_values(値パース) / change_detection(差分検出) / fetch_state(取得状態) / defaults(INDEX_URL・TTL・RATE の既定値 SSOT)）
    - `pipeline/`: 取り込み・正規化（update_msdata / jsonl_to_json / generate_provenance / restore_snapshot / official_overrides）
    - `validation/`: スキーマ・契約検証（validate_* / verify_snapshot_restore）
    - `audit/`: 監査・巻き戻り検出（audit_* / detect_msdata_rollbacks）
    - `reporting/`: レポート生成・整理（report_msdata_diff / msdata_diff_model / rendering / build_atwiki_quality_report / build_source_excerpt / build_update_mail_body / prune_reports）
    - `gh/`: GitHub 連携（auto_review_gate / auto_review_merge / cleanup_auto_update_prs / post_merge_assets / notify_failure / notify_override_due / issue_upsert / repo_labels / gh_json / outputs）
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
- レート制限: tasks 既定 2.0 req/sec（`ms_data/scraping/defaults.py` の `DEFAULT_RATE`）、直接CLIは既定1.0 req/sec（`DEFAULT_CLI_RATE`）。atwiki への負荷を考慮し過度な緩和は避ける。待機は実際のネットワーク取得時のみ（キャッシュヒットは待機しない）。2回目以降は `NO_NET=1` でキャッシュのみ利用可。
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
- 自動レビュー/マージ: `auto review merge` は `data update` 成功後の `workflow_run` で起動する。Codex 側 Automatic reviews を優先し、ファイル指摘が 0 件なら自動マージする。attempt 1 から `@codex review` を投稿する（初回は review マーカー、リトライは retry マーカー）。投稿名義は Secret `CODEX_TRIGGER_PAT`（fine-grained: Issues read/write・Pull requests read/write・Metadata read）があれば PAT（人間）名義、なければ bot（github-actions）名義（2026-07-20〜27 の Codex 側 bot 名義拒絶が解消したことを確認済み。再発時は停止メール→手動 `@codex review` → resume 回収で運用）。merge は常に `github.token`（PAT は使わない）。merge 直前に HEAD SHA を再確認し、不一致ならスキップする。共通 merge 経路で同一 HEAD・ブランチの最新 pull_request `ci.yml` run の completed/success を必須とする（auto review / resume 共通）。未検出・未完了・失敗・対象不一致・API取得異常は停止し、停止理由を Step Summary に記録する。data-only PR の checks スキップは workflow 全体の成功で判定する。
- 対象PRの解決: `data/auto-update-YYYYMMDD`（workflow_run.created_at の JST 日付）を優先し、無ければ open な最新 `data/auto-update-*` にフォールバック。 PR payload のアクセサ（head/base ref・sha、REST/GraphQL 両キー対応）と `source_run_id:N` マーカー解釈は `ms_data/gh/pr_payload.py` に集約（auto_review / cleanup / post_merge で共用）。
- dry-run: `data update` の `workflow_dispatch` で `dry_run=true` を指定すると、取得・監査・artifact 作成まで実行し PR 作成と通知は行いません。
- 古いPR整理: `cleanup auto update prs` が毎日 20:30 JST に実行され、`keep_days` 超過の open PR を close（head ブランチも削除）。
- レポート整理: `reports prune` が毎月1日 18:00 JST に実行され、`reports_manifest.json` の `prune`（max_age_days / keep_min）に基づき期限切れレポートの削除 PR を作成します。この PR は自動マージ対象外のため人間がレビューしてマージします。
- PRラベル: 自動更新 PR には `data-update` / `rollback-guard` / `official-overrides` / `atwiki-quality` を付与。ラベル名・説明・色の SSOT は `ms_data/gh/repo_labels.py`（`uv run python -m ms_data.gh.repo_labels <names...>` で冪等作成、Issue 通知モジュールも同定義を参照）。
- reports 運用SSOT: 命名規約・分類・保持方針は `reports_manifest.json` が正。契約検証は `uv run python -m ms_data.validation.validate_report_contract`、生成物検証は `uv run python -m ms_data.tasks validate-generated-reports`。
- 手動更新レポート: 手動でデータ更新した場合は `reports/YYYY/MM/msdata_update_YYYYMMDD.md` を `reports/msdata_update_template.md` に沿って作成（新規追加機体は主要パラメータを網羅、既存更新は変更前後の値を明記）。
- 失敗時の挙動: findings / no_response / disconnected で停止した場合は自動マージせず PR を残し、`GMAIL_ADDRESS` 宛（本人のみ）に停止メールを送信して手動対応。
- 翌朝レスキュー: `resume auto review` が毎朝 09:00 JST（cron `0 0 * * *`）と `workflow_dispatch` で起動し、停止 PR を自動回収する（手動 `@codex review` 後のマージ回収を含む）。回収対象の停止理由は `codex_no_response` / `codex_disconnected` / `ci_approval_timeout`。`ci_approval_timeout`（CI 承認後の完了待ちだけで停止）は merge ステップが停止マーカーを投稿し、resume が最新 HEAD CI の成功を共通 merge 経路で再確認してからマージする。`auto review merge` と同一 concurrency group（`msdata-auto-review-merge`）を共有。
- 持ち越し指摘: GitHub は行が変わらない未解決レビューコメントの `commit_id` を新しい HEAD へ付け替える（`original_commit_id` は投稿時のまま）。旧 HEAD から持ち越された未解決指摘だけでは即停止せず、現 HEAD の Codex 結果を待つ。現 HEAD で終端シグナル（no-issue 受領コメント等）が出れば持ち越し指摘は無視し、出ないまま打ち切られた場合は従来どおり findings で停止する（`ms_data/gh/auto_review_gate.py`、PR #339 の 2026-10-20 停止が実例）。
- Codexレビュー待ち: 既定 3 回まで試行。調整は repository variables の `CODEX_REVIEW_MAX_ATTEMPTS` / `CODEX_REVIEW_ATTEMPT_TIMEOUT_SECONDS` / `CODEX_REVIEW_POLL_SECONDS` / `CODEX_REVIEW_SETTLE_SECONDS`。
- 通知: マージ後に `post merge notify` が Release アセット作成とメール送信を行います。本文は `reports/YYYY/MM/diff_msdata_YYYYMMDD.md` から生成、添付は `msData.json`。差分ゼロの定期実行時は `data update` から「差分なし」報告メールを送信。idempotency キーは `source_run_id + head_ref`。
- 通知メールの件名: 全通知を `【状態】msData 種類 日付やPR番号（要点）` に統一する（状態は `要対応` / `変更あり` / `変更なし` / `失敗`、カッコは全角）。日次・部分保留・更新反映は `build_update_mail_body --subject-out` が本文と同じ対応要否判定から件名を作り、`send_gmail --subject-file` で送る。共通形式は `ms_data/notify/subjects.py`（Issue #350）。自動マージ停止・パイプライン失敗の通知は `ms_data/notify/notice_html.py` で日次と同じ見た目の HTML カードとテキスト版を同じ表示モデルから作り、Codex 指摘は優先度・要点・ファイル:行・指摘コメントへのリンクのみを出す（本文の GitHub 記法は出さない。`notify failure` は依存未導入の python3 で動くため、`notice_html.py` は標準ライブラリだけで HTML を組み立てる。Issue #351）。日次メールの技術情報は平常時「取得の概要」1行にまとめ、一覧の更新経過時間読み取り率が `detect-changed` の実際のしきい値（`MIN_AGE_COVERAGE`、既定 0.95）未満の日だけ上部の要確認カードと【要対応】件名で知らせる。しきい値と読み取り率は検出サマリの出力として変更なし・部分保留メールへ、atwiki品質レポートの `index` 経由で更新反映メールへ渡す。期限到達・補正維持がない日は「補正値の維持と期限」を出さない（Issue #352）。msData.json の添付は宛先確認まで現状維持。
- メール秘匿運用（重要）: `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `GMAIL_TO` / `CODEX_TRIGGER_PAT` は必ず GitHub **Secrets** 経由で渡します（public リポジトリではログが公開されるため、`vars.` への変更や `echo` でのデバッグ出力は禁止。Secrets はログで自動マスクされます）。`GMAIL_TO` はカンマ区切りで複数宛先可。値の参照は不可のため変更時は最終文字列で上書き。自動レビュー停止メールは宛先を `GMAIL_ADDRESS`（本人のみ）に固定する。
- 生成元追跡: 実行ごとに `reports/YYYY/MM/provenance_YYYYMMDD.json`（index/details/html のハッシュ・件数・source_run_id）を生成。
- 巻き戻り対策: `reports/YYYY/MM/rollback_guard_YYYYMMDD.md` と `reports/YYYY/MM/official_overrides_audit_YYYYMMDD.md` を生成。protected rollback は自動更新を失敗させます。
- 取得元スロット異常: `source_slot_audit_YYYYMMDD.md` と `SOURCE_SLOT_AUDIT_OUT` に原値・比較・処置を保存。限定LV検査の未承認異常は対象機体＋LV全体だけ更新保留し、正常候補は既存ゲートで継続。正常な前値がない既存レコードは `previous_unverified_retained` と明示し推測修正・削除しない。schema/意味エラー・従来protected rollbackは隔離で隠さない。本人通知は `GMAIL_ADDRESS` のみ、dry-runは送信しない。検査範囲・補正の適用期限は [README.md](README.md) と [data/README.md](data/README.md) を参照。
- 取得元抜粋（レビュー照合用）: atwiki は Cloudflare のチャレンジ（403）を返すため、Codex やクラウドのエージェントからは wiki を直接閲覧できない（Actions からの取得は成功する）。そのため `data update` は `ms_data.reporting.build_source_excerpt` で、変更・追加項目ごとに Actions が取得した `cache/html` の該当行（行見出し原文・LV別セル）、取得時刻・HTTP・wiki_url を `reports/YYYY/MM/source_excerpt_YYYYMMDD.md` に保存し、PR 本文にも上限20件で載せる。照合の `不一致` は公式調整オーバーライド・LV単位保留・前LV補完などの後処理の可能性を示し、直ちに誤りではない。
- 生データアーカイブ: 実行ごとに `raw_snapshot_*.tar.xz` を artifact（90日）へ、マージ後に Release tag `raw-snapshot-YYYYMMDD-run-<run_id>` へ恒久保存。
- 復元手順: 対象コミットの provenance から `release.tag` を取得し、`uv run python -m ms_data.tasks restore-snapshot SNAPSHOT=... OUT_DIR=restore_tmp` で `cache/` と `reports/` を再構成（ファイルが HEAD から prune 済みでも `git log -- <path>` + `git show` で provenance 自体を辿れます）。復元CI: `verify-snapshot-restore`。
- official_overrides 期限管理: 各 entry に `review_after` / `remove_after` を設定。期限到達時は `data update` が Step Summary に件数を出し、protected rollback 0 件なら Issue `official_overrides 期限確認` を作成/追記（`ms_data/gh/notify_override_due.py`）。直前の通知と `review_due` / `remove_due` および監査出力 `due_fingerprint`（期限対象・補正値・期限設定の SHA256）がすべて同じなら skipped にして日次の同文コメントを抑止。件数が同じでも対象や設定の変更時は通知する。本文末尾の `<!-- override-due ... fingerprint=... -->` マーカーで追跡し、識別子のない旧通知には一度追記して比較基準を確立する。識別子未指定の呼出しでは抑止しない。スキーマは `schema/official_overrides.schema.json`（`MS名` / `values` / `stale_values` 必須）。
- official_overrides 期限確認 Issue の対応手順（大規模調整のたびに繰り返す）: 監査レポートの状態別に、`upstream_current`（atwiki 反映済み）と `source_changed`（stale 不一致で不発化）は entry を撤去、`protected_by_override`（未反映）は存続させ `review_after` を延長。全 entry 撤去後はファイルごと削除する（ディレクトリは `.gitkeep` で維持。空でも `validate-official-overrides-schema` は OK）。例: Issue #113 → PR #145。
- atwiki取得品質: `reports/YYYY/MM/atwiki_quality_YYYYMMDD.json` に HTTP 状態・304件数・失敗推定・レコード数・差分件数を記録。しきい値超過は warnings として PR 本文・Step Summary に警告（`ATWIKI_QUALITY_*` 変数で調整）。
- notify failure: `workflow_run` で 6 ワークフロー（`data update` / `auto review merge` / `resume auto review` / `post merge notify` / `cleanup auto update prs` / `reports prune`）の `failure` / `timed_out` / `startup_failure` / `action_required` を監視し、GMAIL Secrets によるメール送信と `pipeline-failure` ラベル付き Issue 起票を行う（`ms_data/gh/notify_failure.py`、stdlib のみで動作、重複 Issue の自己修復あり）。
- ci の changes ジョブ: PR がデータ・レポート・md のみの変更なら checks（ubuntu/windows マトリクス）をスキップ。`tests/` 配下と削除は `code=true`。changes ジョブ自身が report-contract / msData / generated-reports の軽量検証を実施。actionlint は checks ジョブ（ubuntu）で実行。
- `.github/actions/resolve-codex-pat`: `CODEX_TRIGGER_PAT` のログイン解決（`pat_available` / `pat_login` を出力、失敗時は警告のみで bot 名義へフォールバック）。`auto review merge` / `resume auto review` で共用。
- `.github/actions/setup-uv-env`: Python 3.11 + uv + `uv sync --dev` の composite action。`ci` / `data update` / `auto review merge` / `resume auto review` / `post merge notify` / `reports prune` で共用（Python バージョン変更はここが主変更点）。`notify failure` と `cleanup auto update prs` は uv 不要のため未使用。
- CI runner: Windows は `windows-2025-vs2026` を明示使用。`windows-latest` へ戻す場合は GitHub の runner image 移行状況を確認。
- 互換期間: レポート再編時の旧パス互換は原則検討するが、v3 の年月階層化（`reports/YYYY/MM/`）は破壊的移行として実施済み（`legacy_path_support: false`、旧パスへの転送なし）。日付付きレポートの旧フラット `path_patterns` は撤去済み（直下に残す undated / テンプレートのみ許容）。

### 自動マージ停止時の切り分け・復旧（Issue #328 / PR #329）
- 最初に対象 PR の現在の HEAD SHA・ブランチと、失敗した auto review run の時刻を固定する。通常ログの `Latest HEAD CI`（run_id / attempt / status / conclusion）、`Merge stopped`（reason / pr_state）、Step Summary、auto review report を照合する。レビューゲートの `merge_ok=true` だけでは CI 成功やマージ完了を意味しない。
- CI を再実行すると同じ run ID の最新表示が更新される。障害時の原因は `GET /repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{attempt_number}` と同 attempt の `/jobs` まで調べ、当時の状態と復旧後の状態を分けて記録する。最新の success だけで障害時も成功していたと判断しない。
- `GITHUB_TOKEN` で作成・更新した PR の `pull_request` CI は実行承認待ちになり得る。`action_required`・ジョブ0件なら、PR の「Approve workflows to run」と初回 attempt を優先確認する。これは直ちにマージ権限不足やコード不具合を意味しない。本人了承（2026-10-16）により、同一リポジトリ・Bot作成・main向けの定期更新ブランチで、msData.jsonと所定の当日レポートのみを変更するPRはCI実行承認を自動化する。元処理が未完了なら最大2分待ち、元data updateのmainブランチ実行（ref接尾辞はなし/@main/@refs/heads/mainのみ）と成功、対象CI/HEAD/作成者、ジョブ0件を検証して承認APIを1回だけ呼び、最大15分CI成功を待つ（2026-10-22 #359 でジョブ自体は20秒で終わったが run の完了確定に約12分かかり、5分で停止したため延長）。対象外、API拒否、失敗、タイムアウトは停止する。PATへの置換や権限の拡大は行わない。API拒否時は対象リンクと必要なActions write権限・write権限者による実行承認を具体的に伝える。
- 自動承認の本線は auto review / resume の共通merge経路で、承認待ちを検出すると`ms_data.gh.auto_ci_approval`で対象検証・実行承認し、承認後に最新HEAD CIを再取得する。Codexレビュー判定を通過するまで到達しないため、レビューで停止したPRのCIは承認待ちのまま残る。
- `approve data CI`（`.github/workflows/approve_data_ci.yml`）は`workflow_dispatch`の`run_id`で既存の承認待ちCIを手動承認するための入口で、信頼されたmain上で同じ検証を行い、auto review / resumeと同一concurrency groupで直列化する。データ更新PRのCIは`GITHUB_TOKEN`由来のため、ciの完了を受ける`workflow_run`は発火しない（Issue #341: 10/16〜10/20の4件すべて未起動）。`workflow_run`トリガーを戻さない。承認はCI実行の許可であり、Codexレビューやマージ承認を代替しない。
- CI 成功後は、現在の HEAD がレビュー済み SHA と一致し、同一 HEAD・ブランチの最新 `ci.yml` が completed/success であることを確認し、既存の auto review merge の失敗ジョブを再実行する。古い成功 run へのフォールバックや手動の直接マージでゲートを飛ばさない。レビュー対象 HEAD が変わっていたら新 HEAD の CI とレビューを必要とする。
- 完了判定は PR の merged / merge commit SHA、auto review run、post merge notify の Release 公開・メール送信処理まで確認する。メール送信成功と端末への配達確認は区別する。修正は Issue → PR → CI → レビューで進め、別件のデータ補正 PR と混在させない。
- 2026-10-15 の実例: PR #327 の CI run 38746722160 は attempt 1 が action_required、attempt 2 が success。既存ゲート維持のまま auto review run 38746738277 の attempt 2 で復旧した。PR #329 は診断ログのみ追加したもので、承認待ち自体を自動解消する変更ではない。
- 仕様確認先: [GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)、[Bot-created pull requests can run workflows if approved](https://github.blog/changelog/2026-06-11-bot-created-pull-requests-can-run-workflows-if-approved/)。実際の状態は毎回 GitHub の最新情報を確認する。

## Review guidelines
- 自動更新 PR（`data/auto-update-*`）の取得元照合は、PR 本文の「取得元抜粋」と `reports/YYYY/MM/source_excerpt_YYYYMMDD.md` を根拠に行う。atwiki はレビュー環境から直接閲覧できない前提とし、記憶や過去の値だけを根拠に「取得元と一致しない」と指摘しない。
- 抜粋で `一致` の項目は、値の増減だけを理由に差し戻さない（atwiki 側の誤記修正で値が下がることがある。例: PR #339 の中スロット 29→20）。`不一致` や `HTMLなし` の項目は、後処理（公式調整オーバーライド・LV単位保留・前LV補完）で説明できるかを確認して指摘する。

## 仕様・挙動変更時のドキュメント先行
- 仕様や挙動を変更する場合は、コード・ワークフロー等の実装を変更する前に、対象の既存の正本ドキュメントへ変更の目的・期待動作・影響範囲・検証計画を反映する。
- 仕様・抽出ルール・Actions 運用の正本は本ファイル（`AGENTS.md`）。変更内容に応じて、利用者向け説明は `README.md` / `docs/msdata_reference.md`、データ運用は `data/README.md` 等の該当する既存文書も更新する。機械検証は `schema/`、レポート契約は `reports_manifest.json` 等の既存 SSOT を維持し、同じ仕様の別の正本を新設しない。
- 計画中・未実装の内容は「変更予定（未実装）」等と明記し、現行動作と区別する。文書を先に更新しただけで、実装済み・検証済みと記載しない。PR 本文にも対象の正本と未完了事項を記載する。
- 実装・検証後は実際の挙動と文書を照合し、計画からの差分や状態表示を更新する。PR には実施した検証と結果、未実施・失敗した項目を明記する。
- 既存仕様に沿った通常の日次データ更新・生成レポート更新、誤字修正や挙動を変えない軽微な修正では、この手順のためだけの文書追加・更新は不要。既存の更新レポート・来歴・監査の記録要件は維持する。抽出・補正・検証・通知・自動更新のルール自体を変える場合は、日次更新に関わる変更でも先行更新の対象とする。
- この手順は既存の保護を緩めない。schema・意味検証・protected rollback、取得元異常の保留、レビュー・同一 HEAD の CI 成功確認等の日次更新のゲートは引き続き適用する。

## コーディング規約・テスト
- JSON: 2スペース、UTF-8、LF、キーは `snake_case`。
- Python: インデント4スペース、型ヒント必須（`str | None` 形式を推奨）。命名はファイル/関数 lower_snake_case、クラス CapWords。
- ツール: `black`（88列）/ `ruff` / `pytest` を uv で管理。
- テスト: `tests/test_*.py`。変換/検証ロジックは目安80%以上をカバーし、エッジケースと不正入力を含める。
- テスト共有ヘルパー: `tests/helpers.py`（MS レコード factory `make_ms_record` / `make_minimal_ms_record`、`write_json`）、`tests/workflow_contract.py`（ワークフローのステップ切り出しと必須/禁止部分文字列アサート）、`tests/auto_review_helpers.py`（auto_review cmd_* 用スタブ）。`from helpers import ...` のように素の名前で import する（`__init__.py` は置かない）。
- 共通処理は `ms_data/core` 等の既存ユーティリティを再利用し、コピペ実装を作らない。
- 既定パスは `ms_data/core/paths.py` を SSOT とし、各 CLI の argparse `default=` はそこを参照する（`tests/test_path_defaults_sync.py` が直書きの再発を検出する）。
- 通知メールなどHTMLの表示を作成・変更するときは、Avoid unnecessary secondary labels and descriptions. Let the layout do the explaining.（不要な補助ラベルや説明文は避け、レイアウトに説明させる。）文字サイズ・太さ・余白の階層で重要度と区切りを表す。まとまりは配置と余白で示し、見出しや説明文を足して補わない。対応要否・状態・件数など、判断に必要な情報は削らない。

## コミット・プルリクエスト
- コミットメッセージは日本語。Conventional Commits を採用: `feat:` `fix:` `docs:` `chore:` `refactor:` `test:` `data:`（データのみ変更）。
  - 例: `data: msData.json を更新（2025-09-05; +123/-45 件）` / `fix(update): 宇宙専用時の旋回値を宇宙側へ寄せ替え`
- PR は小さく焦点を絞り、変更概要・データ来歴・検証結果（`validate-strict` / 差分統計 `records: A -> B | +X -Y ~Z`）・影響範囲を記載。
- `gh pr create` で本文にバッククォートを含める場合は `--body-file` を推奨。
- Issue / PR テンプレート: `.github/ISSUE_TEMPLATE/` と `.github/PULL_REQUEST_TEMPLATE.md` を使用（すべて日本語）。

### Codexレビュー依頼手順（Issue #314）
- コード・文書変更 PR のレビューは GitHub 上の Codex（Automatic reviews または PR コメント `@codex review`）を標準経路とする。下記の CLI（`codex exec`）は任意のローカル事前確認で、必須にせず、GitHub レビューと重ねて起動しない。CLI が起動できないことをブロッカーにしない。
- 依頼の流れ: 対象 PR か確認 → 最新 HEAD に Codex レビューが実行中（👀）または完了済みでないか確認 → どちらもない場合に `@codex review` を投稿 → 指摘に対応 → 新 HEAD のレビュー結果と必要 CI を確認 → 承認された範囲でマージ。
- レビュー対象の HEAD は、Review Summary の Commit 列か受領コメントの `Reviewed commit` が現 HEAD と一致するかで判断する。インライン指摘の `commit_id` は push 後に新 HEAD へ付け替えられるため（上記「持ち越し指摘」）、`original_commit_id` が旧 HEAD の未解決指摘があっても、現 HEAD のレビュー完了とはみなさない。
- 必要なレビューは回数を制限しない（新 HEAD への再依頼、無応答・失敗時の再依頼を含む）。ただし、同じ HEAD でレビューが実行中のときと、すでに完了していて変更がないときは依頼を重ねない。Draft→Ready の往復、空コミット、workflow 再実行をレビュー再起動の目的で使わない。
- 無応答時は実行中・完了・失敗の表示を確認してから再依頼し、PR に理由を残す。失敗・利用量不足で進められない場合は停止して本人に伝え、レビューや CI を省略してマージしない。
- 対象は本リポジトリで本人が依頼・承認した PR に限る。Codex 側の対象リポジトリ・Review trigger・利用量の設定は Codex の設定画面で管理し、本ファイルの文言をアクセス制御とみなさない。
- データ自動更新 PR（`data/auto-update-*`）は上記「GitHub Actions 運用」の auto review / resume の仕組み（対象選定・マーカーによる投稿抑止・既定 3 試行）をそのまま使う。コード変更が混ざった PR はデータ更新扱いにしない。

#### CLI での任意の事前確認
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
