# 運用とトラブルシューティング

まず `task` を実行します。実行中のタスクと PR を確認し、空きがあれば承認済みのタスクを開始し、
未完了のタスクすべてと、あなたの対応が必要なタスクの数を表示します。

## 実行の様子を見る

- **herdr**: 各実行には、サイドバーに "task <id>: <title>" という名前のワークスペースがあります。開くと
  エージェントの出力をリアルタイムで確認できます。実行が終わっても、ペインは最終ステータス行を表示したまま
  開いています。`task done <id>`(または PR のマージ)で閉じます。
- **herdr なしの場合**: `task log <id>` で最後の 40 行を、`task log <id> --full` ですべてを表示します。
- エージェントに伝えた内容: `~/.local/share/task-hub/prompts/<id>.md`。

## 保存場所

| 内容 | 場所 |
|---|---|
| タスクファイル(ボード) | `~/.local/share/task-hub/board/tasks/`(非公開。すべての変更はボード独自のローカル git 履歴にコミットされます) |
| 設定 | `~/.config/task-hub/config.ini` |
| リポジトリのクローン | `~/.local/share/task-hub/repos/<owner>/<name>` |
| worktree | `~/.local/share/task-hub/worktrees/<id>` |
| プロンプト | `~/.local/share/task-hub/prompts/<id>.md` |
| ログ | `~/.local/state/task-hub/logs/<id>.log` |

## タスクが `blocked` になった

`task show <id>` で `reason` を確認できます。詳しくはレポートに書かれています。よくある理由:

| 理由 | 対処 |
|---|---|
| エージェント自身が書いた行(`## Blocked` から) | 求められたものを与えます。タスクファイルの Goal を編集するか、環境を修正します |
| `agent exited without a report (exit N)` | `task log <id>` を読みます。多くの場合、エージェントがクラッシュした、ログインしていない、または予算を使い切ったのが原因です |
| `agent wrote a report but changed no files` | エージェントはやることがないと判断しました。Goal を明確にします |
| `run stopped unexpectedly` | `task _run` プロセスが停止しました(たとえば herdr のペインを閉じた、Mac が再起動した) |
| `could not start: ...` | クローンまたは worktree の準備に失敗しました。`gh auth status` と `repo` の名前を確認します |
| `PR was closed without merging` | 再実行するか、`task done <id>` でタスクを閉じます |

その後 `task start <id>` を実行します。再実行は同じブランチと PR で作業を続け、エージェントには前回の実行が
止まった理由が伝えられます。

## `queue: N approved task(s) waiting, all 3 slots busy`

正常な状態です。実行中のタスクが終わった後、次の `task` 実行時に開始されます。

## `github_errors[...]`

`gh` がリポジトリの PR を読み取れませんでした(ログインしていない、アクセス権がない、リポジトリ名が変わった)。
該当するタスクの status はそのまま保たれます。`gh auth status` を実行してください。

## 実行中のタスクを止める

herdr のワークスペースでエージェントを停止します(Ctrl-C)。ランナーは最後まで処理を行い、変更された内容を
push してタスクをブロック状態にします。または、ペインを閉じます。その場合、次の `task` 実行時に
`run stopped unexpectedly` として記録されます。

## タスクを取り消す

`task done <id>` を実行します。そのタスクの herdr のワークスペースを閉じ、worktree を削除します。ブランチと PR は
GitHub に残ります。必要であれば、GitHub 上で PR をクローズしてください。

## 同時実行数の上限を変更する

`bin/task` の先頭にある `MAX_PARALLEL` を変更します。

## ディスクの整理

worktree はタスクが完了すると削除されます。`~/.local/share/task-hub/repos/` 内のクローンは次の実行を速くするために
残されており、いつでも削除できます。
