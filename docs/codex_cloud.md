# 保存済みCodexクラウド環境の修復と再検証

対象はChatGPTのdotから選択する、保存済みのMS_dataクラウド環境です。
Mac・Windowsのローカル環境、GitHub Actions、旧Codex Cloudの設定とは区別します。
`AGENTS.md` のCursor Cloud専用のPython版や起動スクリプトの説明も、この環境へ流用しません。
この文書を追加しただけでは、保存環境の設定や既存タスクは変更されません。

## 先に実行先と並行作業を確認する

- dotのタスク一覧で、同じリポジトリの変更・テストを行うタスクが動いていないことを確認する。確認できない場合は新しいクラウドタスクを重ねて起動しない。
- 選択した保存環境、公開済みの版、タスクが使う版、作業場所を照合する。既存タスクが最新の公開版を使っているとは限らない。
- この環境のリポジトリは `/workspace/MS_data`。異なる場所なら、実行先を確認してからコマンドを調整する。
- `git status` は未追跡ファイルも含めて確認する。既存の変更を `reset --hard`、`clean`、強制checkoutで消さない。
- GitHub上のopen PRとActionsの確認も行う。ただし、Actionsが動いていないことはdot側のタスクが停止している証拠にはならない。

## 1. このタスクのuvキャッシュを修復する

2026-10-17の診断では `/home/agent/.cache/uv` が読取り専用で、
`/workspace/scratch` と `/tmp` への書込みは成功しました。
既存のマウントやOS権限を変更せず、uvの保存先を明示します。

次は既存のPython 3.11を使い、キャッシュだけを動作確認するコマンドです。
依存関係の同期、fetch、checkout、CI、Wiki取得は行いません。
同じ対象タスク内で実行してください。

```bash
bash <<'BASH'
set -euo pipefail
set +x
cd /workspace/MS_data
umask 077

export UV_CACHE_DIR=/tmp/ms-data-uv-cache
mkdir -p -- "$UV_CACHE_DIR"
probe=$(mktemp "$UV_CACHE_DIR/.write-probe.XXXXXXXX")
trap 'rm -f -- "$probe"' EXIT
printf x > "$probe"

.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11); print(sys.version.split()[0])'
uv --version
uv cache dir
uv run --offline --no-project --python "$PWD/.venv/bin/python" \
  python -c 'import sys; assert sys.version_info[:2] == (3, 11)'
test -f "$UV_CACHE_DIR/CACHEDIR.TAG"
printf 'cache_probe=passed\n'
BASH
```

`uv cache dir` が指定した保存先を指していることも確認します。
`--offline --no-project` の確認は、既存のPythonを用いたキャッシュ動作確認です。
PRのテスト成功を意味しません。ここで失敗したら、失敗したコマンドと終了コードを残し、
CIへ進みません。キャッシュへの書込み成功と、同期先 `.venv` への書込み成功は別です。

この `export` は上のシェル内だけに有効です。次のコマンド群でも明示し、
次回タスクへの反映は後述の保存環境設定で行います。

## 2. 成功している認証経路でPRのHEADを確認する

現在読取りが成功しているRESTコマンドまたはGitHubコネクタで、対象PRの
`number`、`state`、`draft`、`head.sha` を確認します。
クラウド内の `gh api` がその成功経路であると確認できた場合の例です。

```bash
env -u GH_DEBUG -u DEBUG GH_PROMPT_DISABLED=1 \
  gh api --method GET repos/murakotaro4/MS_data/pulls/326 \
  --jq '{number, state, draft, head_sha: .head.sha}'
```

RESTの成功をGraphQLの復旧や、gitの認証成功と読み替えません。
過去の `gh pr view` の401を繰り返したり、テストのために認証を交換したりしません。
ブランチ保護の読取りに必要な権限と、PR・コードの読取り権限も別です。

2026-10-17に確認したPR #326のHEADは
`527acc32372f3790c367b1b1a704006c4c49f7c2` です。
以下はこのHEADを再検証する例です。現在のPRのHEADが変わっていたら、
どのSHAを検証するのかを先に決め、別のSHAへ無条件に置き換えないでください。

## 3. 正しいHEADで固定依存関係と総合CIを確認する

並行作業がなく、上のキャッシュ動作確認が成功した対象タスクで実行します。
以下は既存のプロキシ・認証を引き継ぎ、依存関係を1回同期します。
`uv sync` はlockにない追加パッケージを取り除くことがあるため、
既存作業の途中のvenvを共有して実行しないでください。
`UV_PROJECT_ENVIRONMENT` が設定されている場合も一旦停止します。
値を公開せずに同期先を確認し、対象専用の `.venv` であることを確かめます。

uvの版は診断時の `0.12.19` を確認します。異なる場合は停止して理由を確認します。
Pythonは既存の3.11を使い、別バージョンへのフォールバックや自動ダウンロードをしません。
GitHub APIの読取りとは別にgitの取得が失敗する場合も、そこで停止します。

標準出力・標準エラーは、リポジトリ外の専用ディレクトリへ保存します。
ログにはコマンド出力が含まれるため、そのままPRやチャットへ貼らないでください。

```bash
bash <<'BASH'
set -euo pipefail
set +x
cd /workspace/MS_data
umask 077

expected_head=527acc32372f3790c367b1b1a704006c4c49f7c2
expected_uv=0.12.19
pr_number=326
log_dir=$(mktemp -d /tmp/ms-data-ci.XXXXXXXX)
printf 'private_log_dir=%s\n' "$log_dir"
exec 3>&1
exec >"$log_dir/commands.log" 2>&1
stage=checkout
ci_command_status=not_run
trap 'rc=$?; printf "stage=%s exit_code=%s ci_command=%s\n" "$stage" "$rc" "$ci_command_status" >&3' EXIT

status=$(git status --porcelain=v1 --untracked-files=all)
test -z "$status"
if ! git cat-file -e "$expected_head^{commit}" 2>/dev/null; then
  git fetch --no-tags origin "refs/pull/$pr_number/head"
  fetched_head=$(git rev-parse --verify 'FETCH_HEAD^{commit}')
  test "$fetched_head" = "$expected_head"
fi
# fetchが失敗した場合、set -eで停止し、古いFETCH_HEADを使わない。
git checkout --detach "$expected_head"
actual_head=$(git rev-parse --verify HEAD)
test "$actual_head" = "$expected_head"
status=$(git status --porcelain=v1 --untracked-files=all)
test -z "$status"
lock_before=$(sha256sum uv.lock)

stage=cache_and_uv
export UV_CACHE_DIR=/tmp/ms-data-uv-cache
export UV_PYTHON=3.11
export UV_PYTHON_DOWNLOADS=never
mkdir -p -- "$UV_CACHE_DIR"
probe=$(mktemp "$UV_CACHE_DIR/.write-probe.XXXXXXXX")
printf x > "$probe"
rm -- "$probe"
uv_line=$(uv --version)
[[ "$uv_line" == "uv $expected_uv" || "$uv_line" == "uv $expected_uv "* ]]
printf '%s\n' "$uv_line"
uv cache dir

stage=venv_target
test -z "${UV_PROJECT_ENVIRONMENT-}"
stage=dependencies
uv sync --locked --dev
stage=python
uv run --locked python -c 'import sys; print(sys.version); assert sys.version_info[:2] == (3, 11)'

stage=integrity_before_ci
actual_head=$(git rev-parse --verify HEAD)
test "$actual_head" = "$expected_head"
status=$(git status --porcelain=v1 --untracked-files=all)
test -z "$status"
lock_after=$(sha256sum uv.lock)
test "$lock_after" = "$lock_before"

stage=ci
ci_command_status=running
ci_exit=0
if env -u NO_NET uv run --locked python -m ms_data.tasks ci; then
  ci_command_status=passed
else
  ci_exit=$?
  ci_command_status="failed:$ci_exit"
fi

stage=integrity_after_ci
actual_head=$(git rev-parse --verify HEAD)
test "$actual_head" = "$expected_head"
status=$(git status --porcelain=v1 --untracked-files=all)
test -z "$status"
lock_after=$(sha256sum uv.lock)
test "$lock_after" = "$lock_before"
stage=complete
printf 'ci_command=%s head=%s lock=%s\n' "$ci_command_status" "$actual_head" "$lock_after" >&3
exit "$ci_exit"
BASH
```

対象オブジェクトが存在する場合は、不要なfetchをしません。
fetch・checkout・依存同期の失敗を、pytestの失敗やPRのテスト結果とは呼びません。
`ci_command=running` はCIコマンドを呼んだ状態であり、pytest開始の証拠ではありません。

`ms_data.tasks ci` は次の順で実行し、最初の非ゼロ終了で停止します。

1. `validate-report-contract`
2. `validate-generated-reports`
3. `validate-official-overrides-schema`
4. `verify-snapshot-restore`
5. `lint`
6. `test-cov`
7. `validate-strict`

失敗時は専用ログから確認できた完了箇所と、未実施・不明の箇所を報告します。
ログにない完了を推定せず、総合CIを別のコマンドで置き換えません。
同じHEADでもWikiの最新値取得とは別の検証です。

## 4. WikiのCONNECT拒否は通信設定として扱う

診断結果の `curl=56 / CONNECT=403 / origin HTTP=000` は、
サイトのHTTP応答を受ける前の拒否です。Wiki側の拒否と断定しません。
HTTP方式のプロキシを使うこの結果を、socksio未導入のせいとも断定しません。

保存環境の適用版、Internet access、Additional allowed domains、
組織で適用されるAgent Securityの設定を読取りで確認します。
必要な取得先は `w.atwiki.jp` のHTTPSポート443で、目的は
`https://w.atwiki.jp/battle-operation2/pages/2283.html` の最新データ確認です。

許可ドメインの追加などが必要なら、対象・理由・影響範囲を本人へ示し、
確認を得てから変更します。プロキシ解除、`NO_PROXY` 追加、`--noproxy`、
別のプロキシ・IP・外部環境への切替によって制限を回避しません。
許可設定と公開版が正しくても拒否される場合は、タスクID、時刻、
CONNECTの結果、秘密を除いた識別用ヘッダを本人経由でサポートへ渡します。

Wikiを取得できていない間は最新値確認を未完了とし、過去の22の記録や
ローカルCI成功を根拠に補正撤去の未解決レビューを解決扱いにしません。
socksioの追加は、固定依存関係で必要性が再現された場合に別変更として検討します。

## 5. 次回タスクへ修復を反映する

保存環境の修正は Settings > Codex Cloud > Environments > 対象環境の Edit で行います。
まず現在の公開版と編集差分を確認し、通常の環境変数に以下を設定します。

```text
UV_CACHE_DIR=/tmp/ms-data-uv-cache
UV_PYTHON=3.11
```

Install scriptでは既存のPython 3.11と合意したuv版を準備し、
`uv sync --locked --dev` が成功することを確認します。
Start skillには、実行先・対象HEAD・キャッシュへの書込み・Python/uv版の確認と、
失敗時にCIへ進まない指示を残します。
Install scriptの `export` だけを次のプロセスへ残る設定として扱わないでください。

Save前に公開版との差分と共有状況を確認します。認証・権限・通信許可・共有範囲の変更が
混ざっていれば本人確認まで停止し、通常の非セキュリティ設定だけと確認できてからSave、Republishします。
Saveで編集用環境へ即時適用される設定もあるため、確認をSave後へ遅らせません。
Republishは同じ環境を使う今後の新規タスクに影響します。
新しいタスクで公開版、uvの保存先、書込み、Python/uv版、固定依存の同期を再確認します。
既存タスクは自身の状態を保持し、リポジトリの自動更新だけではinstall/startは再実行されません。

既存環境の修正と新タスクでの確認を優先します。新規環境の作成は、
修正・再公開しても古い状態から起動する、または既知の書込み可能領域まで
利用できないなど、環境固有の状態不整合が残る場合に検討します。
認証や通信許可が原因なら、環境の再作成だけで解消すると仮定しません。

## 毎朝の停止条件と記録

- 実行先・並行タスク・公開版が不明なら、新しいタスクを重ねない。
- PRの期待SHAと実HEADが異なる、または作業ツリーに変更があれば、CIを開始しない。
- キャッシュ、Python/uv版、固定依存の同期で失敗したら、CIを未実施として止める。
- 同一の401、CONNECT 403、EROFSを繰り返さない。前回から変わった設定・コード・実行先が説明できるときだけ再確認する。
- 公開版を使った新しいタスクで総合CIまで通るまでは、毎朝の継続改善を再開しない。
- Wikiが必要な判断は最新値を取得できるまで保留する。Wikiに依存しないコード検証は独立して進めてよい。

記録する項目は、JST/UTC時刻、環境の公開版と適用版、タスク・turnのID、
実行場所、期待/実HEAD、clean確認、uv・Python版、cache実パス、
lockハッシュ、コマンドの終了コード、CIの完了/未実施箇所です。
タスクIDや保存環境IDは本人向けの記録に残し、公開PRへ載せる必要はありません。
トークン・プロキシURL・認証ファイル本文・環境変数一覧・未加工の通信ログは表示しません。

## 公式資料

- [現行の保存済みクラウド環境](https://learn.chatgpt.com/docs/environments/cloud-environments)
- [uvのキャッシュ保存先](https://docs.astral.sh/uv/concepts/cache/)
- [uvのlockと環境同期](https://docs.astral.sh/uv/concepts/projects/sync/)
- [GitHub CLIの環境変数と認証の優先順位](https://cli.github.com/manual/gh_help_environment)
- [PRをローカルに取得する手順](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/checking-out-pull-requests-locally)
