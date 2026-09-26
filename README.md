# task-hub

GitHub Project をかんばんボードとして使い、そのタスクをコーディングエージェントに実行させるツールです。
エージェントは何でも使えます: Claude Code、Codex、Pi、Kiro、そのほか非対話モードを持つものなら何でも構いません。

あなたが決めるのは「始めてよい」(カードを Ready に移す)と「入れてよい」(PR をマージする)の 2 つだけです。
その間の実装、レビュー、PR の作成、止まったときの仕分けは、task-hub とエージェントが進めます。

## 全体像

```
あなた ──話す──▶ /chief(総指揮のエージェント、任意)
  │                  │ 提案 → あなたの「うん」で登録・開始、起きたことを自分から知らせる
  │ /task, task new  ▼
  ├──────────▶ GitHub Project(ボード)と Issue(タスクの Goal)   ← 共有の状態
  │ Ready に移す      │
  │                  ▼
  │            task-hub(bin/task、コードで流れを決める)
  │              ├─ 実装エージェント   worktree で編集し、テストし、レポートを書く
  │              ├─ reviewer(任意)     別のコンテキストで Goal と PR 全体を照らし合わせる
  │              ├─ replanner(任意)    エージェントが Blocked で止まった理由を仕分ける
  │              └─ git / PR / カードの移動 / 記録(events.jsonl、metrics.jsonl)
  │                  │
  └◀── PR をマージ ──┘ In review
```

- **流れを決めるのはコードです。** 同時実行数(最大 3)、ブランチ、PR、差し戻しの回数、でっち上げの検出は
  `bin/task` が保証します。LLM は、実装、レビュー、仕分け、会話の役を担います。
- **エージェントがタスクを勝手に作ったり始めたりすることはありません。** 登録は `/task`・`task new`・`/chief`
  (あなたの「うん」のあと)だけ、開始は Ready に移したとき(または `task start`)だけです。
- **ボードは GitHub Project そのものです。** ブラウザでもスマホアプリでも見られます。タスクは非公開リポジトリの
  Issue で、実行中の情報(ログ、worktree など)は手元のマシンにだけ残ります。

## 1 つのタスクの流れ

```
you:      /task in a chat (or ask /chief)  ->  Issue jyoka/tasks#12, card in Backlog
you:      move the card to Ready           ->  `task watch` starts it on your Mac          In progress
          a tab "#12 Fix login" opens in the herdr workspace where you asked
agent:    edits files, runs tests, writes its report
reviewer: checks the Goal's acceptance criteria against the whole PR diff
          pass          -> PR is opened
          needs changes -> sent back to the agent once, then reviewed again
task:     pushes task/12, opens the PR, comments the report and the review          In review
          the tab closes itself (the output stays in `task log 12`)
you:      review + merge the PR -> the Issue closes                                 Done
```

止まった場合:

```
agent:     writes "## Blocked: need the Stripe test key"                             Blocked
replanner: answered (from the repo, with file:line evidence) / human (a sharper question) / goal-conflict
you:       answer in the Goal (or check the replanner's answer), move the card to Ready again
           -> the same branch and PR continue
```

## 使い始め方

セットアップは [docs/setup.md](docs/setup.md) を見てください(GitHub Project の準備、動かす用の clone、設定、スキルのリンク)。
使い方は 3 通りあり、混ぜても構いません。

| 使い方 | やること |
|---|---|
| **総指揮と話すだけ**(おすすめ) | 作業中の herdr の workspace のペインでエージェントを起動し、`/chief`。状況を教え、作業を話すとタスクに分けて提案し、「うん」で登録と開始をし、In review や Blocked になると向こうから知らせてきます |
| **チャットから登録して、ボードで承認** | 普段のエージェントとの会話の中で `/task`。カードが Backlog にできるので、やってほしいときに Ready へ移します |
| **ターミナルだけ** | `task new ...` で登録し、`task start <番号>` で開始、`task list` と `task events` で様子を見ます |

`/task` はこれまでどおり、いつでも使えます。herdr の中で頼むと、そのタスクのタブがその workspace に開きます。

## 日々の使い方

| やりたいこと | 方法 |
|---|---|
| **頼む** | |
| 今のチャットをタスクにする | エージェント内で `/task`(必要なら `/task repo is jyoka/app, use codex`) |
| 話した作業をタスクに分けてもらう | `/chief` に話す。提案に「うん」と答えると登録と開始まで行います |
| ターミナルからタスクを作る | `task new --title "..." --repo owner/name --goal "..." [--base feat/x] [--agent codex]` |
| 調べもの(コードを変えない)を頼む | `task new --research ...`、または `/task` や `/chief` に「調べて」と頼む。レポートが成果物になり、PR なしで In review |
| main ではなく作業中のブランチから始める | カードの Base branch 欄にブランチ名を書く(push 済みのもの)。PR もそのブランチに向けて出ます |
| **始める** | |
| タスクを承認してエージェントに作業させる | カードを Ready に移す、または `task start`(一覧から選択)/ `task start 12` |
| Ready のカードを自動で始める | herdr のペインで `task watch` を動かしておく(1 分ごとに確認) |
| このタスクだけ別のエージェントを使う | カードの Agent 欄を書き換える、または `task start --agent kiro` |
| **見守る** | |
| 自分の対応が必要なものを知る | `/chief` が知らせてくる。自分で見るなら `task list`(読むだけ)か `task`(Ready のカードの開始も行う) |
| ボード全体を見る | GitHub Project(ブラウザ、スマホアプリ) |
| 実行を見守る | herdr のそのタスクのタブ、または `task log 12` |
| 最近の出来事を見る | `task events`(`--follow` で起きるたびに 1 行、`--only "In review,Blocked"` で絞り込み) |
| **受け入れる・直す** | |
| レポートとレビューすべき点を読む | Issue の最新コメント、PR、または `task show 12 --full` |
| 完了した作業を受け入れる | PR をマージします。Issue が閉じてカードは Done になります |
| Blocked のタスクを再実行する | Issue の Goal に答えを書き足してカードを Ready に戻す(同じブランチと PR で続行)。`/chief` に答えを伝えて頼んでも構いません |
| タスクをクローズまたはキャンセルする | Issue を閉じる、または `task done 12` |
| **振り返る** | |
| 自動レビューや Blocked の傾向を見る | `task stats`(このマシンで終わった実行の集計) |

## 自動化の設定

`~/.config/task-hub/config.ini` で、PR の前のレビュー、Blocked の仕分け、秘密情報の受け渡しを有効にします。

```ini
[runner]
agent = claude          ; このマシンのデフォルトの実装エージェント
reviewer = agent        ; PR の前の自動レビュー。agent = タスクと同じエージェントを新しいコンテキストで
replanner = agent       ; エージェント自身の Blocked を仕分けて Issue にコメントする

[env]
; テストに要る .env などを、実行のたびに worktree にコピーする(コミットはしない)
jyoka/app = ~/code/app/.env, ~/code/app/voice/.env -> voice/.env
```

| 設定 | 有効にすると | 人が決めること |
|---|---|---|
| `reviewer` | reviewer が受け入れ条件を 1 つずつ根拠付きで確かめる。`needs changes` なら 1 回だけ差し戻し、それでも通らなければドラフト PR で Blocked | マージするかどうか |
| `replanner` | リポジトリから答えられるものは根拠(`path:行番号` と引用)付きで答え、task-hub が根拠を実物と照らし合わせる。答えられないものは、あなたへの質問を 1 行にまとめる | Ready に戻すかどうか。Goal の本文は書き換えません |
| `[env]` | 設定に書いたリポジトリにだけ、ファイルをコピーで渡す | どのリポジトリに秘密情報を渡すか |

`agent` の代わりに `codex` などのエージェント名を書くと、そのエージェントに固定できます。空か省略なら、その
自動化は行いません。詳しくは [docs/agents.md](docs/agents.md) と [docs/setup.md](docs/setup.md) を見てください。

## herdr での見え方

herdr が動いていれば、各タスクは "#<番号> <タイトル>" のタブで動きます。置き場所は、`/task`(や `/chief`)を
頼んだ workspace、なければそのリポジトリの checkout を開いている workspace、どちらもなければタスク専用の
workspace です。In review で終わったタブは自動で閉じ、Blocked で終わったタブは中身を見られるように残します。
herdr がなくても、実行はバックグラウンドで動き、`task log` で追えます。

## 使い方のパターン

**コードを直してもらう(エンジニア向け)。** 上の流れそのままです。Goal に何を直すかと受け入れ条件を書き、
エージェントの変更を PR でレビューしてマージします。

**調べもの・壁打ち(企画職など、コードを直接書かない人にも)。** 既存のリポジトリのコードをエージェントに読ませて、
調査、比較、改善案、要件の整理などをしてもらう使い方です。`--research`(`/task` や `/chief` では「調べて」と頼めば
付きます)を付けると、エージェントのレポートそのものが成果物になります。

```
task new --research --title "検索ライブラリの比較" --repo owner/app \
  --goal "今の検索の実装を読み、候補の 3 つのライブラリと比べて、移行の手間と効果をまとめる"
```

ファイルを変えずにレポートだけを書いた実行は、PR なしで In review になり、結果は Issue のコメント(`task show <番号>`)で
読めます。reviewer を設定していれば、レポートが Goal に答えているか、根拠があるかも確かめます。読み終えたら
`task done <番号>` で閉じます。提案書をファイルとして残したいときは、Goal に置き場所を書けば、今までどおり PR になります。
`--research` のないタスクで何も変えなかった実行は、これまでどおり Blocked です(Goal が伝わっていない可能性があるため)。
GitHub の Issue に `research` ラベルを手で付けても同じです。

**コード以外の雑務。** Project の画面の「+ Add item」でタイトルだけのカード(下書き)を作ります。task-hub は
Issue ではないカードを無視するので、エージェントが動くことはありません。好きな列で管理し、終わったら Done に移します。

## ボードの列

| 列 (Status) | 意味 | 対応が必要? |
|---|---|---|
| Backlog | 登録済み、未承認 | はい: やってほしいときに Ready へ |
| Ready | 承認済み。空きがあればすぐ、3 つ実行中なら空きが出たら開始 | いいえ |
| In progress | エージェントが作業中(reviewer と、その差し戻しもこの間に行う) | いいえ |
| In review | PR がオープンされた(調べものはレポートだけ)。reviewer を設定していれば、自動レビューも通っている | はい: レビューしてからマージ(調べものは読んで `task done`) |
| wait for merge(任意) | レビュー済みで、マージ待ちの PR。列が無いボードでは使いません | いいえ: マージされれば Done に移ります |
| Blocked | エージェントが何かを必要としている、自動レビューが通らなかった、または実行が失敗した(理由は Issue のコメント。replanner の仕分けもそこに付く) | はい: 対処してから Ready へ |
| Done | PR がマージされた、または Issue が閉じられた | いいえ |

## 手元に残るもの

| 内容 | 場所 |
|---|---|
| 実行のログ | `~/.local/state/task-hub/logs/<番号>.log`(`task log`) |
| 起きたこと(列の移動、replanner の判定) | `~/.local/state/task-hub/events.jsonl`(`task events`、`/chief` が見張る) |
| 実行ごとの結果(レビューの判定、差し戻し、Blocked の理由) | `~/.local/state/task-hub/metrics.jsonl`(`task stats`) |
| worktree とリポジトリの clone | `~/.local/share/task-hub/` |

## 構成

```
bin/task               the CLI (Python 3 standard library; uses git, gh, and herdr if running)
worker/PROMPT.md       the instructions every implementation agent gets at the start of a run
worker/REVIEW.md       the reviewer's instructions (adversarial, acceptance criteria one by one)
worker/REPLAN.md       the replanner's instructions (answered / human / goal-conflict, with evidence)
skills/task/SKILL.md   the /task skill: register the current conversation as a task
skills/chief/SKILL.md  the /chief skill: the one agent you talk to (watches events, proposes tasks)
tests/test_task.py     tests: python3 -m unittest discover -s tests -v
docs/                  setup, agents, design, task format, operations, lessons
```

`task` は、開発用とは別の clone(`~/.local/lib/task-hub`)から動かします。PR をマージしたら、その clone で
`git -C ~/.local/lib/task-hub pull --ff-only` を実行して更新します。

## ドキュメント

- [docs/setup.md](docs/setup.md): セットアップ(GitHub Project、動かす用の clone、設定、スキル、仕事用 Mac も含む)
- [docs/agents.md](docs/agents.md): 各エージェントの実行方法、reviewer と replanner、安全性、エージェントの追加
- [docs/task-format.md](docs/task-format.md): Issue、レポートファイル、コメント、PR の形式
- [docs/operations.md](docs/operations.md): 実行の見守り、herdr のタブ、events と stats、トラブルシューティング、後片付け
- [docs/design.md](docs/design.md): なぜこの作りなのか、ほかに検討したもの
- [docs/lessons.md](docs/lessons.md): 作ってテストしてわかったこと、まだ実証されていないこと
