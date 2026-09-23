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
- そこに `.task-report.md` を書けること。task-hub が結果を知る方法はこれだけです。
  レポートがなければ、タスクはブロックとして扱われます

## 安全性

Codex を除き、組み込みコマンドは**承認の確認なしで**実行されます。エージェントはあなたの権限で、worktree の中でも外でも
どんなコマンドでも実行できます。それを制限しているのは次の点です:

- 別の worktree(`~/.local/share/task-hub/worktrees/<id>`)で作業し、あなた自身のチェックアウトには触れません
- タスクを承認できるのはあなただけで(`task start`)、同時に実行されるのは最大 3 つです
- エージェントは push しません。task-hub が push するのはそのタスク自身のブランチだけで、変更がデフォルトブランチに
  入るのは、あなたが PR をマージしたときだけです

マシンによって(たとえば仕事用 Mac で)これでは信頼しすぎだと感じる場合は、config でコマンドを厳しくしてください。
Claude ならツールの許可リスト、Kiro なら `--trust-tools=...`、Codex ならより厳しいサンドボックスを使います。
