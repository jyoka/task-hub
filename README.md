# task-hub

GitHub Project をかんばんボードにして、そのタスクをコーディングエージェント(Claude Code、Codex、Pi、Kiro など、
非対話モードを持つ CLI なら何でも)に実行させるツールです。

あなたが決めるのは 2 つだけです。

- **始めてよいか**: カードを Ready に移す
- **入れてよいか**: PR をマージする

その間の実装、レビュー、PR の作成、止まったときの仕分け、順番待ちは、task-hub とエージェントが進めます。

## 全体構成

```
あなた
 ├─ 話す・頼む ──▶ あなたのエージェントの会話
 │                   /task    今の会話をタスクとして登録
 │                   /chief   ボードを見張って知らせる、作業を分けて提案、「うん」で登録・開始
 │                   to-issues などほかのスキルも task new で登録
 │                        │
 │                        ▼
 ├─ Ready に移す ─▶ GitHub(状態はすべてここ)
 │                   Project     かんばんボード
 │                   Issue       タスク(本文が Goal)。Blocked by で前後関係、research ラベルで調べもの
 │                   PR          成果(作業先のリポジトリ)
 │                        │ 1 分ごとに読む
 │                        ▼
 │                 task-hub(bin/task、あなたの Mac で動くコード)
 │                   開始の判定  Ready で、待ち先がすべて完了していて、実行の枠(最大 5)が空いている
 │                   準備        clone → worktree(task/<番号>)→ [env] のコピー → [setup] の実行
 │                   実行        worker → reviewer ─ pass ─────────▶ commit・push・PR → In review
 │                                  ▲        └ needs changes(1 回だけ差し戻す。2 回目も不合格なら Blocked)
 │                                  └────────┘
 │                               worker が「Blocked」と書いた → replanner が仕分けて Issue にコメント
 │                   後片付け    マージを見て Done に。worktree、ブランチ、herdr のタブを片付ける
 │                   記録        events.jsonl(出来事。/chief を起こす)、metrics.jsonl(実行ごとの数字)
 │                        │
 └─ PR をマージ ◀─────────┘ In review
```

### 役割

task-hub が定義している役割は 5 つです。どれも Claude Code の sub-agent ではなく、役割ごとの指示書です。
ランナーが起動する 3 つは別プロセスの CLI として動くので、どのエージェントでも同じ形で使えます。

| 役割 | どこで動くか | 仕事 | 書いてよいもの | 指示書 |
|---|---|---|---|---|
| **worker** | task-hub が起動(タスクごと) | Goal を実装し、テストし、レポートを書く | worktree のファイル、`.task-report.md` | [worker/PROMPT.md](worker/PROMPT.md) |
| **reviewer**(任意) | task-hub が起動(worker の後、PR の前) | Goal の受け入れ条件を 1 つずつ、PR 全体と照らし合わせる | `.task-review.md` だけ | [worker/REVIEW.md](worker/REVIEW.md) |
| **replanner**(任意) | task-hub が起動(worker が自分で Blocked と書いたとき) | 止まった理由を「リポジトリから答えられる / 人に聞く / Goal が矛盾」に仕分ける | 何も書けない(コメントの本文を返すだけ) | [worker/REPLAN.md](worker/REPLAN.md) |
| **/task** | あなたのエージェントの会話 | 今の会話を Backlog のタスクとして登録する | ボードへの登録だけ | [skills/task](skills/task/SKILL.md) |
| **/chief**(総指揮) | あなたのエージェントの会話(herdr のペイン) | ボードを見張って知らせる。作業を分けて提案し、「うん」で登録・開始する | 登録と開始だけ(マージはしない) | [skills/chief](skills/chief/SKILL.md) |

### 分担

- **LLM が担うのは、判断が要る 3 か所だけです**: 実装する、評価する、止まった理由を仕分ける。
- **それ以外はコードが決めます**: いつ始めるか、git と PR、判定の読み取り、replanner の根拠(`path:行番号` と引用)が
  実物と合うかの照合、reviewer が勝手に書き換えた分の取り消し、前後関係の判定。エージェントとの約束は
  「ファイルを編集し、テストし、レポートを書く」だけなので、どのベンダーでも同じ動きになります。
- **エージェントがタスクを勝手に作ったり始めたりすることはありません。** 登録は `/task`・`task new`・`/chief`
  (あなたの「うん」のあと)だけ、開始は Ready に移したとき(または `task start`)だけです。

## タスクの一生

| 列 (Status) | 何が起きているか | あなたの対応 |
|---|---|---|
| **Backlog** | 登録済み、未承認 | やってほしいときに Ready へ |
| **Ready** | 承認済み。枠(最大 5)が空けば始まる。「Blocked by」の待ち先が終わるまでは、枠を使わずに待つ(`task list` の `waits_for` に理由) | なし(待ち先が Blocked なら、そちらに対応) |
| **In progress** | worker が作業中。reviewer と、その差し戻しもこの間 | なし |
| **In review** | PR ができた(調べものはレポートだけ)。reviewer を設定していれば、自動レビューも通っている | PR をレビューしてマージ(調べものは読んで `task done`) |
| wait for merge(任意) | レビュー済みで、マージ待ち。列のないボードでは使わない | なし |
| **Blocked** | エージェントが何かを必要としている、自動レビューが通らなかった、または実行が失敗した。理由と replanner の仕分けは Issue のコメント | 答えを Goal に書き足して Ready へ(同じブランチと PR で続く) |
| **Done** | PR がマージされた、または Issue が閉じられた。後片付けが済み、これを待っていたタスクが始まる | なし |

例: 「ログインを直す」を頼んで、マージするまで。

```
あなた      /task(または /chief に話す)            → Issue jyoka/tasks#12、Backlog
あなた      カードを Ready に移す                    → task-hub が開始                 In progress
            herdr に "#12 ログインを直す" のタブが開く
worker      編集し、テストし、レポートを書く
reviewer    受け入れ条件を PR 全体と照らし合わせる   → pass(needs changes なら 1 回差し戻し)
task-hub    task/12 を push し、PR を作り、レポートと判定を Issue にコメント   In review
            タブは自分で閉じる(出力は task log 12 に残る)
あなた      PR をレビューしてマージ                  → Issue が閉じる                  Done
```

止まったとき:

```
worker      「Stripe のテスト用キーが要る」と書いて止まる                          Blocked
replanner   answered(リポジトリにある答えを根拠付きで)/ human(あなたへの質問を 1 行に)/ goal-conflict
あなた      Goal に答えを書き足して Ready に戻す     → 同じブランチと PR で続きから
```

## はじめる

セットアップは [docs/setup.md](docs/setup.md) にあります(GitHub Project の準備、動かす用の clone、設定、スキルのリンク)。
使い方は 3 通りで、混ぜても構いません。

| 使い方 | やること |
|---|---|
| **総指揮と話す**(おすすめ) | 作業中の herdr の workspace のペインでエージェントを起動し、`/chief`。状況を教え、話した作業をタスクに分けて提案し、「うん」で登録と開始をし、In review や Blocked になると向こうから知らせてきます |
| **会話から登録して、ボードで承認** | 普段のエージェントとの会話で `/task`。Backlog にカードができるので、やってほしいときに Ready へ移します |
| **ターミナルだけ** | `task new` で登録、`task start <番号>` で開始、`task list` と `task events` で様子を見ます |

`/task` と `/chief` は Claude Code と Kiro での呼び方です。Pi では `/skill:chief`、Codex では `$chief` のように
呼びます([docs/setup.md](docs/setup.md#task-と-chief-スキルのインストール))。

Ready のカードを自動で始めるには、herdr のペインで `task watch` を動かしておきます(1 分ごとに確認)。
`task` を引数なしで実行しても、その場で 1 回確認して始めます。

## タスクの頼み方

### Goal に書くこと

エージェントが見るのは Goal(Issue の本文)とリポジトリだけです。会話で決まったことは、すべて Goal に書きます。

- 何をするか、なぜか。関係するファイル、決まったこと、制約、やらないこと
- **受け入れ条件**: エージェントと reviewer が 1 つずつ確かめられるチェックリスト
- **`### Ready conditions`**(任意): 開始前にそろっているべきこと。依存するタスクとそこから使うもの、決まっているべき
  仕様、`.env` のキーなど。エージェントは最初にこれを確かめ、足りなければ何も変えずに Blocked で止まります

### 大きさと分け方

1 つのタスクは、単独でレビュー・マージ・取り消しができる 1 つの関心ごとにします(10〜15 分でレビューできる PR が
目安)。性質の違う作業(機能、バグ、開発環境、ドキュメント)は分け、同じファイルを触る作業はまとめます(分けると
PR 同士が競合します)。`/task` と `/chief` はこの基準で分け方を提案し、分けたタスクには「PR #23 follow-up (1/3): ...」
のような共通の接頭辞を付けます。

### 前後関係

前のタスクのコードや結論が必要なタスクには、GitHub の「Blocked by」を付けます。

```
task new --title "検索 API を使う画面" --repo owner/app --blocked-by 12 --goal-file goal.md
```

- 待っているタスクは Ready にしておいて構いません。#12 が完了として閉じる(PR のマージ、`task done`)と自動で始まります。
  開始時に最新のベースから作業を始めるので、#12 の PR がマージされていれば、その変更を前提に作業できます。
- 待ち先が「not planned」や「duplicate」で閉じた場合は、前提が届いていないので待ち続けます。不要ならリンクを外します。
- `/task` と `/chief` は、分けたタスクに前後関係があれば付けます。Issue の画面の Relationships から付けても同じです。
- 本文の `Blocked by` や `Ready conditions` の見出しの下にだけ書かれた番号(`task new` を通さずに作った Issue)も、
  ボード上の開いたカードなら開始を待たせ、`waits_for` に「only in the body: link it」と出します。
- to-prd や to-issues など、ほかのスキルからボードに作るときの手順は [docs/issue-tracker.md](docs/issue-tracker.md) にあります。

### そのほかの頼み方

| やりたいこと | 方法 |
|---|---|
| 調べもの(コードを変えない)を頼む | `task new --research ...`、または `/task` や `/chief` に「調べて」と頼む。レポートが成果物になり、PR なしで In review になる。読み終えたら `task done` |
| main ではなく作業中のブランチから始める | カードの Base branch 欄にブランチ名を書く(push 済みのもの)。PR もそのブランチに向けて出る |
| このタスクだけ別のエージェントを使う | カードの Agent 欄に書く、または `task start --agent kiro` |
| エージェントを使わない雑務を管理する | Project の「+ Add item」で下書きのカードを作る。Issue ではないカードを task-hub は無視する |

## コマンド

| コマンド | すること |
|---|---|
| `task` | ボードと同期し、Ready のカードを始め、あなたの対応が必要なものを出す |
| `task list` | 開いているカードの一覧(読むだけで、何も始めない) |
| `task new --title ... --repo owner/name (--goal ... \| --goal-file ...)` | タスクを登録する。`--base`、`--agent`、`--research`、`--blocked-by 12,14` |
| `task start [<番号>] [--agent 名前]` | Backlog を承認する、または Blocked を再実行する。番号なしなら一覧から選ぶ |
| `task watch` | Ready のカードを自動で始める(1 分ごと) |
| `task show <番号> [--full]` | Issue と最新のレポート、replanner の仕分け |
| `task log <番号> [--full]` | このマシンでの実行の出力 |
| `task events [--follow \| --next] [--only "In review,Blocked"]` | 最近の出来事。`--follow` は起きるたびに 1 行、`--next` は次の出来事を待って終わる |
| `task stats` | このマシンで終わった実行の集計(自動レビュー、差し戻し、Blocked の理由、PR の大きさ、トークン数) |
| `task done <番号>` | 手で閉じる・取り消す(マージされた PR は自動で閉じる) |

## 設定

`~/.config/task-hub/config.ini` です。全体は [docs/setup.md](docs/setup.md)、エージェントごとの設定は [docs/agents.md](docs/agents.md) にあります。

```ini
[runner]
agent = claude          ; このマシンのデフォルトの worker
reviewer = agent        ; PR の前の自動レビュー。agent = worker と同じエージェントを新しいコンテキストで
replanner = agent       ; worker 自身の Blocked を仕分けて Issue にコメントする

[env]
; テストに要る .env などを、実行のたびに worktree にコピーする(コミットはしない)
jyoka/app = ~/code/app/.env, ~/code/app/voice/.env -> voice/.env

[setup]
; worker の前に worktree で実行する準備(仮想環境など)。失敗したら Blocked
jyoka/app = uv venv -q .venv && uv pip install -q -r requirements.txt --python .venv/bin/python
```

| 設定 | 有効にすると | 人が決めること |
|---|---|---|
| `reviewer` | 受け入れ条件を 1 つずつ根拠付きで確かめる。`needs changes` なら 1 回だけ差し戻し、それでも通らなければドラフト PR で Blocked | マージするかどうか |
| `replanner` | リポジトリから答えられるものは根拠付きで答え(task-hub が根拠を実物と照合)、答えられないものは質問を 1 行にまとめる。コメントするだけで、カードは動かさない | Ready に戻すかどうか |
| `[env]` | 書いたリポジトリにだけ、ファイルをコピーで渡す | どのリポジトリに秘密情報を渡すか |
| `[setup]` | 実行のたびに、worker の前に準備のコマンドを動かす。失敗や、コミットされてしまうファイルが残ったら Blocked | 何を準備するか |

`reviewer` と `replanner` には `codex` などのエージェント名も書けます。空か省略なら、その自動化は行いません。

## 見え方と、手元に残るもの

**herdr のタブ。** herdr が動いていれば、各タスクは "#<番号> <タイトル>" のタブで動きます。置き場所は次の順で決まります。

1. `/task` や `/chief` で登録した workspace
2. 登録時の記録がなければ、`task start` や `task` を手で実行した workspace(`task watch` は含まない)
3. そのリポジトリの checkout を開いているペインがある workspace
4. どれもなければ、タスク専用の workspace

In review で終わったタブは自動で閉じ、Blocked のタブは中身を見られるように残します。herdr がなくても、実行は
バックグラウンドで動き、`task log` で追えます。

**手元の記録。** GitHub に載るのは Issue、コメント、PR だけです。実行中の情報はこのマシンにだけ残ります。

| 内容 | 場所 |
|---|---|
| 実行のログ | `~/.local/state/task-hub/logs/<番号>.log`(`task log`) |
| 起きたこと(列の移動、replanner の判定) | `~/.local/state/task-hub/events.jsonl`(`task events`、`/chief` が見張る) |
| 実行ごとの結果(レビューの判定、差し戻し、Blocked の理由、起動ごとの秒数とトークン数) | `~/.local/state/task-hub/metrics.jsonl`(`task stats`) |
| worktree とリポジトリの clone | `~/.local/share/task-hub/` |

## リポジトリの中身

```
bin/task               CLI(Python 3 の標準ライブラリだけ。git、gh、動いていれば herdr を使う)
worker/PROMPT.md       worker の指示書(実行のたびに渡す)
worker/REVIEW.md       reviewer の指示書(受け入れ条件を 1 つずつ、根拠付きで)
worker/REPLAN.md       replanner の指示書(answered / human / goal-conflict、根拠付き)
skills/task/SKILL.md   /task スキル
skills/chief/SKILL.md  /chief スキル
pi/task-events.ts      Pi の拡張機能: 出来事で /chief を起こす(Pi にはバックグラウンド実行がないため)
tests/test_task.py     テスト: python3 -m unittest discover -s tests -v
docs/                  セットアップ、エージェント、設計、形式、運用、教訓
```

`task` は、開発用とは別の clone(`~/.local/lib/task-hub`)から動かします。PR をマージしたら
`git -C ~/.local/lib/task-hub pull --ff-only` で更新します。

## ドキュメント

- [docs/setup.md](docs/setup.md): セットアップ(GitHub Project、動かす用の clone、設定、スキル、仕事用 Mac も含む)
- [docs/agents.md](docs/agents.md): 各エージェントの実行方法、reviewer と replanner、安全性、エージェントの追加
- [docs/task-format.md](docs/task-format.md): Issue、Blocked by と Ready conditions、レポートファイル、コメント、PR の形式
- [docs/issue-tracker.md](docs/issue-tracker.md): ほかのスキル(to-prd、to-issues など)がボードに Issue を作るときの手順
- [docs/operations.md](docs/operations.md): 実行の見守り、herdr のタブ、events と stats、トラブルシューティング、後片付け
- [docs/design.md](docs/design.md): なぜこの作りなのか、ほかに検討したもの
- [docs/lessons.md](docs/lessons.md): 作って試してわかったこと、まだ確かめていないこと
