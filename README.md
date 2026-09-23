# task-hub

GitHub Project をかんばんボードとして使い、そのタスクをコーディングエージェントに実行させるツールです。
エージェントは何でも使えます: Claude Code、Codex、Pi、Kiro、そのほか非対話モードを持つものなら何でも構いません。

ボードは GitHub Project そのものなので、ブラウザでもスマホアプリでも見られ、`gh` を使えるエージェントなら
どれでも読み書きできます。タスクは非公開リポジトリの Issue です。カードを **Ready** に移すと、あなたの Mac で
エージェントが動き始めます。同時に実行されるのは最大 3 つで、それぞれ専用の herdr ワークスペースと専用のブランチで
動きます。エージェントが終わると、task-hub がブランチを push して PR を作り、エージェントのレポートと、
あなたがレビューすべき点をまとめた一覧を Issue にコメントし、カードを **In review** に移します。

```
you:    /task in a chat      ->  Issue jyoka/tasks#12, card in Backlog
you:    drag card to Ready   ->  `task watch` starts it on your Mac         In progress
        (herdr sidebar shows a new workspace "task 12: Fix login" with the agent working)
agent:  edits files, runs tests, writes its report
task:   commits, pushes task/12, opens the PR, comments the report         In review
you:    review + merge the PR -> the Issue closes                           Done
```

## 日々の使い方

| やりたいこと | 方法 |
|---|---|
| ボード全体を見る | GitHub Project(ブラウザ、スマホアプリ) |
| Ready のカードを自動で始める | herdr のペインで `task watch` を動かしておく |
| 自分の対応が必要なものを見る | `task`(Ready のカードの開始も行います) |
| 今のチャットをタスクにする | エージェント内で `/task`(必要なら `/task repo is jyoka/app, use codex`) |
| ターミナルからタスクを作る | `task new --title "..." --repo owner/name --goal "..." [--agent codex]` |
| タスクを承認してエージェントに作業させる | カードを Ready に移す、または `task start`(一覧から選択)/ `task start 12` |
| このタスクだけ別のエージェントを使う | カードの Agent 欄を書き換える、または `task start --agent kiro` |
| 実行を見守る | herdr サイドバーのそのワークスペース、または `task log 12` |
| レポートとレビューすべき点を読む | Issue の最新コメント、PR、または `task show 12` |
| 完了した作業を受け入れる | PR をマージします。Issue が閉じてカードは Done になります |
| ブロックされたタスクを再実行する | Issue に答えを書き足してカードを Ready に戻す(同じブランチと PR で続行します) |
| タスクをクローズまたはキャンセルする | Issue を閉じる、または `task done 12` |

普通のチャットがタスクになることはありません。タスクを作るのは `/task` か `task new` だけで、
エージェントに作業させるのはカードを Ready に移したとき(または `task start`)だけです。

## ボードの列

| 列 (Status) | 意味 | 対応が必要? |
|---|---|---|
| Backlog | 登録済み、未承認 | はい: やってほしいときに Ready へ |
| Ready | 承認済み。空きがあればすぐ、3 つ実行中なら空きが出たら開始 | いいえ |
| In progress | エージェントが作業中 | いいえ |
| In review | PR がオープンされ準備完了 | はい: レビューしてからマージ |
| Blocked | エージェントが何かを必要としている(理由は Issue のコメント)、または実行が失敗した | はい: 対処してから Ready へ |
| Done | PR がマージされた、または Issue が閉じられた | いいえ |

## 構成

```
bin/task              the CLI (Python 3 standard library; uses git, gh, and herdr if running)
worker/PROMPT.md      the instructions every agent gets at the start of a run
skills/task/SKILL.md  the /task skill (linked into Claude, Codex/Pi, and Kiro skill folders)
tests/test_task.py    tests: python3 -m unittest -v
docs/                 setup, agents, design, task format, operations, lessons
```

あなたのタスクはこのリポジトリには含まれません。タスクは非公開の Issue リポジトリ(例: `jyoka/tasks`)と
GitHub Project にあり、実行中の情報(ログ、worktree など)は手元のマシンにだけ残ります。

## ドキュメント

- [docs/setup.md](docs/setup.md): セットアップ(GitHub Project の準備、仕事用 Mac も含む)
- [docs/agents.md](docs/agents.md): 各エージェントの実行方法、安全性、エージェントの追加
- [docs/task-format.md](docs/task-format.md): Issue、レポートファイル、コメント、PR の形式
- [docs/operations.md](docs/operations.md): 実行の見守り、トラブルシューティング、後片付け
- [docs/design.md](docs/design.md): なぜこの作りなのか、ほかに検討したもの
- [docs/lessons.md](docs/lessons.md): 作ってテストしてわかったこと、まだ実証されていないこと
