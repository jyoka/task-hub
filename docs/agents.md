# エージェント

task-hub は、プロンプトを受け取り、誰も入力しなくても作業できるエージェント CLI なら何でも実行できます。
タスクの worktree でエージェントを 1 つの引数(プロンプト)付きで起動し、終了するまで待ちます。プロンプトは
[worker/PROMPT.md](../worker/PROMPT.md) の指示の後にタスクを続けたものです。

エージェントの仕事は、ファイルを編集し、テストを実行し、`.task-report.md` を書くことだけです。git と GitHub の
作業はすべて、その後で task-hub が行います。これにより、サンドボックスがネットワークを使えない、またはフォルダの外に
書き込めないエージェントも含め、すべてのエージェントが同じように振る舞います。

## 組み込みのエージェント

| 名前 | task-hub が実行するコマンド | 補足 |
|---|---|---|
| `claude` | `claude -p --dangerously-skip-permissions {prompt}` | Claude Code の print モード、権限の確認なし |
| `codex` | `codex exec -s workspace-write {prompt}` | Codex は workspace-write サンドボックスで動きます。worktree の編集とコマンドの実行ができ、デフォルトではネットワークは使えません |
| `pi` | `pi -p {prompt}` | Pi の print モード |
| `kiro` | `kiro-cli chat --no-interactive --trust-all-tools {prompt}` | Kiro CLI、すべてのツールを信頼。先にログインしてください(`kiro-cli whoami`) |

`{prompt}` はプロンプトを 1 つの引数として置き換えるため、シェルのクォートは関係しません。

## エージェントの選び方

1. `task start --agent <name>` でこのタスク用に指定(タスクに保存されます)
2. それがなければ、タスクの登録時に指定した `task new --agent <name>`
3. それもなければ、`~/.config/task-hub/config.ini` の `[runner] agent`
4. それもなければ `claude`

## 自動レビュー

`~/.config/task-hub/config.ini` の `[runner] reviewer` にエージェント名を書くと、実装エージェントが終わったあと、
PR を作る前に reviewer が同じ worktree で差分を読みます。reviewer には Issue の Goal と、ベースから分かれた時点からの
PR 全体の差分(新しいファイルを含む)を渡します。reviewer の指示は
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

- `answered` の根拠は task-hub が 1 行ずつ確かめます。ファイルがない、行がない、引用がその行にない、のどれかなら
  答えを捨てて `human` として質問だけを載せます
- Goal の本文は書き換えません。答えは `<!-- task-hub replan -->` 付きのコメントに残します
- `answered` は 1 タスク 2 回まで。前回の仕分けと同じ理由でまた Blocked になったら、仕分けをせずにあなたに回します
- replanner がファイルを書き換えたら、元に戻して結果を捨てます
- カードを Ready に戻すのは常にあなたです。タスクの作成や分割もしません

## エージェントの変更と追加

`~/.config/task-hub/config.ini` の `[agents]` にコマンドを書きます。同じ名前の組み込みコマンドを上書きするか、
新しいエージェントを追加します:

```ini
[agents]
; stricter Claude: allow only edits and test commands
claude = claude -p --allowedTools Edit,Write,Bash(npm test:*) {prompt}
; a new agent
aider = aider --yes-always --message {prompt}
```

コマンドが動くための条件:

- 質問せずに最後まで実行されること(stdin は閉じられています)
- カレントディレクトリ、つまりタスクの worktree で動作すること
- 実装エージェントは `.task-report.md` を書けること。task-hub が結果を知る方法はこれだけです。
  レポートがなければ、タスクはブロックとして扱われます
- reviewer として使う場合は `.task-review.md` を書けること。reviewer はそれ以外のファイルを変更してはいけません

## 安全性

Codex を除き、組み込みコマンドは**承認の確認なしで**実行されます。エージェントはあなたの権限で、worktree の中でも外でも
どんなコマンドでも実行できます。それを制限しているのは次の点です:

- 別の worktree(`~/.local/share/task-hub/worktrees/<id>`)で作業し、あなた自身のチェックアウトには触れません
- タスクを承認できるのはあなただけで(`task start`)、同時に実行されるのは最大 3 つです
- エージェントは push しません。task-hub が push するのはそのタスク自身のブランチだけで、変更がデフォルトブランチに
  入るのは、あなたが PR をマージしたときだけです

マシンによって(たとえば仕事用 Mac で)これでは信頼しすぎだと感じる場合は、config でコマンドを厳しくしてください。
Claude ならツールの許可リスト、Kiro なら `--trust-tools=...`、Codex ならより厳しいサンドボックスを使います。
