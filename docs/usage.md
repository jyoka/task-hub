# 使い方の詳細

[README](../README.ja.md) の続きです。タスクの頼み方、設定、役割、手元に残るものを書きます。セットアップは [setup.md](setup.md)、
全体の仕組みは [architecture/hld.md](architecture/hld.md) にあります。

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
- to-prd や to-issues など、ほかのスキルからボードに作るときの手順は [docs/issue-tracker.md](issue-tracker.md) にあります。

### そのほかの頼み方

| やりたいこと | 方法 |
|---|---|
| 調べもの(コードを変えない)を頼む | `task new --research ...`、または `/task` や `/chief` に「調べて」と頼む。レポートが成果物になり、PR なしで In review になる。読み終えたら `task done` |
| main ではなく作業中のブランチから始める | カードの Base branch 欄にブランチ名を書く(push 済みのもの)。PR もそのブランチに向けて出る |
| このタスクだけ別のエージェントを使う | カードの Agent 欄に書く、または `task start --agent kiro` |
| エージェントを使わない雑務を管理する | Project の「+ Add item」で下書きのカードを作る。Issue ではないカードを task-hub は無視する |

## 設定

`~/.config/task-hub/config.ini` です。全体は [docs/setup.md](setup.md)、エージェントごとの設定は [docs/agents.md](agents.md) にあります。

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

[notify]
events = In review, Blocked, replan, Done, slow   ; 通知を出す出来事(これが既定)。空にすると出さない
```

| 設定 | 有効にすると | 人が決めること |
|---|---|---|
| `reviewer` | 受け入れ条件を 1 つずつ根拠付きで確かめる。`needs changes` なら 1 回だけ差し戻し、それでも通らなければドラフト PR で Blocked | マージするかどうか |
| `replanner` | リポジトリから答えられるものは根拠付きで答え(task-hub が根拠を実物と照合)、答えられないものは質問を 1 行にまとめる。コメントするだけで、カードは動かさない | Ready に戻すかどうか |
| `[env]` | 書いたリポジトリにだけ、ファイルをコピーで渡す | どのリポジトリに秘密情報を渡すか |
| `[setup]` | 実行のたびに、worker の前に準備のコマンドを動かす。失敗や、コミットされてしまうファイルが残ったら Blocked | 何を準備するか |

`reviewer` と `replanner` には `codex` などのエージェント名も書けます。空か省略なら、その自動化は行いません。

## 役割と分担

### 役割

task-hub が定義している役割は 5 つです。どれも Claude Code の sub-agent ではなく、役割ごとの指示書です。
ランナーが起動する 3 つは別プロセスの CLI として動くので、どのエージェントでも同じ形で使えます。

| 役割 | どこで動くか | 仕事 | 書いてよいもの | 指示書 |
|---|---|---|---|---|
| **worker** | task-hub が起動(タスクごと) | Goal を実装し、テストし、レポートを書く | worktree のファイル、`.task-report.md` | [worker/PROMPT.md](../worker/PROMPT.md) |
| **reviewer**(任意) | task-hub が起動(worker の後、PR の前) | Goal の受け入れ条件を 1 つずつ、PR 全体と照らし合わせる | `.task-review.md` だけ | [worker/REVIEW.md](../worker/REVIEW.md) |
| **replanner**(任意) | task-hub が起動(worker が自分で Blocked と書いたとき) | 止まった理由を「リポジトリから答えられる / 人に聞く / Goal が矛盾」に仕分ける | 何も書けない(コメントの本文を返すだけ) | [worker/REPLAN.md](../worker/REPLAN.md) |
| **/task** | あなたのエージェントの会話 | 今の会話を Backlog のタスクとして登録する | ボードへの登録だけ | [skills/task](../skills/task/SKILL.md) |
| **/chief**(総指揮) | あなたのエージェントの会話(herdr のペイン) | ボードを見張って知らせる。作業を分けて提案し、「うん」で登録・開始する。名指しで頼まれたら開始・`task done`・マージを実行する | 登録・開始・`task done`・マージ(どれもあなたが頼んだときだけ。自分からはしない) | [skills/chief](../skills/chief/SKILL.md) |

### 分担

- **LLM が担うのは、判断が要る 3 か所だけです**: 実装する、評価する、止まった理由を仕分ける。
- **それ以外はコードが決めます**: いつ始めるか、git と PR、判定の読み取り、replanner の根拠(`path:行番号` と引用)が
  実物と合うかの照合、reviewer が勝手に書き換えた分の取り消し、前後関係の判定。エージェントとの約束は
  「ファイルを編集し、テストし、レポートを書く」だけなので、どのベンダーでも同じ動きになります。
- **エージェントがタスクを勝手に作ったり始めたりすることはありません。** 登録は `/task`(Claude Code では、会話で「タスクにして」と
  頼んだときも)・`task new`・`/chief`(あなたの「うん」のあと)だけ、開始は Ready に移したとき(または `task start`)だけです。

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
| 起きたこと(列の移動、replanner の判定) | `~/.local/state/task-hub/events.jsonl`(`task events`、`/chief` が見張る。書くときに通知も出す) |
| 実行ごとの結果(レビューの判定、差し戻し、Blocked の理由、起動ごとの秒数とトークン数) | `~/.local/state/task-hub/metrics.jsonl`(`task stats`) |
| worktree とリポジトリの clone | `~/.local/share/task-hub/` |
| task-hub の新しい版を確かめた結果(1 日 1 回まで) | `~/.local/state/task-hub/update.json` |

## 動かし方の補足

### 止まったとき

```
worker      「Stripe のテスト用キーが要る」と書いて止まる                          Blocked
replanner   answered(リポジトリにある答えを根拠付きで)/ human(あなたへの質問を 1 行に)/ goal-conflict
あなた      Goal に答えを書き足して Ready に戻す     → 同じブランチと PR で続きから
```

### スキルの呼び方、自動で始める、通知

`/task` と `/chief` は Claude Code と Kiro での呼び方です。Pi では `/skill:chief`、Codex では `$chief` のように
呼びます([docs/setup.md](setup.md#task-と-chief-スキルのインストール))。

Ready のカードを自動で始めるには、herdr のペインで `task watch` を動かしておきます(1 分ごとに確認)。
`task` を引数なしで実行しても、その場で 1 回確認して始めます。

In review、Blocked、replanner の仕分け、Done、長引いている実行(`slow`)は、task-hub 自身が通知で知らせます(herdr が動いていれば herdr の
通知、なければ macOS の通知)。文面はタイトル、判定か理由、見てほしいこと、PR の URL で、LLM は使わないので
費用はかかりません。知らせを受けるためだけに `/chief` を開いておく必要はなく、相談したいときに開けば足ります。

### 任意の列 wait for merge

In review と Done の間に `wait for merge` の列を足せます。レビュー済みでマージ待ちのカードを置く列で、
マージされた PR はいつもどおり Done に移します。列のないボードでは使いません。

### 更新

`task` は、開発用とは別の clone(`~/.local/lib/task-hub`)から動かします。新しい版が出ると `task list` と
`task watch` が 1 行で知らせるので、`task update` で更新します(clone を最新のリリースまで進め、launchd の
`task watch` の再起動と Kiro IDE の定義のコピーし直しもまとめて行います。[docs/setup.md](setup.md#インストール))。
