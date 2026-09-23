# task-hub

コーディングエージェントを代わりに実行してくれる、ファイルベースのタスクボードです。どのエージェントでも使えます:
Claude Code、Codex、Pi、Kiro、そのほか非対話モードを持つものなら何でも構いません。

タスクは、あなたが登録したいときに登録します。`task start` で承認します。同時に実行されるのは最大 3 つで、
それぞれ専用の herdr ワークスペースと専用のブランチで動きます。エージェントが終わると、
task-hub がブランチを push し、エージェントのレポートと、あなたがレビューすべき点を正確にまとめた一覧を載せた PR を作成します。

```
you:    /task in a chat          ->  tasks/0012-fix-login.md           draft
you:    task start               ->  pick the task, an agent starts    in_progress
        (herdr sidebar shows a new workspace "task 12: Fix login" with the agent working)
agent:  edits files, runs tests, writes its report
task:   commits, pushes task/12, opens the PR                          review
you:    review + merge the PR    ->  next `task` marks it              done
```

クラウドでは何も動かず、特定のベンダーにも依存しません。ボードは手元のマシン上のただの markdown で、
エージェントも手元のマシンで動き、GitHub が見るのはブランチと PR だけです。

## 日々の使い方

| やりたいこと | 実行するもの |
|---|---|
| 自分の対応が必要なものを見る(待機中のタスクの開始も行います) | `task` |
| 今のチャットをタスクにする | エージェント内で `/task`(必要なら `/task repo is jyoka/app, use codex`) |
| ターミナルからタスクを作る | `task new --title "..." --repo owner/name --goal "..." [--agent codex]` |
| タスクを承認してエージェントに作業させる | `task start`(一覧から選択)または `task start 12` |
| このタスクだけ別のエージェントを使う | `task start --agent kiro` |
| 実行を見守る | herdr サイドバーのそのワークスペース、または `task log 12` |
| レポートとレビューすべき点を読む | `task show 12` |
| 完了した作業を受け入れる | PR をマージします。次の `task` で done になります |
| ブロックされたタスクを再実行する | `task start`(同じブランチと PR で続行します) |
| タスクをクローズまたはキャンセルする | `task done 12` |

普通のチャットがタスクになることはありません。タスクを作るのは `/task` か `task new` だけで、
エージェントに作業させるのは `task start` だけです。

## ステータスのライフサイクル

| ステータス | 意味 | 対応が必要? |
|---|---|---|
| `draft` | 登録済み、未承認 | はい: やってほしいときに `task start` |
| `ready` | 承認済み、すでに 3 つ実行中のため待機中 | いいえ: 後の `task` で開始します |
| `in_progress` | エージェントが作業中 | いいえ |
| `review` | PR がオープンされ準備完了 | はい: レビューしてからマージ |
| `blocked` | エージェントが何かを必要としている(理由を表示)、または実行が失敗した | はい: 対処してから `task start` |
| `done` | PR がマージされた、または手動でクローズされた | いいえ |

## 構成

```
bin/task              the CLI (Python 3 standard library; uses git, gh, and herdr if running)
worker/PROMPT.md      the instructions every agent gets at the start of a run
skills/task/SKILL.md  the /task skill (linked into Claude, Codex/Pi, and Kiro skill folders)
tests/test_task.py    tests: python3 -m unittest -v
docs/                 setup, agents, design, task format, operations, lessons
```

あなたのタスクはこのリポジトリには含まれません。タスクは `~/.local/share/task-hub/board/tasks/` にあります。これは
独自のローカル git 履歴を持つ非公開フォルダで、push されることはないため、このリポジトリは安全に共有できます。

## ドキュメント

- [docs/setup.md](docs/setup.md): Mac へのインストール(Kiro しかない仕事用 Mac も含む)
- [docs/agents.md](docs/agents.md): 各エージェントの実行方法、安全性、エージェントの追加
- [docs/task-format.md](docs/task-format.md): タスクファイル、エージェントのレポートファイル、PR
- [docs/operations.md](docs/operations.md): 実行の見守り、トラブルシューティング、後片付け
- [docs/design.md](docs/design.md): なぜこの作りなのか、ほかに検討したもの
- [docs/lessons.md](docs/lessons.md): 作ってテストしてわかったこと、まだ実証されていないこと
