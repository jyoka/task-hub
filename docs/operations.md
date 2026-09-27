# 運用とトラブルシューティング

全体は GitHub Project のボードで見ます。手元では `task` を実行します。ボードと実行中のタスクと PR を確認し、
空きがあれば Ready のカードを開始し、あなたの対応が必要なタスクの数を表示します。herdr のペインで `task watch` を
動かしておけば、これを 1 分ごとに自動で行います。

## 実行の様子を見る

- **herdr**: 各実行は "#<番号> <title>" という名前のタブで動き、エージェントの出力をリアルタイムで確認できます。
  タブを置く workspace は、次の順で決まります。
  1. `/task` を頼んだ workspace(herdr のペインの中で登録したとき)。登録時の記録がなければ(`gh issue create`
     やほかのスキル、GitHub の画面で作った Issue)、`task start` や `task` を手で実行した workspace。`task watch` が
     始めたものは、watch の場所には置きません
  2. そのリポジトリの checkout を開いているペインがある workspace(スマホやボードから作ったカードなど)
  3. どちらもなければ、タスク専用の workspace "task <番号> · <リポジトリ名>: <title>" を作る

  In review で終わったタブは自動で閉じます(出力は `task log <番号>` で読めます)。Blocked で終わったタブは、
  何が起きたかを見られるように残し、`task done <番号>` か PR のマージで閉じます。task-hub が閉じるのは、自分が
  作ったタブだけです(herdr が同じ id を別のタブに使い回していないか、名前で確かめてから閉じます)。
- **herdr なしの場合**: `task log <番号>` で最後の 40 行を、`task log <番号> --full` ですべてを表示します。
- エージェントに伝えた内容: `~/.local/share/task-hub/prompts/<番号>.md`。

## 起きたことを受け取る(events.jsonl)

task-hub はカードの列を動かすたびに、`~/.local/state/task-hub/events.jsonl` に 1 行書きます。GitHub を見に行かなくても、
このファイルを見張れば、何かが起きた瞬間に分かります。`task events` は最近の 20 件を、`task events --follow` は
新しい出来事を起きるたびに 1 行ずつ出します。`task events --next` は次の出来事を待って出力し、続きから読むための
コマンドを `next: task events --next --after <n> ...` の行に出して終わります(`<n>` は events.jsonl の行番号なので、
2 回の実行の間に起きたことも取りこぼしません)。総指揮のエージェント(`/chief`)は `--next` を裏で動かし、終わって
起こされるたびに `next:` のコマンドで動かし直します。「終わったら起こす」バックグラウンド実行でも、「1 行ごとに
起こす」監視でも同じように動きます。

```json
{"time": "2026-09-26T14:05:00Z", "id": "41", "title": "保存できる項目に…", "repo": "jyoka/aica_ra_a2a_poc", "event": "In review", "pr": "https://github.com/jyoka/aica_ra_a2a_poc/pull/36", "digest": {"verdict": "pass", "review": ["api/save.py: 必須項目の判定", "マイグレーションの順番"], "pr": "https://github.com/jyoka/aica_ra_a2a_poc/pull/36"}}
{"time": "2026-09-26T14:20:00Z", "id": "32", "title": "求人検索と…", "repo": "jyoka/aica_ra_a2a_poc", "event": "Blocked", "reason": "前提の PR #26 がまだマージされていない", "digest": {"reason": "前提の PR #26 がまだマージされていない"}}
{"time": "2026-09-26T14:21:00Z", "id": "32", "title": "求人検索と…", "repo": "jyoka/aica_ra_a2a_poc", "event": "replan", "decision": "human", "digest": {"decision": "human", "question": "PR #26 を先にマージしてよいですか?"}}
```

`event` は列の名前(`Backlog`、`Ready`、`In progress`、`In review`、`Blocked`、`Done`)か、replanner が仕分けたときの
`replan` です。`reason`(Blocked の 1 行)、`pr`、`decision`、`digest` は、あるときだけ入ります。マシンごとのファイルで、
そのマシンの task-hub が動かしたものだけが書かれます。

### 判断用の要点(digest)

In review、Blocked、replan のイベントには、人が判断するための要点 `digest` が入ります。task-hub が Issue に書く
レポートや replanner のコメントと同じ内容から、書くその場で作るので、GitHub を読み直しません。読む側も
`task show <番号> --full` を読まずに、イベントだけで判断できます。

| キー | 入るとき | 中身 |
|---|---|---|
| `verdict` | 自動レビューがあるとき | 自動レビューの判定(`pass`、`needs changes`、`blocked`) |
| `reason` | Blocked | 止まった理由の 1 行 |
| `review` | レポートに Please review があるとき | 項目を最大 3 つ。多いときは `(+N more)` を足す |
| `report` | PR のない In review(research タスク) | Report の頭 |
| `decision` | replan | replanner の判定(`answered`、`human`、`goal-conflict`) |
| `question` / `answer` / `goal_change` | replan | 人への質問、replanner の答え、Goal の変更案 |
| `pr` | PR があるとき | PR の URL |

長さには上限があります。1 項目 120 文字、`reason`・`report`・`question`・`answer`・`goal_change` は 240 文字で切り、
1 件の要点は 1000 文字に収まります。

`task events` に `--digest` を付けると(`--next`、`--follow`、引数なしのどれでも)、イベントの行の下に要点を
`  review: ...` のように字下げして出します。行に出ている `reason`、`decision`、`pr` は繰り返しません。
要点を持たない古いイベントには ``digest: none, run `task show <番号> --digest` `` と出ます。`--digest` なしの出力は
これまでと同じです。`--next --digest` の `next:` の行には `--digest` も付くので、続きも同じ形で読めます。

`task show <番号> --digest` は、同じ形の要点を Issue の最新のレポートと replanner のコメントから作ります(こちらは
GitHub を読みます)。要点のない古いイベントや、あとから確かめたいときに使います。replanner のコメントは、
最新のレポートと同じ Blocked の理由のものだけを使います。

### 通知(LLM なし)

task-hub は出来事を書くその場で、同じ内容を通知として出します。文面はイベントとその要点(digest)から組み立てる
だけで、LLM も GitHub も使いません。知らせを受けるために `/chief` を開いておく必要はありません。

- 見出し: `#<番号> <出来事>: <タイトル>`(例: `#41 In review: 保存できる項目に…`)
- 本文: 要点を `verdict: pass`、`reason: ...`、`review: ...`、`decision: human`、`question: ...` のように 1 行ずつ。
  最後の行が PR の URL(あれば)
- 出し方: herdr が動いていれば `herdr notification show`(Blocked と replan は `--sound request`、ほかは
  `--sound done`)。herdr がなければ macOS の通知(`osascript` の `display notification`)。どちらもなければ出しません

通知はイベントを書いたプロセス(実行中の `task _run`、`task watch`、`task`、`task start` など)がそのまま出します。
見張り役のプロセスを別に動かす必要はなく、`task watch` を止めていても、実行が終わった瞬間に届きます。通知のコマンドは
待たずに切り離して起動するので、通知が出せない、失敗する、止まったままになる、のどれでも task-hub の処理は
そのまま続きます(その通知は出ないだけです)。

どの出来事で通知するかは `~/.config/task-hub/config.ini` の `[notify]` で変えられます:

```ini
[notify]
events = In review, Blocked, replan, Done   ; 既定。列の名前か replan をカンマ区切りで。空にすると通知しない
```

通知は、このマシンで task-hub が書いた出来事だけです(events.jsonl と同じ)。macOS で通知が見えないときは、
システム設定の「通知」で、herdr または「スクリプトエディタ」(osascript の通知はこの名前で出ます)が許可されて
いるか確かめます。

## 実行の結果を集計する

`task stats` は、このマシンで終わった実行を集計します(0.6 から記録しています)。列ごとの件数、エージェントごとの
件数と所要時間の中央値、自動レビューの最初の判定と差し戻しで直った数、Blocked の理由、replanner の判定、
PR の大きさ(ベースから分かれた時点からの変更行数の中央値と、大きい順の 3 件)、エージェントの使用量(下記)です。10〜15 分でレビューできる
数百行を大きく超えるタスクが続くなら、分け方を見直す合図です(基準は `/task` と `/chief` のスキルにあります)。
Blocked の理由は次のどれかです。

| 理由 | 意味 |
|---|---|
| `agent` | エージェント自身が `## Blocked` を書いた |
| `review` | 自動レビューが通らなかった(`blocked`、判定なし、差し戻し後も `needs changes` など) |
| `no report` | エージェントがレポートを書かずに終わった |
| `no changes` | レポートはあるが、ファイルを変えなかった |
| `start` | 開始できなかった(Target repo、Base branch、`[env]` など) |
| `setup` | `[setup]` の準備が失敗した、または git が無視しないファイルを残した |
| `finish error` | 終了処理(push、PR、GitHub への書き込み)が失敗した |

### エージェントの使用量

実行の記録の `usage` は、エージェントを起動するたびに 1 件です(`role` は `agent` / `agent retry after review` /
`reviewer` / `replanner`)。`agent`(エージェント名)と `seconds` は必ず入り、エージェントの CLI の記録を読めたときだけ
`calls`(API 呼び出しの数。サブエージェントの分を含む)、`input`、`cache_creation`、`cache_read`、`output`(トークン数)、
`subagent_calls`、`models` が入ります。今読めるのは Claude Code の記録(`~/.claude/projects`)だけで、ほかのエージェントでは
トークンの欄がありません。読めたときは、ログ(herdr のタブと `task log`)にも起動ごとに 1 行出ます:

```
== agent used 42 calls, 1.2M tokens (18k out), 3 subagent calls, models claude-opus-5-5
```

`task stats` の `tokens:` の行は、使用量を測れた実行の数と、1 実行あたりのトークン数(input、cache_creation、
cache_read、output の合計)と呼び出し数の中央値です。測れなかった実行(記録を始める前のもの、Claude Code 以外)の数も
出します。`roles` は役割ごとの起動回数、測れた回数、秒数とトークン数の中央値、`heaviest` はトークン数の多い 3 実行です。
起動の間にその worktree で動いた Claude Code の呼び出しは、すべてその起動の分として数えます(エージェント自身が
起動したものも、あなたが同じ worktree で `claude` を開いたものも)。上限や警告はまだありません。どこに線を引くかは、
この数字を見て決めます。

1 行が 1 回の実行の JSON なので、細かく見たいときは `metrics.jsonl` をそのまま読めます。replanner の自動で Ready に
戻す段階に進むか、reviewer をどのエージェントにするかは、この数字を見て決めます。

## 保存場所

| 内容 | 場所 |
|---|---|
| タスク(ボード) | GitHub: Issue リポジトリと Project(非公開) |
| 設定 | `~/.config/task-hub/config.ini` |
| 実行中の情報 | `~/.local/state/task-hub/runs/<番号>.json`(このマシンだけ) |
| ログ | `~/.local/state/task-hub/logs/<番号>.log` |
| 実行ごとの記録(`task stats` が集計) | `~/.local/state/task-hub/metrics.jsonl` |
| リポジトリのクローン | `~/.local/share/task-hub/repos/<owner>/<name>` |
| worktree | `~/.local/share/task-hub/worktrees/<番号>` |
| プロンプト | `~/.local/share/task-hub/prompts/<番号>.md` |

## カードが Blocked になった

理由は Issue の最新の task-hub コメント(`task show <番号>` でも見られます)に書かれています。よくある理由:

| 理由 | 対処 |
|---|---|
| エージェント自身が書いた行(`## Blocked` から) | 求められたものを与えます。Issue の本文に答えを書き足すか、環境を修正します |
| `agent exited without a report (exit N)` | `task log <番号>` を読みます。多くの場合、エージェントがクラッシュした、ログインしていない、または予算を使い切ったのが原因です |
| `agent wrote a report but changed no files` | エージェントはやることがないと判断しました。Goal を明確にします |
| `the run stopped unexpectedly` | `task _run` プロセスが停止しました(たとえば herdr のペインを閉じた、Mac が再起動した) |
| `no run of this task on this machine` | カードが手で In progress に移されましたが、このマシンでは何も動いていません。Ready に移してください |
| `could not start: ...` | クローン、worktree の準備、カードの Target repo や Agent に問題があります。`gh auth status` とカードの欄を確認します |
| `could not start: branch X is not on GitHub ...` | Base branch が GitHub にありません(push していない、マージ後に削除された)。push してから Ready に戻します。別のブランチに変えたいときは、欄を書き換えます(すでに `task/<番号>` を push していたら次の行のとおり) |
| `could not start: Base branch was changed after the first run ...` | 前の実行が `task/<番号>` を GitHub に push した後で Base branch を書き換えました。そのブランチと PR は前のベースから作られているので続けられません。欄を元に戻すか、PR を閉じてブランチ `task/<番号>` を GitHub で削除してから Ready に戻します(新しいベースから作り直します) |

その後、カードを Ready に戻します(または `task start <番号>`)。再実行は同じブランチと PR で作業を続け、
エージェントには前回の実行が止まった理由が伝えられます。

## 作ったばかりのタスクが `task N not found on the board` になる

GitHub の Project の一覧への反映が遅れています。カードそのものは Project に載っています。まれに 20 分以上
遅れたことがありました。ブラウザで Project を開き、そのカードを別の列に動かす(Ready に移すなど)と、すぐに
一覧に出ました。

GitHub の障害で起きることがあります。ステータスページ([githubstatus.com](https://www.githubstatus.com/))を
確認してください。2026-09-23 には「Users may experience stale Project search results」という障害が出ていて、
その間は新しく追加したカードが何時間も一覧に出ませんでした。この場合は、GitHub の復旧を待ちます。

## `queue: N Ready task(s) waiting, all 5 slots busy`

正常な状態です。実行中のタスクが終わると、次の確認(`task watch` なら 1 分以内)で開始されます。

## `error: GraphQL: API rate limit exceeded`

GitHub Projects は GraphQL API だけで操作でき、GraphQL には 1 時間あたり 5000 ポイントの利用上限があります
(アカウント全体で共有)。task-hub は必要な欄だけを取るので、`task` 1 回は約 4 ポイント、`task watch` は 1 時間で
約 60 ポイントです。上限に届くのは、ほかのツールやエージェントが重い呼び出しを繰り返しているときです。たとえば
`gh project item-list` と `gh project field-list` は 1 回で 101 ポイント使います。上限に届いても `task watch` は止まらず、
エラーを表示して次の確認を続けます。上限は区切りの時刻に回復します。残りと回復の時刻は次で分かります
(`gh api rate_limit` は上限中でも「残り 5000」と表示することがあり、当てになりません):

```
gh api graphql -f query='{rateLimit{used remaining resetAt}}'
```

## その他の GitHub のエラー

`gh` が GitHub を読み取れませんでした(ログインしていない、アクセス権がない、リポジトリ名が変わった)。
カードはそのまま保たれます。`gh auth status` を実行してください。

## `the Project is missing: ...` / `the board is not configured`

Project の欄や選択肢、または設定ファイルが足りていません。[setup.md](setup.md) の「GitHub 側の準備」を見て、
表示された名前のものを追加してください。

## PR をマージせずに閉じた

task-hub はカードを動かしません(Base branch のないカードの PR は確認していないため。Base branch のあるカードも、
確認するのはマージされたかどうかだけです)。
やり直すならカードを Ready に戻し、やめるなら Issue を閉じてください。

## 実行中のタスクを止める

herdr のそのタスクのタブでエージェントを停止します(Ctrl-C)。ランナーは最後まで処理を行い、変更された内容を
push してカードを Blocked にします。または、ペインを閉じます。その場合、次の確認で `the run stopped unexpectedly`
として Blocked になります。

## タスクを取り消す

Issue を閉じるか、`task done <番号>` を実行します。そのタスクの herdr のタブ(またはタスク専用の workspace)を閉じ、worktree を削除し、
カードを Done にします。task-hub の clone の中のブランチ `task/<番号>` も消しますが、GitHub のブランチと PR は残ります。
必要であれば、GitHub 上で PR をクローズしてください。

## 同時実行数の上限を変更する

`bin/task` の先頭にある `MAX_PARALLEL` を変更します。

## ディスクの整理

worktree と、clone の中のブランチ `task/<番号>` は、タスクが完了すると削除されます。消せなかったときは
`cleanup: task <番号>: ...; trying again at the next check` と表示し、次の確認でやり直します(0.6 より前に完了したタスクの
ブランチは残っていることがあります。`git -C ~/.local/share/task-hub/repos/<owner>/<name> branch --list 'task/*'` で
確かめ、完了済みのものは `git branch -D` で消せます)。`~/.local/share/task-hub/repos/` 内のクローンは次の実行を
速くするために残されており、いつでも削除できます。
