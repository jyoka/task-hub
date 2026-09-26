# task-hub

GitHub Project をかんばんボードとして使い、そのタスクをコーディングエージェントに実行させるツールです。
エージェントは何でも使えます: Claude Code、Codex、Pi、Kiro、そのほか非対話モードを持つものなら何でも構いません。

ボードは GitHub Project そのものなので、ブラウザでもスマホアプリでも見られ、`gh` を使えるエージェントなら
どれでも読み書きできます。タスクは非公開リポジトリの Issue です。カードを **Ready** に移すと、あなたの Mac で
エージェントが動き始めます。同時に実行されるのは最大 3 つで、それぞれ herdr のタブ(`/task` を頼んだ workspace の中)と専用のブランチで
動きます。エージェントが終わると、task-hub がブランチを push して PR を作り、エージェントのレポートと、
あなたがレビューすべき点をまとめた一覧を Issue にコメントし、カードを **In review** に移します。

```
you:    /task in a chat      ->  Issue jyoka/tasks#12, card in Backlog
you:    drag card to Ready   ->  `task watch` starts it on your Mac         In progress
        (a tab "#12 Fix login" opens in the herdr workspace where you asked, with the agent working)
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
| 窓口のエージェントと話すだけで済ませる | 作業中の herdr の workspace のペインで `/desk`(状況を伝え、起きたことを知らせ、話した作業をタスクにして提案する) |
| ボードを読むだけ(何も始めない) | `task list`。最近の出来事は `task events` |
| 今のチャットをタスクにする | エージェント内で `/task`(必要なら `/task repo is jyoka/app, use codex`) |
| ターミナルからタスクを作る | `task new --title "..." --repo owner/name --goal "..." [--base feat/x] [--agent codex]` |
| main ではなく作業中のブランチから始める | カードの Base branch 欄にブランチ名を書く(push 済みのもの)。PR もそのブランチに向けて出ます |
| タスクを承認してエージェントに作業させる | カードを Ready に移す、または `task start`(一覧から選択)/ `task start 12` |
| このタスクだけ別のエージェントを使う | カードの Agent 欄を書き換える、または `task start --agent kiro` |
| PR 前に自動レビューさせる | 設定の `[runner] reviewer` に `agent`(タスクと同じエージェント)かエージェント名を書く |
| 自動レビューや Blocked の傾向を見る | `task stats`(このマシンで終わった実行の集計) |
| 実行を見守る | herdr のそのタスクのタブ(`/task` を頼んだ workspace の中)、または `task log 12` |
| レポートとレビューすべき点を読む | Issue の最新コメント、PR、または `task show 12` |
| 完了した作業を受け入れる | PR をマージします。Issue が閉じてカードは Done になります |
| Blocked の理由を自動で仕分けさせる | 設定の `[runner] replanner` に `agent` かエージェント名を書く(コメントだけで、Ready に戻すのはあなた) |
| ブロックされたタスクを再実行する | Issue に答えを書き足してカードを Ready に戻す(同じブランチと PR で続行します) |
| タスクをクローズまたはキャンセルする | Issue を閉じる、または `task done 12` |

普通のチャットがタスクになることはありません。タスクを作るのは `/task` か `task new` だけで、
エージェントに作業させるのはカードを Ready に移したとき(または `task start`)だけです。

## 使い方のパターン

**コードを直してもらう(エンジニア向け)。** 上の流れそのままです。Goal に何を直すかを書き、エージェントの変更を
PR でレビューしてマージします。

**AI と壁打ちして案を出してもらう(企画職など、コードを直接書かない人向け)。** 既存のリポジトリのコードを
エージェントに読ませて、改善案、試作の方針、要件の整理などを考えてもらう使い方です。Goal に結果の置き場所を書きます。

```
task new --title "検索画面の改善案" --repo owner/app \
  --goal "検索まわりのコードを読み、改善案を 3 つ考えて docs/proposals/search-ideas.md に書く"
```

提案書のファイルが PR になり、In review で読めます。置き場所を書かずに、ファイルを何も変えないで報告だけを書いた
実行は、今は Blocked になります(報告は Issue のコメントで読めます)。PR は作業先のリポジトリに出ます。提案書を
そのリポジトリに残したくない場合は、読み終えたら PR をマージせずに閉じ、`task done <番号>` で片付けます。

**コード以外の雑務。** Project の画面の「+ Add item」でタイトルだけのカード(下書き)を作ります。task-hub は
Issue ではないカードを無視するので、エージェントが動くことはありません。好きな列で管理し、終わったら Done に移します。

## ボードの列

| 列 (Status) | 意味 | 対応が必要? |
|---|---|---|
| Backlog | 登録済み、未承認 | はい: やってほしいときに Ready へ |
| Ready | 承認済み。空きがあればすぐ、3 つ実行中なら空きが出たら開始 | いいえ |
| In progress | エージェントが作業中 | いいえ |
| In review | PR がオープンされ準備完了 | はい: レビューしてからマージ |
| wait for merge(任意) | レビュー済みで、マージ待ちの PR。列が無いボードでは使いません | いいえ: マージされれば Done に移ります |
| Blocked | エージェントが何かを必要としている(理由は Issue のコメント)、または実行が失敗した | はい: 対処してから Ready へ |
| Done | PR がマージされた、または Issue が閉じられた | いいえ |

## 構成

```
bin/task              the CLI (Python 3 standard library; uses git, gh, and herdr if running)
worker/PROMPT.md      the instructions every agent gets at the start of a run
skills/task/SKILL.md  the /task skill (linked into Claude, Codex/Pi, and Kiro skill folders)
tests/test_task.py    tests: python3 -m unittest discover -s tests -v
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
