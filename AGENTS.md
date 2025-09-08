# Repository Guidelines

## 言語ポリシー
- 本リポジトリのコミュニケーションは原則「日本語」です（Issue/PR/コメント/ドキュメント/コミットメッセージ）。本ガイドも日本語で提供します。

## プロジェクト構成・モジュール整理
- 目的: 本リポジトリは主に `msData.json` を管理します。将来的に更新用の Python スクリプトを追加します。
- 推奨構成:
  - `scripts/`: データ更新・検証スクリプト（Python）。
  - `tests/`: スクリプトのユニットテスト。
  - `schema/`: JSON スキーマ（任意、バリデーション用）。
  - `data/`（任意）: 原データや一時生成物。
  - `pyproject.toml`: 依存とツール設定（uv 管理）。

## ビルド・テスト・開発コマンド（uv）
- 環境作成: `uv venv`（任意で `-p 3.11`）。実行は基本 `uv run <cmd>` を使用。
- 依存追加: `uv add black ruff pytest jsonschema`（`pyproject.toml` に記録）。
- JSON 構文チェック: `jq . msData.json > /dev/null` または `uv run python -m json.tool msData.json > /dev/null`
- 整形・キーソート: `jq -S '.' msData.json > msData.pretty.json`
- テスト: `uv run pytest -q`（`tests/` 配下）
- フォーマット/リンタ: `uv run black . && uv run ruff .`

### Makefile（ショートカット）
- 初期化: `make setup`
- 更新: `make update INPUT=path/to/new.json`（入力なしで正規化のみ）
- 検証: `make validate`（厳格: `make validate-strict`）
- 品質チェック: `make format && make lint && make test` または `make ci`

## スクレイピング手順（atwiki）
- 一覧取得: `uv run python scripts/scrape_msdata.py index --url https://w.atwiki.jp/battle-operation2/pages/377.html --out cache/index.json`
- 詳細取得: `uv run python scripts/scrape_msdata.py details --in cache/index.json --out cache/details.jsonl --rate 1.0`
- 連続実行: `uv run python scripts/scrape_msdata.py all --out cache/details.jsonl`
- 取り込み: `jq -s '.' cache/details.jsonl > cache/details.json && uv run python scripts/update_msdata.py -i cache/details.json`

注意（SSOT）
- 本リポジトリでは index（`cache/index.json`）の `name` を真実のソース（SSOT）とし、詳細抽出の `MS名` も index の表記で固定します（LVは `_LVn` で付与）。
- 既存/新規データの読み込み時に `update_msdata.py` 側でも名称を index 準拠へ正規化します。

## ラベル正規化と監査（2025-09）
- 目的: 各機体ページの行見出し（項目名）の揺らぎを収集・正規化し、最終パラメータへ安全に変換。
- 共通ユーティリティ: `scripts/label_utils.py`
  - 行見出しの軽正規化: 空白圧縮、半角()注記除去（全角（）は保持）
  - FIELD_MAP: 行見出し → 正規キー（変形/変身や山括弧の順序違いも吸収）
  - KEY_ALIASES: 出力JSONの誤記キー → 正規キー（射撃補則/射撃補生 など）
- 監査ツール: `scripts/audit_labels.py`
  - 出力: `reports/label_audit_YYYYMMDD.md`（unknown=0 を目標）
  - 除外: 属性（汎用/強襲/支援）は監査集計から除外
- 取得コマンド（キャッシュ対応）
  - 一覧: `make scrape-index TTL=7d`
  - 行見出し収集: `make labels LIMIT=0`（または小規模 `LIMIT=30`）
  - 集計: `make audit-labels`

## スキーマ拡張と補正ルール（要点）
- 追加キー（任意）
  - 速度系: `スピード_変形時`, `高速移動_変形時`
  - 旋回系: `旋回_地上_変形時`, `旋回_宇宙_変形時`, `旋回_変形時`
  - 補正系: `射撃補正_変形時`, `射撃補正_変身時`, `格闘補正_変形時`, `格闘補正_変身時`
  - 購入系: `レアリティ`, `必要階級`, `必要DP`, `必要リサイクルチケット`
  - 出撃可否: `出撃_地上可`, `出撃_宇宙可`
  - 環境適正: `環境適正_地上`, `環境適正_宇宙`, `環境適正_水中`
- 必須条件（緩和）
  - 旋回は anyOf（地上 or 宇宙のどちらか必須）。宇宙専用機を許容。
  - 実装状態: `scripts/scrape_msdata.py` の最終フィルタを anyOf に修正済み（宇宙専用でも除外されない）。
- 抽出ロジックの主な規則
  - 旋回値: `78（盾装備時：75.7）` → 先頭整数（78）を採用。
  - 出撃可否・環境適正: atwiki 固有ID（`label_sortie_*`, `label_env_*`）を最優先で解析。フォールバックで文言/表記号を解釈。
  - 不明時の推定: 旋回項目の有無から `出撃_地上可/出撃_宇宙可` を補完。
  - 補正（重要）: 宇宙専用/地上専用で単一見出しが逆側に入っている場合、適切な側へ回転値を寄せる（例: 宇宙専用+地上旋回のみ → 宇宙旋回へ移す）。

## キャッシュ運用（atwiki）
- 仕組み: `scripts/cache_http.py`（TTL=7日, If-None-Match/If-Modified-Since 対応）
- オプション: `--ttl 7d` / `--no-network` / `--force`
- 保存先: `cache/html/<slug>.html` + `*.meta.json`（ETag/Last-Modified/sha256）

## 実行スニペット（更新フロー）
- 全件詳細→取り込み→検証
  - `make scrape-details TTL=7d RATE=1.0 LIMIT=0`
  - `make import-details`
  - `make validate`（厳格: `make validate-strict`）
- 差分要約はコマンド出力（`records: A -> B | +X -Y ~Z`）で確認
 - 監査（index vs msData）: `uv run python -m scripts.audit_index_vs_msdata --index cache/index.json --ms msData.json --out reports/index_ms_audit_YYYYMMDD.md`

## データ品質（2025-09-05 時点の要約）
- レコード: 1516
- 出撃: 両方可=1087, 地上のみ=415, 宇宙のみ=14, 不明=0（推定/補正で解消）
- 環境適正（True件数）: 地上=491, 宇宙=665, 水中=84
- 既知の残課題: `MS名` パターン不一致 1件（例: プロトΖガンダム［X1型］）

## 最終的な msData.json 作成計画（合意済み）
1) 監査を回す: `make labels LIMIT=0 && make audit-labels`（unknown=0確認）
2) 全件詳細取得: `make scrape-details TTL=7d RATE=1.0 LIMIT=0`
3) 取り込み: `make import-details`（回転/出撃の補正・推定を含む）
4) 検証: `make validate-strict`（スキーマ/重複/別名チェック）
5) 差分確認: `git diff -- msData.json`（件数/キー変更）
6) コミット/PR: 来歴・統計・補正ルールを記載（このAGENTS.mdを参照）

## 抽出・正規化ポリシー（更新）
- 行ラベル正規化: 半角カッコの注記（例: `( +25 )`）のみ除去。全角カッコ（例: `旋回（地上）/（宇宙）`）は保持。
- 旋回値の抽出: `81（盾装備時：78.6）` の表記は先頭の整数（`81`）を採用。
- fullst（強化リスト）: 形式は `[{name, level, points?}]`。
  - 「MSレベル毎必要強化値」に数値がある行のみ採用し、MSレベル別に `points` 昇順で整列。
  - 同一リスト名は“数値があるLvの最小/最大（上限開放）”を採用。
  - 高Lvが未掲載の場合は直前Lvで補完（`points: null`）。
- 再出撃時間: 秒を整数で抽出。
- 余白統一: 連続する空白は1つへ圧縮（全角空白も半角空白に集約）。

MS名の正規化（index準拠）
- 目的: `msData.json` の基底名を `cache/index.json` の `name` と一致させ、JOIN 安定化と重複解消を図る。
- 適用タイミング: 詳細抽出の書き出し時（scrape）／読み込み・マージ時（update）。
- 変換ルール（限定的な文脈置換を含む）
  - 半角→全角括弧: `[]` → `［］`
  - ローマ数字: `II/III` → `Ⅱ/Ⅲ`
  - Ζ表記: `Z/ZZ` → `Ζ/ΖΖ`（「ガンダム/ガンダム3号機」の直前のみ）
  - 全角V: `Ｖ` → `V`

備考
- PC版のみの機体（index未収載）が `msData.json` に存在する場合は例外として維持します（監査では msData のみ=3 件として残る想定）。

## コーディング規約・命名
- JSON: 2スペース、UTF-8、LF、キーは `snake_case`。
- Python: インデント4スペース、型ヒント必須、関数は純粋/再利用可能に。
- 命名: ファイル/関数は lower_snake_case、クラスは CapWords。
- データファイル名: `dataset_<topic>_<YYYYMMDD>.json`（例: `dataset_ms_20250115.json`）。
- ツール: `black`（88列）/`ruff`/`pytest` を uv で管理。必要に応じて `mypy`。

## テスト方針
- `tests/` に配置。命名は `test_*.py`。
- 変換/検証ロジックは目安80%以上をカバー。エッジケースと不正入力を含める。
- スキーマ導入時（例: `schema/msData.schema.json`）は CI で `jsonschema` などによる検証を実施。

## データ仕様・取得対象（msData.json）
- 構造: 配列（各要素=MSの1レベル）。主キー相当: `MS名`（例: `XXX_LV1`）。
- 必須項目: `MS名`, `属性`（汎用/強襲/支援）, `コスト`, `HP`, `スピード`, `スラスター`, `高速移動`, `射撃補正`, `格闘補正`, `耐ビーム補正`, `耐実弾補正`, `耐格闘補正`, `近スロット`, `中スロット`, `遠スロット`, `旋回_地上_通常時`（可能なら `旋回_宇宙_通常時`）。
- 追加項目: `カウンター`（文字列）, `再出撃時間`（秒・任意）, `fullst`（`[{name, level, points?}]` の配列）。
- `fullst` 取得ルール: 各機体ページの「強化リスト情報」表から抽出。
  - 「MSレベル毎必要強化値」に数値がある行のみ採用（空欄Lvは除外）。
  - 同一リスト名は“数値があるLvの最小/最大（上限開放）”を採用。
  - 高Lvの強化リストが未掲載の場合は直前のLvを補完（`points: null`）。
- 正規化ルール（表記揺れ吸収）:
  - `射撃補則`/`射撃補生` → `射撃補正`、`格闘補定` → `格闘補正`
  - `旋回_通常時_地上` → `旋回_地上_通常時`、`旋回_通常時_宇宙` → `旋回_宇宙_通常時`
  - `格闘判定力` は原文保持＋任意で正規化（例: 弱/中/強/強+）。
- 値の目安: `コスト` 200–750、`HP` 11,000–34,000、`スピード` 75–160、`高速移動` 150–235（2025-09 時点のデータより）。

## データ更新フロー（推奨）
注意: 現在、`msData.json` への自動取り込みは停止中です。取得結果は `cache/` でスポット検証・レビュー後に反映してください。
1) ブランチ作成: `git switch -c data/update-YYYYMMDD`
2) データ取得・変換: `uv run python scripts/update_msdata.py -i [入力JSON…]` で `msData.json` を生成/更新。
3) 整形固定: `jq -S '.' msData.json > msData.json.tmp && mv msData.json.tmp msData.json`
4) 検証: `uv run python scripts/validate_msdata.py msData.json` と `uv run pytest -q`
5) 差分確認: `git diff -- msData.json`（件数/キー変更点を要約）
6) コミット: `data: update msData.json (YYYY-MM-DD; +N/-M records)`
7) PR: 変更概要・データ来歴・統計（件数/キー変更）を記載。

## 取得元と更新頻度（推奨）
- 取得元: 公式リリースノート/ゲーム内ステータス/信頼できる Wiki。
- 更新頻度: 公式アップデートごと。バランス調整時は速やかに反映。
- 監査: 重要指標（補正・耐性・コスト）の差分は PR 説明に数値で記載。

## スキル抽出/所有逆引き（2025-09 セッション要約）
- 方針（合意）
  - msData.json は恒常値のみとし、スキルは別ファイルで管理（アプリ側で合成）。
  - 定義（param）と所有（owners）を分離し、レビュー/保守性を優先。
- 追加コマンド（Make）
  - `make skills-table` … atwiki「スキル一覧表」の“表の行”を厳格抽出（rowspan継承含む）→ `cache/skills_table.json`
  - `make owners-table` … 「所持機体 逆引き一覧」の“表の行”を厳格抽出（アンカー境界停止・rowspan対応）→ `cache/owners_table.json`
  - `make build-param-skills` … パラメータ変化スキルのみを抽出（ホワイトリスト）→ `data/skills_params.json`
  - `make build-owners-flat` … シリーズ×機体Lv展開（msData から存在LvをJOIN）→ `data/skill_owners_flat.json`
  - `make preview-params` … parameter-only の合成プレビュー（MS単位）→ `derived/ms_params_preview.json`
- 抽出ポリシー
  - 対象パラメータ: スピード/高速移動/射撃補正/格闘補正/旋回/各耐性（3耐展開）/スラスター消費（係数）/被ダメージ（係数）
  - ホワイトリスト: 能力UP系（EXAM/HADES/HADES-E/ALICE/ZEUS/THEMIS/n_i_t_r_o/各種バイオセンサー/覚醒 など）
  - 逆引きテーブル: アンカー行自身の所有機体も取り込み、次のアンカー<th>が出現したらブロック終了。
  - シリーズ名の軽正規化: 半角()[]→全角（）［］、空白圧縮。JOIN 安定化。
- 代表例（現行抽出）
  - HADES LV1 所有: トーリス・リッター / ペイルライダー［空間戦仕様］/［陸戦重装備仕様］/（VG）
  - n_i_t_r_o 所有: ガンダムデルタカイのみ
  - 簡易バイオセンサー: 耐ビ+20 / 耐実+10 / 耐格+10（個別耐性値をそのまま採用）
- 設計判断
  - msData へプレビュー値は埋め込まない（アプリ側で合成）。必要に応じて `derived/ms_params_preview.json` を生成してレビュー。
  - owners/params の SSOT 化（`data/skills_params.json`, `data/skill_owners_flat.json`）。

### 今後の課題/ToDo
- シリーズ名の正規化強化（例: （通常）/（変形）注記の扱い、別名テーブル）。unknown=0の維持。
- 例外ルール: 同シリーズ内でも Lv によりスキル Lv が変わる場合の rules（range指定）導入。
- パラメータ抽出の拡張/安定化
  - ラベル近傍抽出のチューニング（誤検知/取りこぼしの監査をレポート化）。
  - 被ダメ/スラスター以外の係数系が判明した場合の追加。
- 二段階/フェイズ系（NT-D→覚醒など）の扱い整理（適用順序と排他条件）。
- スキルIDの正規ID体系（英小文字スネーク）を併記し、JOINを安定化。
- CI 連携: `build-*` と監査（unknown検出）を optional チェックに追加。

### データ/ファイル運用
- 配布本体: `msData.json`（恒常値のみ）
- 定義/所有: `data/skills_params.json`, `data/skill_owners_flat.json`（SSOT）
- レビュー用: `derived/ms_params_preview.json`（任意生成）
- キャッシュ/HTMLは `.gitignore` 済み。不要な一時HTMLはコミットしない（必要なら `cache/` のみ保存）。

### 監査記録（この時点）
- owners 監査（reports/owners_flat_audit.json）
  - unknown_series_count: 0（シリーズ名正規化で解消済み）
  - owners_count: 75（能力UP系の所持シリーズ×Lv 展開）
- params 監査（reports/skills_params_audit.json）
  - ホワイトリスト外だが数値を含む行を「excluded_param_rows」に記録（例: 空中制御プログラム/EXブースト/シールド・ブースター制御機構 等）。
  - 本リポジトリでは能力UP系のみを対象にし、その他は除外（将来の拡張時に再検討）。

#### index vs msData 監査（2025-09-08 反映）
- SSOT=index 準拠の名称統一後の結果
  - index（一覧）: 527
  - msData（基底名）: 530
  - indexのみ: 0
  - msDataのみ: 3（PC版: ウイングガンダムゼロ/ゴッドガンダム/フリーダムガンダム）
  - 属性/コスト不一致: 0

ツール
- `scripts/audit_index_vs_msdata.py` … 名称差分（正規化ポイント）、属性/コスト不一致、収載差（indexのみ/msのみ）をMarkdownで出力。

#### 参考: 過去の差分サマリ（2025-09-05 レポートより）
- レコード数: 546 → 1515（+970 / -1 / ~545）
- 追加キー（例）: スピード_変形時/射撃補正_変身時/格闘補正_変身時/出撃_地上可・宇宙可/環境適正_* など
- 誤記キーの整理: 射撃補則/射撃補生/格闘補定、旋回_通常時_* を正規キーへ統一
- 初回の owners 監査では unknown が多数（括弧注記や（通/変/通常）表記の揺れ）。シリーズ名の軽正規化で unknown=0 に解消。

## コミット・プルリクエスト
- コミットメッセージは日本語で記載してください（言語ポリシー順守）。
- Conventional Commits を採用: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `data:`（データのみ変更）。
  - 例）
    - `data: msData.json を更新（2025-09-05; +123/-45 件）`
    - `feat(scrape): 出撃可否・環境適正の抽出を追加（label_sortie/label_env 対応）`
    - `fix(update): 宇宙専用時の旋回値を宇宙側へ寄せ替え`
    - `docs: AGENTS.md に運用手順を追記`
- PR は小さく焦点を絞る。含める内容:
  - 変更概要とデータ来歴（ソース/取得日/処理手順）。
  - サンプルレコードや前後比較の統計（行数/ハッシュ差分）。
  - 関連 Issue、再現手順、UI/可視化が変わる場合はスクリーンショット。

## テンプレート方針（Issue / Pull Request）
- 言語: すべて日本語を原則とする（タイトル/本文/チェックリスト）。
- 配置（参考）: `.github/ISSUE_TEMPLATE/*.md`, `.github/PULL_REQUEST_TEMPLATE.md`。

### Issue テンプレート（推奨の種類）
- バグ報告（bug）
  - 概要: 何が起きたか（簡潔に）
  - 再現手順: ステップ/入力/コマンド
  - 期待結果 / 実結果
  - ログ/スクリーンショット（任意）
  - 影響範囲: 対象スクリプト/データ/環境
  - 環境情報: OS/uv/python/gh など
- 機能要望（feature）
  - 課題: 何を解決したいか（背景・目的）
  - 提案: 具体的な振る舞い/入出力/CLI 仕様（例コマンド）
  - 代替案/トレードオフ
  - 影響範囲/検証方針
- データ更新（data）
  - 取得ソース/取得日
  - 変更点の要約（+N/-M/主要キーの差分）
  - 検証結果（validate-strict/監査 unknown=0 など）
  - サンプルレコード（before/after）
- 質問/相談（question）・タスク（task）も最小限の背景/目的/完了条件を記載。

### Pull Request テンプレート（推奨構成）
- 概要: 何を、なぜ、どう変えたか（1〜3行）
- 変更点（箇条書き）
  - スキーマ変更/抽出ロジック/補正/ドキュメント など
- データ来歴（必要に応じて）
  - 取得日・ソースURL・処理コマンド（Make/CLI）
- 検証結果
  - `make validate-strict` の結果
  - 監査（labels）: unknown=0 の確認（必要時）
  - 差分統計: `records: A -> B | +X -Y ~Z`
- 影響範囲/後方互換性
- 関連 Issue / スクリーンショット（任意）
- チェックリスト（例）
  - [ ] `uv run black .` / `uv run ruff check .` を通過
  - [ ] `uv run pytest -q` を通過（ある場合）
  - [ ] `make validate-strict` を通過
  - [ ] 監査（必要時）で unknown=0 を確認
  - [ ] 差分の件数/要点を PR に記載
  - [ ] 影響範囲と後方互換性を説明

## セキュリティ・データ運用
- 秘密情報や個人情報をコミットしない。`.env` 等は `.gitignore` へ。
- 10MB 超やバイナリは Git LFS を使用: `git lfs track "data/**" "*.csv" "*.parquet"`。
- 再現性を重視: 依存関係のピン留め、乱数シード固定、デフォルト実行での外部ネットワーク依存を回避。
