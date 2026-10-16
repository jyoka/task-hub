# Issue、レポートファイル、コメント、PR の形式

## タスク = Issue + Project のカード

各タスクは、非公開の Issue リポジトリ(設定の `[board] issues`、例: `jyoka/tasks`)の Issue 1 件です。
タスクの番号は Issue の番号です。Issue は GitHub Project にカードとして載っています。

| どこに | 何を | 書くのは |
|---|---|---|
| Issue のタイトル | 命令形の短い要約。PR のタイトルにもなります | あなた(`/task` / `task new`) |
| Issue の本文 | Goal: やること、理由、チャットで決まった文脈、確認項目のチェックリスト。エージェントへの指示のすべてです | あなた |
| Issue の「Blocked by」 | このタスクより先に終わっているべきタスク。GitHub の Issue の依存関係(リレーションシップ)です | あなた(`task new --blocked-by` / GitHub の画面) |
| カードの Status | Backlog / Ready / In progress / In review / wait for merge(任意) / Blocked / Done | あなた(Backlog と Ready と wait for merge) / task-hub(それ以外) |
| カードの Target repo | 作業先の GitHub リポジトリ `owner/name` | あなた |
| カードの Agent | このタスクのエージェント。空欄 = そのマシンのデフォルト([agents.md](agents.md)) | あなた |
| カードの Base branch | 作業を始めるブランチ(例: `feat/search`)。PR もこのブランチに向けて出ます。空欄 = リポジトリのデフォルトブランチ。GitHub に push 済みである必要があります | あなた(`/task` / `task new --base`) |
| Issue のコメント | task-hub のレポート(下記)。人のコメントは、再実行のときにエージェントへの追加の指示として渡ります(下記) | task-hub / あなた |

### 開始の条件: Blocked by と Ready conditions

- **Blocked by**: task-hub は、Ready のカードでも、Blocked by の Issue がすべて終わるまでは始めません(実行の枠も
  使いません)。終わったとは、完了として閉じられたこと(PR のマージ、`task done`)です。「not planned」や
  「duplicate」として閉じられた場合は、前提が届いていないので待ち続けます。不要ならリンクを外してください。
  待っているカードは `task` と `task list` の `waits_for` に、何を待っているか(例: `#12 (Blocked)`)が出ます。
- **本文にだけ書かれた前後関係**: `task new` を通さずに作った Issue(`gh issue create` やほかのスキル)は、本文の
  `Blocked by` や `Ready conditions` の見出しの下に `#12` と書いてあっても、リンクがありません。task-hub は、
  そこに書かれた番号がボード上の開いたカードなら、リンクと同じように開始を待たせ、`waits_for` に
  `#12 (In review, only in the body: link it)` と出します。本文は開始を止めるためだけに読み、開始の許可には
  使いません。Issue の画面の Relationships から「Blocked by」を付ければ、この表示は消えます。
- **Ready conditions**: Goal の `### Ready conditions` の見出しに、それ以外の開始の条件を書きます。依存するタスクと
  そこから使うもの、決まっているべきこと、`.env` のキーなどです。コードは判定しません。エージェントが最初に確かめ、
  満たされていなければ何も変えずに Blocked で止まります。`/chief` は、待ち先が Done になったときにこれを読んで、
  開始してよいか提案します。

```markdown
### Ready conditions

- #12 が終わっていること(#12 で追加する `User` 型を使う)
- 決済のテスト用キーが `.env` にあること
```

Goal(Issue の本文)は GitHub 上でいつでも編集できます。ブロックされたタスクに答えるときも、本文に書き足してから
カードを Ready に戻します。Issue や PR にコメントで書いてもかまいません([人のコメント](#人のコメント))。

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

- Learning route:          <- always the last item; one per report
  - Question: ...
  - Entry point: ...
  - Search: ...
  - Trace: ...
  - Check: ...
  - Explain yourself: ...
```

Please review の最後の項目は、人がコードを自分で探して理解するための学習ルート(Learning route)です。
変えた中でいちばん大事な動きについて、次の 6 行を 1 つの項目の下に字下げして書きます。

| 行 | 中身 |
|---|---|
| Question | 人が調べること |
| Entry point | 読みはじめる実在のファイルと関数 |
| Search | エージェントがこの実行で動かし、役に立つ一致を確かめた読み取りだけの `rg` コマンド。`rg` がなければそう書き、代わりに動かした `git grep` などを書く |
| Trace | 動きの流れを読む順に、関数やファイルを最大 3 つ |
| Check | 関係するテストと、それで分かること。動かしたのか、勧めるだけなのかを分ける |
| Explain yourself | 人が自分で答える質問を 1 つ。答えは書かない |

当てはまらない行(research タスク、ドキュメントだけの変更、テストがない)は `n/a` と理由を書き、実際にある根拠
(文書の節、出典)を示します。学習ルートは確認すべきリスクや判断の代わりではなく、その後ろに足すものです。
見出しは増やさないので、task-hub の読み取りと、PR や Issue への転記はこれまでと同じです。ルートが 1 つの項目
なので、digest の `review`([operations.md](operations.md#判断用の要点digest))にはリスクの項目が先に出ます。

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

## 人のコメント

再実行(Blocked や In review のカードを Ready に戻す、`task start`)のとき、task-hub は前回の実行より後に人が書いた
次のコメントを、プロンプトの最後に「Comments since the earlier run」として古い順に入れます。

| どこの | 何を | 添えるもの |
|---|---|---|
| Issue | コメント | 書いた人、日時 |
| タスクの PR | 会話のコメント | 書いた人、日時 |
| タスクの PR | レビューの本文(送信済みのものだけ。本文が空のレビューは除く) | 判定(`changes requested` など)、書いた人、日時 |
| タスクの PR | 行へのコメント | ファイルと行(`lines 10-12` のような範囲、行が変わったあとは前の版の行と `outdated`)、書いた人、日時 |

- 「前回の実行」は、このマシンでの前回の開始の時刻(`runs/<番号>.json` の `started`)です。記録がなければ(別のマシンで
  実行した)、Issue の最後のレポートのコメントの時刻です。どちらもなければ(初めての実行)コメントは渡しません。
  タスクの PR は、手元の記録の PR だけを見ます
- task-hub 自身のコメント(`<!-- task-hub` で始まるもの: レポート、仕分け、つなぎ先)と bot のコメント(GitHub の
  ユーザーの種類が Bot、または名前が `[bot]` で終わる)は入れません
- エージェントは、コメントを Goal への追加の指示として扱い、レポートの Report の中に `Comments:` で始まる箇条書きで、
  コメントごとに何をしたか、しなかったならその理由を書きます([worker/PROMPT.md](../worker/PROMPT.md) の最後の部分)
- reviewer にも同じコメントが Goal のすぐ後に渡り、受け入れ条件と同じように 1 つずつ確かめます
  ([worker/REVIEW.md](../worker/REVIEW.md) の最後の部分)。渡したコメントは `~/.local/share/task-hub/prompts/<番号>-comments.md`
  に残ります
- 渡すコメントがなければ、プロンプトは今までと同じです(指示書の最後の部分も入りません)
- コメントはどこにも写さず、Goal も書き換えません
- 読むのは REST API で、再実行のたびに Issue のコメント 1 回、PR があれば会話のコメント、レビュー、行へのコメントの
  3 回です。コメントは前回の実行より後に変わったものの、レビューは全部の、それぞれ最初の 100 件までを見ます

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
| レポートあり、変更なし | push せず、PR も作成しない。レポートをコメント | Blocked(`research` ラベルのタスクは In review) |

再実行(Blocked のカードを Ready に戻す、または `task start`)は同じブランチで作業を続け、同じ PR を更新します。
最新の実行で使われたプロンプトそのものは `~/.local/share/task-hub/prompts/<番号>.md` に保存されます。

## PR

- ブランチは `task/<番号>`、ベースはカードの Base branch(空欄ならリポジトリのデフォルトブランチ)、タイトルは Issue のタイトル
- 説明: `## Blocked`(ある場合)、`## Report`、`## Please review`、`Closes <issues repo>#<番号>`、エージェント名のフッター
- マージされると `Closes` によって Issue が閉じ、Project のワークフロー(Item closed)でカードが Done に移ります。
  次の確認で task-hub はカードが開いた列から消えたことに気づき、worktree と herdr のワークスペースを削除します
- GitHub のドキュメントは「`Closes` はデフォルトブランチへのマージのときだけ効く」としています。デフォルトブランチへの
  マージでも閉じなかったことがあります(jyoka/tasks#81)。そのため task-hub が In review と wait for merge のカードすべての
  PR を確認し、マージされていれば Issue を閉じてカードを Done にし、
  worktree と herdr のワークスペースを削除します。この確認は GraphQL とは別枠の REST API で行います。
  そのタスクを別のマシンで実行した場合や、変更なしで終わった実行のあとに人が PR を作った場合も、ブランチ `task/<番号>`
  から PR を探して確認します。そのときは、いちばん新しい PR
  の本文に `Closes <issues repo>#<番号>` があり、手元の最後の実行より後にマージされたときだけ Done にします
- Base branch が GitHub にない(手元にしかない、マージ後に削除された)場合は、実行のたびに開始前に確かめて開始せず、
  「push してから Ready に戻してください」とコメントして Blocked にします
- 前の実行が `task/<番号>` を push した後で Base branch を書き換えた(空欄にした場合を含む)カードは再実行せず、
  理由をコメントして Blocked にします。ブランチと PR は前のベースから作られているためです。まだ何も push して
  いなければ(エージェントが何も変えずに止まった場合など)、新しいベースから作り直します
- マージせずに PR を閉じた場合、task-hub はカードを動かしません。Ready に戻すか、Issue を閉じてください
