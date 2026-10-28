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

Ready に移す前に `task check <番号>` を動かすと、文脈を持たないエージェント(Goldfish)が Goal とコードだけを読み、
実装に取りかかれるかを GO / NO-GO で判定します。NO-GO なら、Goal に足す文言案が Issue のコメントに付きます
([task-format.md](task-format.md#ready-の前の確かめtask-check))。

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
| 外出先のスマートフォンから登録する | `task intake` を常駐させ、ntfy アプリで `<合言葉> owner/name: やること` を送る。Backlog にでき、番号とリンクが返ってくる([operations.md](operations.md#スマートフォンからカードを作るtask-intake)) |
| エージェントを使わない雑務を管理する | Project の「+ Add item」で下書きのカードを作る。Issue ではないカードを task-hub は無視する |

## 設定

`~/.config/task-hub/config.ini` です。全体は [docs/setup.md](setup.md)、エージェントごとの設定は [docs/agents.md](agents.md) にあります。

```ini
[runner]
agent = claude          ; このマシンのデフォルトの worker
reviewer = agent        ; PR の前の自動レビュー。agent = worker と同じエージェントを新しいコンテキストで
replanner = agent       ; worker 自身の Blocked を仕分けて Issue にコメントする
parallel = 5            ; 同時に動かすタスクの数(既定 5)。性能の低い PC では 1 か 2 にする
review_retries = 2      ; needs changes で worker に差し戻す回数(既定 2。0 で差し戻さない)
review_mode = agent     ; reviewer に渡すもの。agent(既定。レポートも)/ goldfish(Goal とコードだけ。2 つの視点)
readiness = off         ; Ready のカードを始める前に task check の GO を求めるか。off(既定)/ warn / require
checker =               ; task check の Goldfish のエージェント。空か agent = カードの Agent 欄
limit_resume = on       ; エージェントが利用の上限で止まったら、戻る時刻に再開する(既定 on。off で今までどおりの Blocked)

[env]
; テストに要る .env などを、実行のたびに worktree にコピーする(コミットはしない)
jyoka/app = ~/code/app/.env, ~/code/app/voice/.env -> voice/.env

[setup]
; worker の前に worktree で実行する準備(仮想環境など)。失敗したら Blocked
jyoka/app = uv venv -q .venv && uv pip install -q -r requirements.txt --python .venv/bin/python

[notify]
events = In review, Blocked, replan, Done, slow, update, conflict, autopilot, over budget   ; 通知を出す出来事(これが既定)。空にすると出さない
ntfy =                    ; https://ntfy.sh/<トピック> を書くと、スマートフォンにも送る(既定は空)

[intake]
; task intake: スマートフォンから ntfy で送った文を Backlog のカードにする(docs/operations.md)
topic =                   ; 登録のトピック([notify] ntfy と同じサーバー、別の名前)
secret =                  ; 文の 1 語目に書く合言葉(16 文字以上)
repo =                    ; 文に owner/name: がないときの作業先

[triggers]
; task watch が自分でカードを作る(Backlog に入る)。詳しくは docs/triggers.md
ci = jyoka/app                  ; 既定のブランチの CI が失敗した
issues = jyoka/app              ; あなたに割り当てられた Issue
deps = weekly mon jyoka/app Bump the dependencies   ; 毎週の目標
drift_report =                  ; 文書とコードの食い違いを調べる research カードにする繰り返しの目標の名前

[merge]
queue = off               ; on: 承認した PR(task merge、wait for merge の列)を base に追いつかせ、競合を解き、チェックが通ったらマージする
prefix = off              ; on: キューにない In review の PR も、競合したら承認の前に解いておく(マージはしない)
rerun = 1                 ; キューで落ちたチェックを同じコミットで 1 回だけ走らせ直す(既定)。0: すぐ Blocked

[autopilot]
repos = jyoka/app         ; このリポジトリのカードは、承認(Ready)とマージを task-hub がする。[merge] queue = on と reviewer が要る

[resume]
; 止まった実行を、エージェント自身の会話の続きから再開するコマンド。組み込みの claude と pi は書かなくてよい(docs/agents.md の「止まった実行の再開」)
myagent = myagent --continue {prompt}

[balance]
; Goal の Budget に書いた有料 API の残高を、起動の前に確かめるコマンド。0 で終われば足りている(docs/operations.md の「予算と残高」)
openai = python3 scripts/check_openai_balance.py

[sandbox]
mode = user             ; Linux だけ。エージェントを専用のユーザーで動かす(既定 off)
user = task-agent       ; そのユーザー(これが既定)
```

| 設定 | 有効にすると | 人が決めること |
|---|---|---|
| `reviewer` | 受け入れ条件を 1 つずつ根拠付きで確かめる。blocking の指摘があれば `review_retries` 回まで差し戻し、同じ指摘がまた出るか変更が収束しなければ早めに止める。通らなければドラフト PR で Blocked にし、次の実行への修正指示の下書きを Issue に書く。minor の指摘だけなら In review に進み、PR に「Known issues」として残す([task-format.md](task-format.md#自動レビューの差し戻し))。判定は Project の Review 欄にも入る。`review_mode = goldfish` では、レポートを読まない 2 つの視点が別々に見る([task-format.md](task-format.md#goldfish-のレビューrunner-review_mode)) | マージするかどうか。Blocked なら下書きを確かめて Ready に戻すかどうか |
| `readiness` | `warn`: 今の Goal への `task check` の GO がない Ready のカードも始めるが、`readiness` イベントと `task` の出力で知らせる。`require`: GO がなければ始めず(`waits_for` に理由)、オートパイロットも Ready に移さない。どちらも `task list` に `readiness` の列が付く。`--research` のカードは対象外([task-format.md](task-format.md#開始の門-runner-readiness)) | `task check` の NO-GO を見て Goal を直すか、Backlog に戻すか(task-hub はカードを動かさない) |
| `replanner` | リポジトリから答えられるものは根拠付きで答え(task-hub が根拠を実物と照合)、答えられないものは質問を 1 行にまとめる。コメントするだけで、カードは動かさない | Ready に戻すかどうか |
| `[env]` | 書いたリポジトリにだけ、ファイルをコピーで渡す | どのリポジトリに秘密情報を渡すか |
| `[setup]` | 実行のたびに、worker の前に準備のコマンドを動かす。失敗や、コミットされてしまうファイルが残ったら Blocked | 何を準備するか |
| `[sandbox]` | エージェントと、worktree への git を専用の Linux ユーザーで動かし、あなたの HOME(ほかのリポジトリ、鍵、`gh` のログイン)に届かせない([sandbox.md](sandbox.md)) | そのユーザーを用意し、GitHub のトークンをどこまで許すか |
| `[triggers]` | `task watch` が CI の失敗、割り当てられた Issue、繰り返しの目標のカードを 1 回に 1 枚作る([triggers.md](triggers.md)) | Ready に移すかどうか(`ready` に書いた繰り返しの目標だけは Ready に入る)。`drift_report` に書いた目標は、文書とコードの食い違いを調べる research カードになる |
| `[merge] queue` | 承認した PR を 1 つずつ base に追いつかせ(競合はエージェントが解く)、チェックが通ったらマージする。解けない競合と、走らせ直しても落ちたチェックは Blocked | どの PR をマージしてよいか(`task merge`) |
| `[autopilot]` | 書いたリポジトリの Backlog のカードを、待ち先が終わったら Ready に移す。自動レビューが `pass` の PR をマージキューに入れる([autopilot.md](autopilot.md)) | どのリポジトリを任せるか。任せたくないカードには Goal に `Autopilot: off` |

`reviewer` と `replanner` には `codex` などのエージェント名も書けます。空か省略なら、その自動化は行いません。

## チームのボードに出す(task share)

個人のボードのタスクのうち、選んだものだけをチームの GitHub(組織のリポジトリの Issue と、組織の Project のカード)に
出します。正本は個人のボードのままで、写す向きは個人 → チームだけです(設計は
[architecture/designs/team-sync.md](architecture/designs/team-sync.md))。

```
task share 12 --to org/app [--project org/7]
```

- チームのリポジトリに Issue を 1 つ作ります。タイトルは `[share]` の接頭辞 + 個人の Issue のタイトル、本文は
  「task-hub が上書きするので意見はコメントへ」という注意のあとに Goal をそのまま、担当はあなた(`--assignee @me`)です
- 個人の Issue にある task-hub のコメント(Report、Blocked の仕分け)も写します。人のコメントは写しません
- チームの Project(`--project`、なければ `[share]`。どちらもなければ Issue だけ)にカードを足し、Status と既定の欄を入れます
- 個人の Issue に、つなぎ先のコメント(`<!-- task-hub link -->` で始まる)を書きます。選んだ Project も残すので、あとから設定を変えてもその Project に写します。2 回目からは同じ Issue を出すだけです
- つなぎ先は、今 `gh` でログインしているアカウントが書いたコメントだけを読みます。ほかの人のコメントでは、別の Issue を書き換えたり閉じたりしません
- そのあとの実行の PR は、本文に `Closes` を 2 つ(個人の Issue とチームの Issue)持ちます。マージで両方が閉じます。
  開いている PR がすでにあれば、`task share` がその場で足します(実行中なら、終わってからもう一度 `task share`)
- 出したくない部分があるタスクは共有しません(本文を変えて出す方法はありません)。本文に同じリポジトリの Issue の
  URL や `#番号` があると、チームのリポジトリではその Issue への参照になります。個人の Issue へのリンクは、チームの人には開けません

つないだあとも、task-hub が変えたものはチームに写ります(向きは個人 → チームだけ)。

- Status が変わると、チームのカードを下の対応表の列に動かします。チームのカードがもうその列にあれば何もしません。
  スマホで Ready に移したときは写さず、実行が始まって In progress にするときに写します
- 実行を始めるたびに、チームの Issue のタイトルと本文を個人の Issue から写し直します。Goal に答えを書き足して Ready に
  戻したときも、次の実行で新しい Goal になります。チームの人が本文を直していても上書きします
- task-hub がコメント(Report、Blocked の仕分け)を書くと、同じ本文をチームの Issue にもコメントします。人のコメントは写しません
- `task done` でチームの Issue も閉じます。デフォルトブランチ以外へのマージで GitHub が閉じなかったときは、マージを見つけた
  同期がチームの Issue も閉じます
- 写すのに失敗しても、個人のカードと実行は止まりません。stderr(実行の中ならログ)に `warning: task <番号>: could not copy ...`
  を 1 行出します
- 実行中に共有したタスクは、その実行が終わるまで写しません(次の実行から写します)

```ini
[share]
org/app = org/7                      ; org/app に出した Issue を足すチームの Project
org/app.title = 【Sprint 3】          ; タイトルの接頭辞。末尾に空白を残すなら "[Sprint 3] " と引用符で囲む
org/app.field.Sprint = Sprint 3      ; カードに入れる単一選択の欄と値(いくつでも)
status.Blocked = Todo                ; 個人の列 = チームの列(すべての共有先)
org/app.status.In review = Review    ; この共有先だけの対応
```

チームの列は、`[share]` の対応、チームの同じ名前の列、次の既定の順で決めます。

| 個人の列 | チームの列(既定) |
|---|---|
| Backlog | Todo |
| Ready、In progress、In review、wait for merge、Blocked | In progress |
| Done | Done |

`[share]` に書いた列、欄、値がチームの Project になければ、何も作らずに `error:` で止まります。チームのリポジトリに
書けないとき(権限、別のアカウント)も、`error:` と `help:` を出して終わり、個人のカードと PR は変えません。

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
| `task check` ごとの判定と、起動ごとの秒数とトークン数 | `~/.local/state/task-hub/checks.jsonl`(`task stats` の `checks:` 行)。ログは `logs/<番号>-check.log` |
| `task review --no-write` ごとの判定と、起動ごとの秒数とトークン数 | `~/.local/state/task-hub/review-trials.jsonl`。ログは `logs/<番号>-review-trial.log` |
| 最後に読んだ各カードの判定(`[runner] readiness` が `off` 以外のとき) | `~/.local/state/task-hub/readiness.json` |
| worktree とリポジトリの clone | `~/.local/share/task-hub/` |
| task-hub の新しい版を確かめた結果(1 日 1 回まで) | `~/.local/state/task-hub/update.json` |

## 動かし方の補足

### 止まったとき

```
worker      「Stripe のテスト用キーが要る」と書いて止まる                          Blocked
replanner   answered(リポジトリにある答えを根拠付きで)/ human(あなたへの質問を 1 行に)/ goal-conflict
あなた      Goal に答えを書き足すか Issue や PR にコメントして Ready に戻す → 同じブランチと PR で続きから(コメントも渡る)
```

### スキルの呼び方、自動で始める、通知

`/task` と `/chief` は Claude Code と Kiro での呼び方です。Pi では `/skill:chief`、Codex では `$chief` のように
呼びます([docs/setup.md](setup.md#task-と-chief-スキルのインストール))。

Ready のカードを自動で始めるには、herdr のペインで `task watch` を動かしておきます(1 分ごとに確認)。
`[triggers]` を書いていれば、`task watch` はカードを自分で作ることもします([triggers.md](triggers.md))。
`task` を引数なしで実行しても、その場で 1 回確認して始めます。
`task watch` は、GitHub のエラー、動いている間に壊れた設定ファイル、始められないカードでは止まりません。
`error:` の行を出し(始められないカードは理由を書いて Blocked にし)、次の回にまた確かめます。

In review、Blocked、replanner の仕分け、Done、長引いている実行(`slow`)、予算を超えた実行(`over budget`)は、task-hub 自身が通知で知らせます(herdr が動いていれば herdr の
通知、なければ macOS の通知)。文面はタイトル、判定か理由、見てほしいこと、PR の URL で、LLM は使わないので
費用はかかりません。知らせを受けるためだけに `/chief` を開いておく必要はなく、相談したいときに開けば足ります。

### In review の PR の読み方

worker のレポートの Please review には、確認すべき場所に加えて学習ルートが 1 つ付きます
([task-format.md](task-format.md#エージェントのレポートファイル))。説明を読むだけで終わらせず、次の順に自分で探すと、
エージェントが書いたコードを理解したうえでマージを決められます。

1. Goal を読み、コードがどこにあるかを予想する
2. 自分で検索する(`rg`。候補を絞るなら `fzf`)。ルートの Search は答え合わせに使う
3. 見つけた場所の周りのコードと、タスクの差分を読む
4. ルートの Check にあるテストが何を確かめているかを理解する
5. Explain yourself の質問に自分で答えてから、マージするかを決める

これは人の習慣で、task-hub は何も確かめません(状態も、マージの条件も増えません)。`rg` と `fzf` は手元で使う
道具で、task-hub には要りません。エージェントは `fzf` を起動しません。

### 任意の列 wait for merge

In review と Done の間に `wait for merge` の列を足せます。レビュー済みでマージ待ちのカードを置く列で、
マージされた PR はいつもどおり Done に移します。列のないボードでは使いません。

`[merge] queue = on` にすると、この列はマージキューの入口になります。カードをここに動かす(または `task merge <番号>`)と
承認したことになり、`task watch` が base に追いつかせて、チェックが通ったらマージします
([operations.md](operations.md#マージキュー))。

### 更新

`task` は、開発用とは別の clone(`~/.local/lib/task-hub`)から動かします。新しい版が出ると `task list` と
`task watch` が 1 行で知らせるので、`task update` で更新します(clone を最新のリリースまで進め、launchd の
`task watch` の再起動と Kiro IDE の定義のコピーし直しもまとめて行います。[docs/setup.md](setup.md#インストール))。
Windows でも同じで、常駐(タスク スケジューラ)の `task watch` も新しい版で始め直します。

かんたんセットアップ(Mac の `kiro/install.sh`、Windows の `windows\install.ps1`)で入れた人の clone は、リリースの
タグ(v0.12.0 以上)の上にあります。そのときの `task update` は、一番新しいリリースのインストーラを、その版の写し(手元の clone
から作るので、ダウンロードはしない)から動かします。Kiro のチャットで「セットアップして」ともう一度言うのと同じで、
スキル、フック、Slackトリアージの起動キーまで新しい版になります。常駐を入れていれば、そのまま新しい版で動きます。
知らせの行は、ブランチの上の clone と同じです(例 `update: v0.13.0 が出ています。`task update` で更新(今は v0.12.0)`)。
