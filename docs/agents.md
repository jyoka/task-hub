# エージェント

task-hub は、プロンプトを受け取り、誰も入力しなくても作業できるエージェント CLI なら何でも実行できます。
タスクの worktree でエージェントを 1 つの引数(プロンプト)付きで起動し、終了するまで待ちます。プロンプトは
[worker/PROMPT.md](../worker/PROMPT.md) の指示の後にタスクを続けたものです。再実行で、前回の実行より後に人が Issue や PR に
書いたコメントがあれば、その最後に指示書の最後の部分とコメントが続きます([task-format.md](task-format.md#人のコメント))。

エージェントの仕事は、ファイルを編集し、テストを実行し、`.task-report.md` を書くことだけです。git と GitHub の
作業はすべて、その後で task-hub が行います。これにより、サンドボックスがネットワークを使えない、またはフォルダの外に
書き込めないエージェントも含め、すべてのエージェントが同じように振る舞います。

## 組み込みのエージェント

| 名前 | task-hub が実行するコマンド | 再開のコマンド(`[resume]`) | 補足 |
|---|---|---|---|
| `claude` | `env CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 BASH_DEFAULT_TIMEOUT_MS=1800000 BASH_MAX_TIMEOUT_MS=1800000 claude -p --dangerously-skip-permissions --output-format stream-json --verbose --session-id {session} {prompt}` | 同じコマンドの `--session-id` を `--resume` にしたもの | Claude Code の print モード、権限の確認なし。`claude -p` はバックグラウンドのコマンドの終わりを待たずに終わり、レポートのないまま Blocked になるため、環境変数でバックグラウンド実行を止め、代わりに前景のコマンドを 30 分まで待てるようにしています。`--output-format stream-json --verbose` は途中の手順をログに出すためです([operations.md](operations.md#実行の様子を見る)) |
| `codex` | `codex exec -s workspace-write --json {prompt}` | なし(新しいセッション) | Codex は workspace-write サンドボックスで動きます。worktree の編集とコマンドの実行ができ、デフォルトではネットワークは使えません。`--json` は途中の手順をログに出すためです |
| `pi` | `pi -p --mode json -e <task-hub>/pi/task-groups.ts --session-id {session} {prompt}` | 同じコマンド | Pi の print モード。`--mode json` は途中の手順をログに出すためです。`-e` は bash のコマンドを `worker/group-shell` に通す拡張で、`<task-hub>` は `task` を動かしている clone(ふつうは `~/.local/lib/task-hub`)です([落ちたエージェントのコマンドを止める](#落ちたエージェントのコマンドを止める))。`--session-id` はその ID の会話がなければ作り、あれば続けます(pi 1.4.0 で確認) |
| `kiro` | `kiro-cli chat --no-interactive --trust-all-tools --output-format stream-json {prompt}` | なし(新しいセッション) | Kiro CLI、すべてのツールを信頼。先にログインしてください(`kiro-cli whoami`)。`--output-format stream-json` は途中の手順をログに出すためです。このフラグのない古い kiro-cli では動かないので、`kiro-cli update` で新しくしてください(2.28.0 で確認) |

`{prompt}` はプロンプトを 1 つの引数として置き換えるため、シェルのクォートは関係しません。`{session}` も同じく
1 つの引数で、起動ごとに新しく作る UUID(会話の ID)に置き換わります。再開では、止まった起動と同じ ID が入ります
([止まった実行の再開](#止まった実行の再開resume))。

## エージェントの選び方

1. `task start --agent <name>` でこのタスク用に指定(タスクに保存されます)
2. それがなければ、タスクの登録時に指定した `task new --agent <name>`
3. それもなければ、`~/.config/task-hub/config.ini` の `[runner] agent`
4. それもなければ `claude`

## 自動レビュー

`~/.config/task-hub/config.ini` の `[runner] reviewer` にエージェント名を書くと、実装エージェントが終わったあと、
PR を作る前に reviewer が同じ worktree で差分を読みます。reviewer には Issue の Goal と、ベースから分かれた時点からの
PR 全体の差分(新しいファイルを含む)を渡します。実行に人のコメントを渡したときは、それも Goal の後に渡し、
受け入れ条件と同じように確かめさせます。reviewer の指示は
[worker/REVIEW.md](../worker/REVIEW.md) です。受け入れ条件を 1 つずつ照らし合わせ、指摘には場所と具体的な入力と結果を
付けるよう求めています。

| `[runner] reviewer` | reviewer |
|---|---|
| `agent` | そのタスクの実装エージェント(カードの Agent 欄に従う)を、実装を見ていない新しいコンテキストで起動します |
| エージェント名(例: `codex`) | そのエージェントに固定します。実装とは別のベンダーのモデルにすると、同じモデルに共通する思い込みを避けやすくなります |
| 空、または省略 | 自動レビューをしません |

reviewer は `.task-review.md` だけを書きます。テストは実行できます。テストが残した新しいファイルは自動で消し、
PR のファイルを書き換えた場合は元に戻して Blocked にします。判定は `pass` / `needs changes` / `blocked` です。
`needs changes` の場合、task-hub は 1 回だけ実装エージェントに自動で差し戻します。2 回目も通らなければ
ドラフト PR を作り、カードを Blocked にします。マージの判断は今までどおり人が行います。

## Blocked の仕分け(replanner)

`[runner] replanner` に `agent` かエージェント名を書くと、エージェント自身が `## Blocked` を書いて止まったとき、
replanner がその理由を仕分けて Issue にコメントします(指示は [worker/REPLAN.md](../worker/REPLAN.md))。
task-hub 自身が付けた Blocked(開始の失敗、レポートなし、自動レビューの不合格)は対象外です。

| 判定 | コメント | カード |
|---|---|---|
| `answered` | リポジトリにある答えと、根拠(`path:行番号` と、その行からの引用) | Blocked のまま。正しければ Ready に移すと、次の実行に「Replanner notes」として渡ります |
| `human` | あなたへの質問を 1 行に | Blocked のまま |
| `goal-conflict` | Goal の修正案 | Blocked のまま。適用はあなたが Goal を書き換えて行います |

でっち上げを防ぐため、次をコードで保証しています:

- `answered` の根拠は task-hub が 1 行ずつ確かめます。ファイルがない、git が追跡していない(replanner が自分で書いた
  ファイルなど)、行がない、引用がその行にない、引用が 3 文字に満たない、のどれかなら、答えを捨てて `human` として
  質問だけを載せます
- Goal の本文は書き換えません。答えは `<!-- task-hub replan -->` 付きのコメントに残します
- `answered` は 1 タスク 2 回まで。前回の仕分けと同じ理由でまた Blocked になったら、仕分けをせずにあなたに回します
- replanner がファイルを書き換えたら、元に戻して結果を捨てます
- カードを Ready に戻すのは常にあなたです。タスクの作成や分割もしません

## 使用量の記録

task-hub は、エージェントを起動するたびに秒数を `metrics.jsonl` に残します。エージェントの CLI が手元に残す記録を
読めるときは、その記録にある使用量も残します(エージェントに申告させるのではなく、task-hub が外から読みます)。
どの記録をどの起動でも試し、エージェントの名前では分けません。

| エージェント | 読む記録 | 残るもの |
|---|---|---|
| `claude` | `~/.claude/projects/**/*.jsonl`(`CLAUDE_CONFIG_DIR` があればその下の `projects`) | 秒数、トークン数、呼び出し数、サブエージェント、モデル |
| `kiro` | v1: `~/Library/Application Support/kiro-cli/data.sqlite3`(macOS。ほかは `~/.local/share/kiro-cli/`)の `conversations_v2`<br>v2: `~/.kiro/sessions/cli/<id>.json` | 秒数、クレジット(小数 2 桁)、リクエスト数、モデル。トークン数は kiro-cli が残さないので欄がありません |
| `codex`、`pi`、追加したもの | まだ読みません | 秒数だけ |

どちらも、その worktree の中で、その起動の間に書かれた記録だけを数えます。kiro-cli は版によって保存先が違い
(2.2.0 の `--no-interactive` は v1 に書きました。新しい版は v2 に書くとされますが、確かめていません)、両方を読みます。
v1 のデータベースは読み取り専用で開き、ロックされている、形式が違う、などで読めなければ秒数だけを残します。
`[agents]` でコマンドを変えても、CLI が記録を残す限り同じように測れます。集計は `task stats` で見られます
([operations.md](operations.md#エージェントの使用量))。上限や停止はまだしません。

## エージェントの変更と追加

`~/.config/task-hub/config.ini` の `[agents]` にコマンドを書きます。同じ名前の組み込みコマンドを上書きするか、
新しいエージェントを追加します:

```ini
[agents]
; stricter Claude: allow only edits and test commands
claude = env CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 BASH_DEFAULT_TIMEOUT_MS=1800000 BASH_MAX_TIMEOUT_MS=1800000 claude -p --output-format stream-json --verbose --allowedTools 'Edit,Write,Bash(npm test:*)' {prompt}
; a new agent
aider = aider --yes-always --message {prompt}
```

`{prompt}` 以外の、自分で書く引数に空白が含まれるときは、`'Edit,Write,Bash(npm test:*)'` のように引用符で囲んでください。コマンドは `shlex` の規則で引数に分けます。

`claude` を上書きするときも、組み込みと同じ `env ...` の 3 つの環境変数を付けてください。付けないと、長いテストが Bash ツールの時間の上限(既定 2 分、最大 10 分)を超えたときにバックグラウンドへ回され、`claude -p` はその終わりを待たずにレポートなしで終わります。

途中の手順もログに出したいときは、組み込みと同じ出力のフラグを付けてください。task-hub は、コマンド(プロンプトを除く)にそのフラグがあるエージェントの出力を、手順ごとの短い 1 行に直してログに書きます。付けなければ、出力をそのまま書きます(`claude -p` と `pi -p` なら最後の結果の文だけ)。

| CLI | 付けるフラグ | コマンドの条件 |
|---|---|---|
| Claude Code | `--output-format stream-json --verbose` | `--output-format stream-json` がある(下の kiro-cli でないもの) |
| Codex | `--json` | `codex` と `exec` と `--json` がある |
| Pi | `--mode json` | `pi` と `--mode json` がある |
| Kiro CLI | `--output-format stream-json` | `kiro-cli` と `--output-format stream-json` がある |

`codex` などの CLI は、パス付き(`/opt/homebrew/bin/pi`)でも、`env A=1 ...` の後ろでもかまいません。

コマンドが動くための条件:

- 質問せずに最後まで実行されること(stdin は閉じられています)
- カレントディレクトリ、つまりタスクの worktree で動作すること
- 実装エージェントは `.task-report.md` を書けること。task-hub が結果を知る方法はこれだけです。
  レポートがなければ、タスクはブロックとして扱われます
- reviewer として使う場合は `.task-review.md` を書けること。reviewer はそれ以外のファイルを変更してはいけません

### 止まった実行の再開(`[resume]`)

予期せず止まった実行(クラッシュ、kill、再起動、ペインを閉じた)は、task-hub が 1 回だけ再開します
([operations.md の「実行中のタスクを止める」](operations.md#実行中のタスクを止める))。再開のエージェントには、
元のプロンプトに「# Resumed」の節(`worker/PROMPT.md` の最後の部分)を足して渡します。コマンドは次の順に選びます。

1. `[resume]` に同じ名前があればそれ。値が空なら再開のコマンドはなし(3 になる)
2. `[agents]` のコマンドが組み込みのままの `pi` と `claude` は、組み込みの再開のコマンド([上の表](#組み込みのエージェント))。
   `[agents]` で自分のコマンドに変えたら、`[resume]` に書かない限り使いません(別のプログラムやモデルで続けないため)
3. それもなければ `[agents]` のコマンド(新しいセッション。worktree の途中の仕事から続けます)

エージェントの会話を続けるには、`[agents]` と `[resume]` の両方に `{session}` を書きます。task-hub は実装エージェントの
起動(`agent` と、レビューの差し戻しの `retry`)ごとに新しい UUID を作り、`runs/<id>.json` の `session` に残してから
起動します。再開では、止まった起動と同じ値を `[resume]` のコマンドに渡します。reviewer と replanner は毎回新しい値です。
`{session}` を書かないコマンドは、会話の ID を受け取らず、再開は新しいセッションになります。

```ini
[agents]
pi = /Users/me/.pi/agent/bin/pi -p --mode json --model openai-codex/gpt-6-luna -e /Users/me/.local/lib/task-hub/pi/task-groups.ts --session-id {session} {prompt}

[resume]
; the command that goes on with the agent's own saved conversation, under the same {session}
pi = /Users/me/.pi/agent/bin/pi -p --mode json --model openai-codex/gpt-6-luna -e /Users/me/.local/lib/task-hub/pi/task-groups.ts --session-id {session} {prompt}
myagent = myagent --continue {prompt}
```

`[resume]` のコマンドが手順を 1 つも出さず、レポートも書かずに 0 以外で終わったら(続ける会話が見つからなかった、など)、
同じ再開の中で 1 回だけ `[agents]` のコマンドで起動し直します。そのときの `{session}` は新しい値です
(`claude --session-id` は使われている ID を断り、`claude --resume` はない ID で 1 で終わります。2.1.310 で確認)。

pi も claude も、会話をそれぞれの置き場所(pi は `~/.pi/agent/sessions/`、claude は `~/.claude/projects/`)に実行ごとに
残します。task-hub はそれを消しません。

### 落ちたエージェントのコマンドを止める

pi と claude は、ツールのコマンド(長いテストなど)をエージェントとは別のプロセスグループで動かします。エージェントが
落ちてもそのコマンドは最後まで動くので、再開したエージェントの横で同じ worktree に書き続けることがあります。
task-hub はこれを防ぐため、コマンドを `worker/group-shell` に通してそのプロセスグループを記録し、エージェントを起動する前に、
前のエージェントが残したものを止めます。止めたときはログに `== stopped process group <番号>: ...` と出ます。

| エージェント | 通し方 | 自分のコマンドに変えたとき |
|---|---|---|
| `pi` | 拡張 `pi/task-groups.ts` が `bash` のツールを置き換え、シェルを `group-shell` にする(`-e` は `--no-extensions` でも読む)。ほかの拡張が `bash` を置き換えていれば、そちらを使い、記録しない | `[agents]` と `[resume]` に `-e <task-hub>/pi/task-groups.ts` を足す |
| `claude` | task-hub がエージェントに環境変数 `CLAUDE_CODE_SHELL_PREFIX` を渡す | そのままで使える。自分で `CLAUDE_CODE_SHELL_PREFIX` を決めていれば(環境変数でも `~/.claude/settings.json` の `env` でも)、そちらを使い、記録しない |
| `codex`、`kiro` | 差し込み口がなく、記録しない | - |

- 利用者の `~/.pi` と `~/.claude` の設定ファイルは書き換えません。pi の拡張は pi の設定(`shellPath`、`shellCommandPrefix`)を
  読んで使うだけです。`shellPath` の `~/` と `file://` の URL は、pi と同じくパスに直します
- 止めるのは、記録したグループの先頭が記録と同じ開始時刻で生きているときだけです。番号が別のプロセスに渡っていれば止めません
- 止めるのは、次のエージェントを起動するときと、片付け(`cleanup`)のときです
- Windows と `[sandbox] mode = user` では記録しません(今までどおり)。`[sandbox] mode = user` では、組み込みの pi のコマンドから `-e` を外します
- 調べた根拠と、差し込み口のないエージェントで止められない理由は
  [durable-runs-comparison.md の「A でツールのコマンドを止める」](durable-runs-comparison.md#a-でツールのコマンドを止めるタスク-238)にあります

実験として、Pi Durable で作った実行役(`durable/`)も `[agents] durable` と `[resume] durable` に同じコマンドを書いて使えます。会話を worktree の `.task-durable/` に残し、止まったところから続けます。入れ方、実験版であること、認証は [durable/README.md](../durable/README.md) にあります。

## 始める前の確認と、実行に渡す環境変数

無人で動かすとき(launchd の `task watch` など)は、エージェントのログインが切れていても誰も気づきません。
`[check]` にエージェントごとの確認コマンドを書くと、task-hub はタスクを始める前(worktree を作る前、
エージェントを起動してクレジットを使う前)にそれを実行します。終了コードが 0 以外なら、そのコマンドと出力の最後の
数行を理由にしてカードを Blocked にします(「could not start: agent "kiro" is not ready: ...」)。実装エージェントに
加えて、`[runner] reviewer` と `replanner` のエージェントも同じときに確かめます。

```ini
[runner]
agent = kiro
pass_env = KIRO_API_KEY         ; herdr のペインで動く実行にも渡す変数の名前(カンマか空白区切り)

[check]
kiro = kiro-cli whoami          ; 例。書いたエージェントだけ確認します(組み込みの既定はありません)
```

- `[check]` に書いていないエージェントは確認しません(組み込みの確認はありません)。Kiro の公式ドキュメントは、
  どの認証方法が有効かを `kiro-cli whoami` で確かめると書いています。ただし `KIRO_API_KEY` だけ(ブラウザでのログインなし)
  のときに終了コード 0 になるかは確かめていません。**API キーだけで使う場合は、先に手で
  `kiro-cli whoami; echo $?` が 0 になるか確かめてから**この設定を入れてください
- 確認は `task watch` / `task start` を動かしている環境で、シェルを通さずに実行します(60 秒で打ち切り)
- `pass_env` は、herdr のペインで動く実行のためのものです。ペインのシェルは herdr サーバーの環境で始まるので、
  task-hub は小さな起動スクリプト(`~/.local/share/task-hub/run/<番号>.sh`、本人だけが読める 0600)で
  `HOME`、`PATH`、`TASK_*`、`GIT_AUTHOR_*`、`GIT_COMMITTER_*` と、ここに書いた変数を渡します。起動スクリプトは
  始まった直後に自分自身を消すので、キーの値はファイルに残りません。herdr を使わない
  バックグラウンドの実行は、もともと環境をすべて引き継ぎます
- `pass_env` に書いた変数の値は、確認の出力に現れても `***` に置き換えてからコメントと出来事に書きます。
  ログやコメントに値を出さないでください(エージェント自身の出力は task-hub には消せません)

## 安全性

Codex を除き、組み込みコマンドは**承認の確認なしで**実行されます。エージェントはあなたの権限で、worktree の中でも外でも
どんなコマンドでも実行できます。設定の `[env]` に書いたファイル(`.env` など)も読めます。それを制限しているのは次の点です:

- 別の worktree(`~/.local/share/task-hub/worktrees/<id>`)で作業し、あなた自身のチェックアウトには触れません
- タスクを承認できるのはあなただけで(`task start`)、同時に実行されるのは最大 5 つです
- エージェントは push しません。task-hub が push するのはそのタスク自身のブランチだけで、変更がデフォルトブランチに
  入るのは、あなたが PR をマージしたときだけです

マシンによって(たとえば仕事用 Mac で)これでは信頼しすぎだと感じる場合は、config でコマンドを厳しくしてください。
Claude ならツールの許可リスト、Kiro なら `--trust-tools=...`、Codex ならより厳しいサンドボックスを使います。
Linux では、`[sandbox] mode = user` でエージェントを専用の Linux ユーザーで動かし、あなたの HOME に届かないようにできます([sandbox.md](sandbox.md))。
タスクごとにしてはいけないことは、Goal の `Rules` に書きます([task-format.md](task-format.md#rules-タスクごとの決まり))。
