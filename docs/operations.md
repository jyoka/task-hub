# 運用とトラブルシューティング

全体は GitHub Project のボードで見ます。手元では `task` を実行します。ボードと実行中のタスクと PR を確認し、
空きがあれば Ready のカードを開始し、あなたの対応が必要なタスクの数を表示します。herdr のペインで `task watch` を
動かしておけば、これを 1 分ごとに自動で行います。

## 実行の様子を見る

- **herdr**: 各実行には、サイドバーに "task <番号>: <title>" という名前のワークスペースがあります。開くと
  エージェントの出力をリアルタイムで確認できます。実行が終わっても、ペインは最終ステータス行を表示したまま
  開いています。PR のマージ(または `task done <番号>`)で閉じます。
- **herdr なしの場合**: `task log <番号>` で最後の 40 行を、`task log <番号> --full` ですべてを表示します。
- エージェントに伝えた内容: `~/.local/share/task-hub/prompts/<番号>.md`。

## 実行の結果を集計する

`task stats` は、このマシンで終わった実行を集計します(0.6 から記録しています)。列ごとの件数、エージェントごとの
件数と所要時間の中央値、自動レビューの最初の判定と差し戻しで直った数、Blocked の理由、replanner の判定です。
Blocked の理由は次のどれかです。

| 理由 | 意味 |
|---|---|
| `agent` | エージェント自身が `## Blocked` を書いた |
| `review` | 自動レビューが通らなかった(`blocked`、判定なし、差し戻し後も `needs changes` など) |
| `no report` | エージェントがレポートを書かずに終わった |
| `no changes` | レポートはあるが、ファイルを変えなかった |
| `start` | 開始できなかった(Target repo、Base branch、`[env]` など) |
| `finish error` | 終了処理(push、PR、GitHub への書き込み)が失敗した |

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

## `queue: N Ready task(s) waiting, all 3 slots busy`

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

herdr のワークスペースでエージェントを停止します(Ctrl-C)。ランナーは最後まで処理を行い、変更された内容を
push してカードを Blocked にします。または、ペインを閉じます。その場合、次の確認で `the run stopped unexpectedly`
として Blocked になります。

## タスクを取り消す

Issue を閉じるか、`task done <番号>` を実行します。そのタスクの herdr のワークスペースを閉じ、worktree を削除し、
カードを Done にします。ブランチと PR は GitHub に残ります。必要であれば、GitHub 上で PR をクローズしてください。

## 同時実行数の上限を変更する

`bin/task` の先頭にある `MAX_PARALLEL` を変更します。

## ディスクの整理

worktree はタスクが完了すると削除されます。`~/.local/share/task-hub/repos/` 内のクローンは次の実行を速くするために
残されており、いつでも削除できます。
