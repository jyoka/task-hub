# Issue、レポートファイル、コメント、PR の形式

## タスク = Issue + Project のカード

各タスクは、非公開の Issue リポジトリ(設定の `[board] issues`、例: `jyoka/tasks`)の Issue 1 件です。
タスクの番号は Issue の番号です。Issue は GitHub Project にカードとして載っています。

| どこに | 何を | 書くのは |
|---|---|---|
| Issue のタイトル | 命令形の短い要約。PR のタイトルにもなります | あなた(`/task` / `task new`) |
| Issue の本文 | Goal: やること、理由、チャットで決まった文脈、確認項目のチェックリスト。エージェントへの指示のすべてです | あなた |
| カードの Status | Backlog / Ready / In progress / In review / wait for merge(任意) / Blocked / Done | あなた(Backlog と Ready と wait for merge) / task-hub(それ以外) |
| カードの Target repo | 作業先の GitHub リポジトリ `owner/name` | あなた |
| カードの Agent | このタスクのエージェント。空欄 = そのマシンのデフォルト([agents.md](agents.md)) | あなた |
| カードの Base branch | 作業を始めるブランチ(例: `feat/search`)。PR もこのブランチに向けて出ます。空欄 = リポジトリのデフォルトブランチ。GitHub に push 済みである必要があります | あなた(`/task` / `task new --base`) |
| Issue のコメント | task-hub のレポート(下記) | task-hub |

Goal(Issue の本文)は GitHub 上でいつでも編集できます。ブロックされたタスクに答えるときも、本文に書き足してから
カードを Ready に戻します。

実行中の情報(ブランチ、プロセス、herdr のワークスペース、worktree、ログ)は手元のマシンの
`~/.local/state/task-hub/runs/<番号>.json` にだけ保存され、GitHub には載りません。

## エージェントのレポートファイル

毎回の実行の最後に、エージェントは worktree のルートに `.task-report.md` を書き込みます
(書き方は [worker/PROMPT.md](../worker/PROMPT.md) で指示しています)。task-hub はこれを読み取ってから削除し、
コミットすることはありません。

```markdown
## Blocked                 <- only when stuck; everything else still gets written

Need the Stripe test key.

## Report

What changed, how it was verified, what was not done.

## Please review

Exact files, decisions, and risks to check.
```

## task-hub のレポートコメント

実行が終わるたびに、task-hub は Issue に 1 件コメントします。先頭の `<!-- task-hub report -->` が目印で、
いちばん新しいものがそのタスクの現在のレポートです。再実行のときはこれがエージェントに伝えられます。

```markdown
<!-- task-hub report -->

## Blocked

Need the Stripe test key.

## Report

...

## Please review

...

PR: https://github.com/jyoka/app/pull/41
```

task-hub 自身が止めたとき(実行が止まった、開始できなかった)も、
同じ形式で `## Blocked` だけのコメントを書きます。

## replanner のコメント

`[runner] replanner` を設定すると、エージェント自身の Blocked で止まった実行のあとに、task-hub が次の形で
コメントします([agents.md](agents.md#blocked-の仕分けreplanner))。`Blocked:` と `Decision:` の行は、回数の上限と
同じ理由の検出に使います。

```markdown
<!-- task-hub replan -->

## Replanner

Blocked: Need the Stripe test key.
Decision: answered

### Answer
...
### Evidence
- README.md:12: `STRIPE_KEY is in 1Password "dev"`
```

最新の `answered` のコメントは、次の実行のプロンプトに「Replanner notes」として入ります。

## 実行終了時の処理

task-hub は worktree の中で git が無視しないファイルをすべてコミットします。`.task-report.md`、`.task-review.md`、
Python の `__pycache__/` と `*.pyc`、設定の `[env]` でコピーしたファイルは、リポジトリに `.gitignore` がなくてもコミットしません(clone の `.git/info/exclude` に
書きます。すでに追跡されているファイルには影響しません)。

`[runner] reviewer` が設定されている場合、task-hub は PR を作る前に reviewer を実行します。reviewer が
`needs changes` と判定したら、実装エージェントに 1 回だけ自動で差し戻します。2 回目も通らない場合は Blocked になります。

| エージェントの結果 | task-hub の処理 | カードの列 |
|---|---|---|
| レポートあり、ファイル変更あり、レビュー通過または reviewer なし | コミットし、`task/<番号>` を push し、レビュー可能な PR を作成、レポートをコメント | In review |
| reviewer が 2 回目も `needs changes`、または `blocked`、判定なし、ファイルを変更した(変更は取り消します) | 現状をコミットして push し、理由を付けた**ドラフト** PR を作成、レビュー結果をコメント | Blocked |
| `## Blocked` を含むレポート | 現状をコミットして push し、理由を付けた**ドラフト** PR を作成、レポートをコメント | Blocked |
| レポートなし、ファイル変更あり | push し、ドラフト PR を作成("agent exited without a report") | Blocked |
| レポートなし、変更なし(クラッシュ) | push せず、PR も作成しない。理由をコメント | Blocked |
| レポートあり、変更なし | push せず、PR も作成しない。レポートをコメント | Blocked |

再実行(Blocked のカードを Ready に戻す、または `task start`)は同じブランチで作業を続け、同じ PR を更新します。
最新の実行で使われたプロンプトそのものは `~/.local/share/task-hub/prompts/<番号>.md` に保存されます。

## PR

- ブランチは `task/<番号>`、ベースはカードの Base branch(空欄ならリポジトリのデフォルトブランチ)、タイトルは Issue のタイトル
- 説明: `## Blocked`(ある場合)、`## Report`、`## Please review`、`Closes <issues repo>#<番号>`、エージェント名のフッター
- マージされると `Closes` によって Issue が閉じ、Project のワークフロー(Item closed)でカードが Done に移ります。
  次の確認で task-hub はカードが開いた列から消えたことに気づき、worktree と herdr のワークスペースを削除します
- Base branch 向けの PR について、GitHub のドキュメントは「`Closes` はデフォルトブランチへのマージのときだけ効く」と
  しています(実際には閉じた例もありますが、保証がありません)。そのため task-hub が In review と wait for merge のカードの PR を確認し、マージされていれば Issue を閉じてカードを Done にし、
  worktree と herdr のワークスペースを削除します。この確認は GraphQL とは別枠の REST API で行います。
  そのタスクを別のマシンで実行した場合も、ブランチ `task/<番号>` から PR を探して確認します
- Base branch が GitHub にない(手元にしかない、マージ後に削除された)場合は、実行のたびに開始前に確かめて開始せず、
  「push してから Ready に戻してください」とコメントして Blocked にします
- 前の実行が `task/<番号>` を push した後で Base branch を書き換えた(空欄にした場合を含む)カードは再実行せず、
  理由をコメントして Blocked にします。ブランチと PR は前のベースから作られているためです。まだ何も push して
  いなければ(エージェントが何も変えずに止まった場合など)、新しいベースから作り直します
- マージせずに PR を閉じた場合、task-hub はカードを動かしません。Ready に戻すか、Issue を閉じてください
