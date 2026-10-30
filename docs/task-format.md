# Issue、レポートファイル、コメント、PR の形式

## タスク = Issue + Project のカード

各タスクは、非公開の Issue リポジトリ(設定の `[board] issues`、例: `you/tasks`)の Issue 1 件です。
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
| カードの Readiness | `task check` の判定 `GO` / `NO-GO`(任意。初めての `task check` が作ります。[下記](#ready-の前の確かめtask-check)) | task-hub |
| カードの Review | 最後の実行の自動レビューの判定 `pass` / `needs changes` / `blocked`(任意。初めてのレビューが作ります。[下記](#判定の残し方review-欄と機械が読む-1-行)) | task-hub |
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

### Rules: タスクごとの決まり

Goal に `Rules` の見出し(`##` でも `###` でも)を書くと、そのタスクでエージェントにしてよいこと、承認が要ること、
してはいけないことを決められます。1 行に 1 つの段階と、カンマ区切りの規則を書きます。

```markdown
### Rules

- can: Bash(npm test *), Bash(npm run lint)
- ask: Bash(npm publish *)
- never: WebFetch, Read(~/.ssh/**), Bash(curl *)
```

| 行 | Claude Code の設定 | 意味 |
|---|---|---|
| `can:` | `permissions.allow` | 聞かずにしてよい |
| `ask:` | `permissions.ask` | 人の承認が要る。誰も答えない実行では断られ、エージェントは Blocked で承認を求める |
| `never:` | `permissions.deny` | してはいけない。`--dangerously-skip-permissions` でも効く |

- 規則の書き方は Claude Code の権限の規則そのままです(`Bash(...)`、`Read(...)`、`WebFetch(domain:...)`、`mcp__...`)
- task-hub は開始のたびに worktree の `.claude/settings.local.json` に書きます。リポジトリの `.claude/settings.json` と
  合わさり、deny はどこに書いたものも優先します。このファイルはコミットしません
- Rules を Goal から消すと、次の実行で task-hub が書いたファイルも消します
- `can` / `ask` / `never` 以外の語で始まる `語:` の行があると、エージェントを起動せずに Blocked にします。
  語のない文章の行は、そのままエージェントへの指示として読まれます
- リポジトリが `.claude/settings.local.json` をコミットしているときは、上書きせずに Blocked にします
- Claude Code 以外のエージェントには、Goal の一部として文章で届きます。コードで止めるのは Claude Code だけです
- 承認するときは、その規則を `ask:` から `can:` に移して、カードを Ready に戻します

### Budget: 予算と有料 API

Goal に `Budget` の見出し(`##` でも `###` でも)を書くと、その実行の予算と、使う有料 API を決められます。
見出しは `Budget` か `予算` だけにします。後ろに付けてよいのは `:` と括弧書き(`## Budget (予算)`)だけです。
`Budget` か `予算` で始まるほかの見出し(`## Budget and limits`、`## 予算と上限` など)は、開始の前に Blocked にします。
見出しの下の行を黙って読み飛ばさないためです。

```markdown
### Budget

- 2h, 3M tokens, $5, 30 credits
- paid api: openai
```

| 行 | 意味 |
|---|---|
| 予算の行 | カンマ(`,` か `、`)区切りで、時間(`2h`、`90m`。分の `m` は小文字だけで、`M` は百万)、トークン(`3M tokens`、`500k tokens`)、費用(`$5`、USD)、クレジット(`30 credits`)。書いたものだけが、いつもの予算の代わりになる |
| `paid api:` | 実行の中で使う有料 API の名前(カンマ区切り)。エージェントを起動する前に、`[balance]` のその名前のコマンドで残高を確かめる。`有料 API: openai`、`**paid api**:`、`paid apis:` のように、日本語、太字、複数形で書いてもよい |

- 予算を超えると、出来事 `over budget` を出して通知します。今は知らせるだけで、実行は止めません
  ([operations.md](operations.md#予算と残高))
- 時間とトークンと費用は、エージェントの起動ごとの記録(`metrics.jsonl` の `usage`)を足したものです。
  トークンは Claude Code と pi、費用は pi、クレジットは Kiro の記録にだけあります
- 残高が足りないと、エージェントを起動せずに、理由をつけて Blocked にします。残高を足してから Ready に戻します
- `paid api:` の名前の `[balance]` のコマンドがないと、開始の前に Blocked にします。確かめられないまま始めないためです
- `paid api` か `有料 API` を含むのに `paid api: 名前` の形で読めない行(`paid api openai`、`有料 API は openai`、
  `the paid API of openai` など)は、開始の前に Blocked にします。読み飛ばすと、残高を確かめずにエージェントが始まるためです。
  同じ理由で、`Budget` の見出しの外にある `paid api:` の行も Blocked にします
- 予算の行に読めない項目(`3M tokns`、`2 hrs`、`3M` など)があると、開始の前に Blocked にします。予算の項目も
  `paid api:` もない文章の行は、そのままエージェントへの指示として読まれます。ただし、次の行は予算の書き間違いとみなします
  - 数字か `$` で始まる英数字だけの行
  - 数字と単位を含む行(`tokens: 3M`、`2h まで`、`Cost: $5`、`500円まで`、`300万トークン`、`時間: 2h` など)。予算は上の形でだけ書けます
- コードブロックの中は読みません
- 費用はエージェント自身の分です。テストの中で有料 API を呼ぶ費用(評価の台帳など)は、ここでは数えません

### Autopilot: off

`[autopilot]`([autopilot.md](autopilot.md))に書いたリポジトリのカードでも、Goal に `Autopilot: off` の行があれば、
task-hub は Ready に移さず、PR もマージキューに入れません。引き継ぎのメモ、PRD、人がする手順のカードに書きます。
箇条書き(`- Autopilot: off`)、強調(`**Autopilot: off**`)、終わりの句点でも効きます。

Goal(Issue の本文)は GitHub 上でいつでも編集できます。ブロックされたタスクに答えるときも、本文に書き足してから
カードを Ready に戻します。Issue や PR にコメントで書いてもかまいません([人のコメント](#人のコメント))。

実行中の情報(ブランチ、プロセス、herdr のワークスペース、worktree、ログ)は手元のマシンの
`~/.local/state/task-hub/runs/<番号>.json` にだけ保存され、GitHub には載りません。

## Ready の前の確かめ(task check)

`task check <番号>` は、カードを Ready に移す前に、Goal だけで実装に取りかかれるかを GO / NO-GO で判定します。
Elephant-Goldfish Model([EGM](https://egm.dev/))の Goldfish の考え方です。Goal を書いた側(あなたや `/chief`)は
会話の文脈を持っているので、Goal の抜けに気づきにくい。そこで、文脈を持たないエージェントに Goal を読ませます。

```
task check 12                 # Backlog か Ready のカード。判定を Issue と Project に書く
task check 12 --no-write      # どの列のカードでも。判定を表示するだけで、何も書かない
task check 12 --no-write --ref 1a2b3c4 --goal-file goal.md
                              # 試すとき: 過去のカードを、変更の前のコミットと、編集される前の Goal で
```

### Goldfish に渡すもの

Goldfish に渡すのは、カードのタイトル、Goal(Issue の本文)、作業先リポジトリの base ブランチのコードだけです
(Base branch 欄のブランチ、空欄なら既定のブランチ。`--ref` ならそのコミット)。会話の履歴、過去のレポート、人のコメント、
ほかのカードは渡しません。指示は [worker/READINESS.md](../worker/READINESS.md) にあり、3 つの段に分かれます。
どの段も新しい文脈のエージェントで、1 体ずつ、そのコミットの worktree(`~/.local/share/task-hub/worktrees/<番号>-check-<役>`)
を自分用に持ちます。終わった worktree は消します。

| 段 | エージェント | すること |
|---|---|---|
| 1. Comprehension Check | 1 体 | Goal を自分の言葉で言い直し、2 通りに読める箇所を両方の読み方つきで挙げる |
| 2. 敵対的レビュー | 4 体を同時に | Design Critic(決まっていない設計)、Naive Reader(初めて読む人に通じない言葉や前提)、Codebase Auditor(Goal とコードの食い違い、Ready conditions、リポジトリの決まり)、Architect(関門に触れる変更と Architecture Brief の食い違い。[architecture-brief.md](architecture-brief.md#task-check-の-architect))。互いの結果は見ない |
| 3. Implementation Readiness | 1 体 | 1 と 2 の結果を Goal とコードで確かめ直し、まとめて GO / NO-GO を決める。NO-GO なら Goal に足す文言案を書く |

2 の視点は、READINESS.md の 3 つ目の部分の `## ` 見出しです。見出しを足すと、視点が増えます。
使うエージェントは `[runner] checker` です。空か `agent` なら、カードの Agent 欄(空ならそのマシンのデフォルト)です。
Goldfish はコードを読むだけで、ビルドやテストは動かしません。

Goldfish がファイルを変えたら(編集、追加して stage、コミット)、task-hub はその worktree を元に戻し、判定を `blocked`
にしてその段で止めます。結果のファイル `.task-readiness.md` を書かずに終わった場合も `blocked` です。

### 判定と指摘の分け方

指摘は、自動レビュー([下記](#自動レビューの差し戻し))と同じく 2 つに分けます。

| 種類 | 意味 |
|---|---|
| blocking | Goal とコードだけを渡されたエージェントが、違うものを作るか、止まって聞くか、終わりを判断できない。決まっていないこと、作るコードが変わる 2 通りの読み方、確かめられない受け入れ条件、Goal とコードや Goal 自身の食い違い、満たされていない Ready conditions |
| minor | 本物だが、注意深いエージェントなら意図どおりに作れる |

blocking が 1 つもなければ GO、あれば NO-GO です。エージェントが NO-GO と書いても blocking がなく minor だけなら GO、
GO と書いても blocking が残っていれば NO-GO として扱います。判定の語がなければ `blocked` です。

### Issue のコメントと Readiness 欄

判定は Issue のコメントに書きます。1 行目が印、2 行目が判定、3 行目が判定した Goal のハッシュです。task-hub はこの
2 行を読み戻します。

```markdown
<!-- task-hub readiness -->
Verdict: NO-GO
Goal: 3f2a9c0d41b7e865

## Readiness

Checked ... by 6 Goldfish (claude) that read only this Goal and owner/app at main (1a2b3c4d5e6f): 6 min, 1.2M tokens.

(Readiness エージェントの要約)

### Blocking

### Minor

### Suggested Goal additions      <- NO-GO のときだけ。blocking ごとに Goal に足す文言案

<details><summary>Comprehension Check</summary> ... </details>
```

- **Goal のハッシュ**: Issue の本文の SHA-256 の先頭 16 文字です(改行コードと前後の空白は除く)。Goal を 1 文字でも
  編集すると、それより前の判定は「古い判定」(`stale`)になります。GO も古くなります。
- **数えるコメント**: この GitHub アカウントが書いた、印のついたコメントのうち最新のものです。ほかの人が書いたコメントは、
  中身にかかわらず判定として扱いません。
- **Readiness 欄**: Project の単一選択フィールド `Readiness`(`GO` / `NO-GO`)に判定を入れます。欄がなければ、
  初めての `task check` が作ります。`blocked` のときは空にします。欄はボードで見るためのもので、開始の判断には
  コメントのハッシュを使います。
- `--no-write` のときは、コメントの全文を表示するだけで、コメントも欄も書きません。
- 判定ごとに、エージェントの起動ごとの秒数とトークン数を `~/.local/state/task-hub/checks.jsonl` に 1 行残します
  (`task stats` の `checks:` 行)。実行の記録 `metrics.jsonl` には入れません。そこは実行の数や「いつもの時間」を
  数えるところなので、判定が混ざると数字がずれます。判定 1 回で使った量が、そのエージェントの実行 1 回の予算を超えたら、
  `over budget` イベントを出します(理由の先頭が `task check:`)。
- 全体のログは `~/.local/state/task-hub/logs/<番号>-check.log` です。判定のあとに `readiness` イベントを書きます。

task-hub は、どの判定でもカードを動かしません。NO-GO のカードを Backlog に戻すか、Goal を直してもう一度確かめるかは、
人が決めます。

### 開始の門: [runner] readiness

この節が、開始の門の既定値と振る舞いの正式な定義です。ほかの文書はここを指し、コード(`READINESS_DEFAULT`、
`readiness_mode`)はここに合わせます([決定事項 39](design.md#決定事項))。既定は `warn` です。`[runner] readiness` を書かなければ
`warn` で動きます。今までどおり Issue を読み足したくないときは `readiness = off` と書きます。

```ini
[runner]
readiness = warn    ; off / warn(既定)/ require
checker =           ; task check のエージェント。空か agent = カードの Agent 欄
```

| 値 | Ready のカード | オートパイロット |
|---|---|---|
| `off` | 門を使わない。Issue を読みに行くこともない | 今までどおり |
| `warn`(既定) | 今の Goal への GO がなくても始める。そのとき `readiness` イベントを書き、`task` の出力に `readiness:` の行を出す。`task list` に `readiness` の列が付く | 今までどおり |
| `require` | 今の Goal への GO がなければ始めない。`waits_for` に理由(`readiness: its Goal changed since its last check (`task check 12`)` など)を出し、`task check` で GO になれば次の確認で始まる | GO のない Backlog のカードを Ready に移さない |

- 「今の Goal への GO」は、最新の判定コメントが GO で、そのハッシュが今の Goal のハッシュと同じことです。
- `task` と `task watch` は、カードの Goal かカード自体(Project の更新時刻)が変わったときだけ、Issue のコメントを読み直します
  (1 回の呼び出し)。読んだ結果は `~/.local/state/task-hub/readiness.json` に残します。`task list` は GitHub を読み足さず、
  このマシンが最後に読んだものを出します(まだ読んでいなければ `unknown`)。
- `task list` の `readiness` の列の値: `GO`、`NO-GO`、`blocked`、`stale`(前の Goal への判定)、`none`(確かめていない)、
  `research`、`unknown`。
- `require` では、Goal を書き足すたびに GO が古くなります。Blocked のカードに答えを Goal に書き足して Ready に戻すときも、
  `[triggers] ready` の繰り返しの目標のカードも、`task check` で GO を取るまで始まりません。答えをコメントで渡せば
  (Goal を編集しなければ)GO は古くなりません。
- **`--research` のカードは門の対象外**です(`research`)。調べものは、答えの見つけ方を決めるのも仕事のうちで、
  レポートが「分からなかったこと」を書く形になっています。実装の Readiness(作るものが 1 通りに決まるか、受け入れ条件で
  確かめられるか)の物差しが合いません。`task check` を手で動かすことはできます。

## エージェントのレポートファイル

毎回の実行の最後に、エージェントは worktree のルートに `.task-report.md` を書き込みます
(書き方は [worker/PROMPT.md](../worker/PROMPT.md) で指示しています)。task-hub はこれを読み取ってから削除し、
コミットすることはありません。

```markdown
## Blocked                 <- only when stuck; everything else still gets written

Need the Stripe test key.

## Report

### Summary                <- 3 to 5 bullets: what was done, the check's result, what to decide

- Added the save check for required fields.
- The tests pass.
- Decide whether an empty name is an error.

### Details                <- per-file changes, commands and results, what was not done

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

Report は、人が判断に要る結論を先に置くため、`### Summary`(要点)と `### Details`(詳細)の 2 つに分けます。

- 要点: 3〜5 行の箇条書き。何をしたか(結論)、確かめた結果を 1 行、人に判断してほしいことがあればその 1 行。
  コマンド、コミットのハッシュ、行番号は入れません
- 詳細: 変えたファイルごとの説明、実行したコマンドと結果、やっていないこと。人のコメントへの `Comments:` の
  箇条書き([人のコメント](#人のコメント))もここに書きます
- research タスクでは、要点に調べた結論(Goal の問いへの答え)を、詳細に調べたことと根拠を書きます
- `## Blocked` の 1 行も同じ考えで、人に求めること(決めてほしいこと、鍵、権限)とその理由だけを書き、
  試したことは Report の詳細に回します

区切りは `##` より下の `###` 見出しなので、task-hub が読み取る `##` の見出しは変わらず、PR の本文と Issue の
コメントにはどちらもそのまま載ります。research タスクの digest の `report`([operations.md](operations.md#判断用の要点digest))
と通知には、要点だけが出ます。

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

PR: https://github.com/you/app/pull/41
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
- エージェントは、コメントを Goal への追加の指示として扱い、レポートの Report の詳細(`### Details`)の中に `Comments:` で始まる箇条書きで、
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

task-hub は PR を作る前に reviewer を実行します(既定。`[runner] reviewer = off` なら実行しません)。reviewer が
`needs changes` と判定したら、実装エージェントに自動で差し戻します。流れは次の「自動レビューの差し戻し」にあります。

| エージェントの結果 | task-hub の処理 | カードの列 |
|---|---|---|
| レポートあり、ファイル変更あり、レビュー通過または reviewer なし | コミットし、`task/<番号>` を push し、レビュー可能な PR を作成、レポートをコメント | In review |
| reviewer の指摘が minor(`Known issues`)だけ | 通過と同じ。指摘は PR とコメントの「Known issues」に残す | In review |
| 差し戻しを止めたあとも `needs changes`、または `blocked`、判定なし、ファイルを変更した(変更は取り消します) | 現状をコミットして push し、理由を付けた**ドラフト** PR を作成、レビュー結果をコメント。`needs changes` で止めたときは「Suggested instructions」(次の実行への修正指示の下書き)も書く | Blocked |
| `## Blocked` を含むレポート | 現状をコミットして push し、理由を付けた**ドラフト** PR を作成、レポートをコメント | Blocked |
| レポートなし、ファイル変更あり | push し、ドラフト PR を作成("agent exited without a report") | Blocked |
| レポートなし、変更なし(クラッシュ) | push せず、PR も作成しない。理由をコメント | Blocked |
| レポートあり、変更なし | push せず、PR も作成しない。レポートをコメント | Blocked(`research` ラベルのタスクは In review) |

再実行(Blocked のカードを Ready に戻す、または `task start`)は同じブランチで作業を続け、同じ PR を更新します。
最新の実行で使われたプロンプトそのものは `~/.local/share/task-hub/prompts/<番号>.md` に保存されます。

### 自動レビューの差し戻し

reviewer は指摘を 2 つに分けます([worker/REVIEW.md](../worker/REVIEW.md))。

| 種類 | 書く場所 | 扱い |
|---|---|---|
| blocking | `## Please fix` | 受け入れ条件を満たさない、使う人やリポジトリの決まりが頼っているものを壊す。差し戻す |
| minor | `## Known issues` | 本物だが、マージしてよい(Goal の外の端の場合、動くもののテストがない、別のタスクにすべきもの)。差し戻さない |

PR の CI でしか確かめられない受け入れ条件(「macos と Windows の CI が通る」など)は、reviewer が `deferred to CI`
と書きます。それだけでは `blocked` にも `needs changes` にもしません。PR を作ると CI が走り、マージキューは CI が
通るのを待ってからマージするからです。CI の通る・落ちるでは決まらない条件(CI の時間、ログの中身など)も
`deferred to CI` です。ただしマージキューは確かめないので、reviewer は Review の欄に見る場所(ジョブの名前とログの行)
を書きます。判定のまとめ方は変わりません。

blocking がなく minor だけなら、レビューは通過です。判定が `needs changes` でも、`Please fix` が空で `Known issues`
だけなら通過として扱います。カードは In review に進み、minor の指摘は PR の本文と Issue のコメントの
「Known issues」に残ります。[オートパイロット](autopilot.md)の対象なら、この PR もマージキューに入ります。

この節が、自動レビューの差し戻しを止める条件の正式な定義です。ほかの文書はここを指し、コード(`review_stop`)は
ここに合わせます([決定事項 39](design.md#決定事項))。

`needs changes` で差し戻す回数は `[runner] review_retries` で決めます。既定は 2 回、0 にすると差し戻しません。
1 回のレビューを 1 ラウンドと数えると、既定では最初のレビューと差し戻しのあとの 2 回で、最大 3 ラウンドです。
次のどれかに当たると、回数が残っていても差し戻しをやめて Blocked にし、人の判断に回します。上から順に確かめます。

| 止まる条件 | 理由の行(Blocked の 1 行目) | `review_stop` |
|---|---|---|
| 差し戻した指摘がまた出た(reviewer が `(again)` を付けたか、同じ文の指摘) | `automated review stopped after ...: a finding came back after the retry it was sent back with` | `repeated` |
| 最後の差し戻しで、ファイルが何も変わらなかった | `automated review stopped after ...: the last retry changed no files` | `no change` |
| 差し戻しの変更が、前の差し戻しより小さくならない(変えた行数。足した行と消した行の和) | `automated review stopped after ...: the retries' changes are not getting smaller (<前> then <今> changed lines)` | `not converging` |
| 差し戻しのあとのレビューで、blocking の指摘が `[runner] review_stop_blocking` 件(既定 3)以下に減った | `automated review stopped after ...: <件数> blocking findings left, [runner] review_stop_blocking = <件数> or fewer go to a person` | `few blocking` |
| 差し戻しの回数を使い切った(最大のラウンドに達した) | `automated review did not pass after <回数> retries` | `limit` |

- `review_stop_blocking` は、差し戻しのあとのレビュー(2 ラウンド目から)だけに効きます。最初のレビューは、
  指摘が 1 件でも差し戻します。「減ったところで止める」の決定で、最初のレビューはまだ減っていないためです。
- `review_stop_blocking = 0` にすると、件数では止めません。blocking が 0 件ならレビューは通過なので、0 件で止まることはありません。
- 既定では、2 ラウンド目に blocking が 4 件以上残ったときだけ、3 ラウンド目のレビューまで進みます。
- 止まった理由は、Blocked の出来事(`events.jsonl` の `reason`)、Issue のレポートのコメントの `## Blocked`、`metrics.jsonl` の
  `review_stop` に残ります。

2 回目からのレビューには、それまでに差し戻した指摘を渡します。reviewer は直っていないものを同じ文で `(again)`
を付けて書き直します。task-hub は、印のある指摘と、空白や大文字小文字、Markdown の飾りを除いて同じ文の指摘を、
「また出た」と数えます。2 回目からのレビューは、既定では前の指摘と、その後に変わった所だけを見ます
([差し戻しの後のレビュー](#差し戻しの後のレビューrunner-re_review))。

`needs changes` のまま止まったときは、Issue のレポートと PR の本文の自動レビューの節のあとに `## Suggested instructions` を書きます。
最後のレビューの blocking の指摘を番号付きで並べ、また出たものには印を付けた、次の実行への修正指示の下書きです。
人は中身を確かめて Ready に戻すだけで済みます。次の実行は前回のレポートを読むので、この下書きも受け取り、
Goal やその後のコメントと食い違わない限りそれに従います。直したいときは、そのコメントを編集するか、コメントを足します。
reviewer が `blocked`(人にしか出せない情報が要る)と判定したときは、下書きを書きません。

### Goldfish のレビュー([runner] review_mode)

```ini
[runner]
reviewer = agent
review_mode = agent     ; agent(既定)/ goldfish
```

| `review_mode` | reviewer に渡すもの | 起動 |
|---|---|---|
| `agent`(既定) | Goal、人のコメント、差し戻した指摘、実装エージェントのレポート、差分 | reviewer 1 体 |
| `goldfish` | Goal、人のコメント、差し戻した指摘、`task check` の判定のコメント(あれば)、差分。**レポートは渡さない** | 視点ごとに 1 体。それぞれ新しいコンテキストで、順に |

`goldfish` は [Elephant-Goldfish Model](https://egm.dev/) の Goldfish の考え方です。実装した側の説明を読まないので、
「テストを通した」のようなレポートの主張に引きずられません。主張は、レビュアーがコマンドを動かして自分で確かめます。
レポートのファイル(`.task-report.md`)も、視点が動く間は worktree から外して `prompts/<番号>-report.md` に置き、終われば戻します。
視点は [worker/REVIEW.md](../worker/REVIEW.md) の最後の部分に `## ` の見出しで書いてあり、見出しを足すと視点が増えます。

| 視点 | 見るもの |
|---|---|
| Goal Auditor | 受け入れ条件と Goal の項目を 1 つずつ、証拠(ファイルと行、動かしたコマンドと出力)つきで met / not met にする。PR の CI でしか確かめられないものは `deferred to CI` |
| Codebase Auditor | 回帰、リポジトリの決まり(AGENTS.md など)と慣習、新しい関数を壊す具体的な入力 |

視点の結果は、次の規則で 1 つの判定にまとめます。まとめた判定で、上の差し戻しと止まる条件がそのまま動きます。

1. どれかが `blocked`(または判定を書かなかった、ファイルを変えた)なら `blocked`
2. そうでなく、どれかに blocking の指摘があれば `needs changes`
3. そうでなければ `pass`。minor だけなら、1 体のときと同じく通過です

同じ指摘(印、空白、大文字小文字、Markdown の飾りを除いて同じ文)が複数の視点から出たら 1 つにします。
blocking と minor の両方に出た指摘は blocking として数えます。Issue のコメントには、まとめた判定と指摘のあとに、
視点ごとの判定と所見(`### Goal Auditor: pass` など)が残ります。

- 視点は同じ worktree で 1 体ずつ動かします。同時に動かさないのは、`[setup]` が入れたものと `[env]` のファイルを
  使ってテストを動かせるようにするためと、起動ごとの使った量(worktree と時刻で見分けます)を分けて測るためです。
  そのぶん時間は視点の数だけかかります。
- `research` ラベルのタスクは、`goldfish` でも 1 体の reviewer がレポートを読みます。レポートが成果物だからです。
- `metrics.jsonl` の `usage` の `role` は、視点の名前(`Goal Auditor` など)になります。`task stats` の役割ごとの行で、
  視点ごとの時間と token を見られます。記録には `review_mode` と、最後のレビューの判定 `review_verdict` も入ります。
- 値が `agent` と `goldfish` 以外なら、エージェントを動かす前にカードを Blocked にします。

### 差し戻しの後のレビュー([runner] re_review)

```ini
[runner]
re_review = delta       ; delta(既定)/ full
```

差し戻しの後のレビューで、何を読むかを決めます。

| `re_review` | 差し戻しの後のレビューが読むもの | 起動 |
|---|---|---|
| `delta`(既定) | Goal、人のコメント、前のレビューが差し戻した指摘(blocking)、前のレビューの Known issues(minor)、**前のレビューが見た作業の木からの差分だけ**。実装エージェントのレポートは渡さない | `review_mode` によらず 1 体 |
| `full` | 1 回目と同じく PR の全部(上の表)と、差し戻した指摘 | 1 回目と同じ |

`delta` のレビュアーが確かめるのは 2 つです。各指摘が直ったかと、直したことで新しい穴ができていないかです。指示は
[worker/REVIEW.md](../worker/REVIEW.md) の 5 つ目と 6 つ目の部分にあります。直っていない指摘は、
1 回目と同じく `(again)` を付けて書き直します。差し戻しの止まり方は変わりません。3 回目のレビューが確かめるのは、
2 回目のレビューが差し戻した指摘です。それより前の指摘は、2 回目が直ったと確かめていて、その後の差分にも入らないからです。
差分がプロンプトの上限で切れたときのために、前のレビューが見た git の tree の番号も渡し、レビュアーが `git diff` で全部を見られるようにします。前のレビューの Known issues は、
まだ残っているものをレビュアーが同じ文で書き直します。PR に残る Known issues は最後のレビューのものだからです。

`delta` のレビュアーには、`review_mode` によらず実装エージェントのレポートを渡しません。レビューの間は worktree の
`.task-report.md` も外します。過去のカードで測った試行がレポートなしで動いたのと、レポートがあるとレビュアーが
それを理由に確かめを省くことがあったためです([lessons.md](lessons.md#自動レビューの-agent-と-goldfish-を比べる-2026-10-27タスク-253))。
テストの結果も渡さず、レビュアーが変わった所のテストを自分で動かします。レビューの時点で task-hub は自分で確かめた
テストの結果を持っていないからです。実行の記録(ログ)にはエージェントの手順だけが残り、コマンドの出力は残りません。CI は PR を開いた後に動きます。

次のときは、`delta` でも PR の全部を読みます。

- 前のレビューの後の変更が大きいとき: **変えた行数(足した行と消した行の和)が 300 を超えるか、変えたファイルが 10 を超える**
- `research` ラベルのタスク(レポートが成果物なので)
- 前のレビューが見た作業の木を読めないとき(記録がない、長く待つ間に git の掃除で消えた)。`Scope:` の行に
  `the change since the earlier review cannot be read` と書きます

この線と既定は、過去のカードでの試行の結果から決めました([lessons.md](lessons.md#レビューの-token-を減らす-3-つの方法を過去のカードで試す-2026-10-29タスク-404))。

- 差し戻された 6 枚で、変わった所だけのレビューは 6 枚とも元の 2 回目と同じ判定でした。直していない版は、2 枚とも `(again)` で差し戻しました。
- 費用の重みをかけた token は元の 22%、時間は 12% でした。元の 2 回目は goldfish の 2 体で、試行は 1 体です。
- 試行の差分は、6 枚のうち 5 枚が 6〜176 行、3〜5 ファイルでした。残りの 1 枚は main を取り込んだ 936 行、27 ファイルで、今の線では全部を読みます。
- どれも 1 回ずつの結果です。測り直しで線や既定は変わりえます。全部の読み直しでしか見つからない穴(直しが、変えていない所を壊す)が
  あったカードはなく、変わった所だけでそれを見逃すかは測れていません。気になるときは `re_review = full` で今までのレビューに戻せます。

どの読み方をしたかは、あとからたどれるように次のところに残します。

- レポートのコメントと PR の本文の `## Automated review`: `Verdict:` の次の行に `Scope:` の行を書きます。`delta` なら
  `Scope: the findings sent back and the change since the earlier review (<行数> changed lines in <数> files), not the whole pull request`、
  変更が大きくて全部を読んだなら `Scope: the whole pull request: the change since the earlier review (...) is past the line of a re-review (...)` です。
  1 回目のレビューと、`full` での差し戻しの後のレビューには書きません(文書だけの PR の軽い確かめは、下の節の 1 行を書きます)。
- 機械が読む 1 行の `scope`: `delta` か `full`(下の「判定の残し方」)
- `metrics.jsonl` の `review_scopes`: 実行の中のレビューごとの `delta` か `full`(文書だけの PR の軽い確かめなら `light`。
  [docs だけの変更の軽い確かめ](#docs-だけの変更の軽い確かめrunner-light_review))。`reviews`(判定)と同じ順です
- `usage` の `role` は、`delta` のレビューでは `re-reviewer` です

値が `delta` と `full` 以外なら、エージェントを動かす前にカードを Blocked にします。

### docs だけの変更の軽い確かめ([runner] light_review)

```ini
[runner]
light_review = docs     ; docs(既定)/ off
```

PR が変えたファイルが全部文書のとき、PR の全部を読むレビューを、軽い確かめに替えます。

| `light_review` | 文書だけの PR のレビューが読むもの | 起動 |
|---|---|---|
| `docs`(既定) | Goal、人のコメント、差し戻した指摘(あれば)、**PR の差分**。実装エージェントのレポートは渡さず、worktree からも外す | `review_mode` によらず 1 体 |
| `off` | ほかの PR と同じ(上の表) | ほかの PR と同じ |

軽い確かめのレビュアーは、テスト、ビルド、文書に書かれたコマンドを動かしません。ほかのファイルを開くのは、次を確かめるときだけです。
指示は [worker/REVIEW.md](../worker/REVIEW.md) の 7 つ目の部分にあります。返し方と、blocking と minor の分け方は、ほかのレビューと同じです。

1. Goal の受け入れ条件を 1 つずつ。Goal の節が丸ごとない、のような抜けも見ます。差分から確かめられない条件は
   `not checkable from the diff` とし、それだけでは差し戻しません
2. 足したリンクと変えたリンク: 先のファイルと、アンカーの見出しがあるか。名前を変えたり消したりしたファイルへのリンクが、ほかの文書に残っていないか
3. 文書に書いたコマンド、オプション、設定、パス: リポジトリにある綴りか(コードを検索して確かめる)。例がそのまま動く書き方か
4. 食い違い: もう一方の言語の版(`README.md` と `README.ja.md` など)や、一緒に直す決まりの文書が、同じことを言っているか。
   既定や数や名前が、変えていない所の記述と合っているか

差分がプロンプトの上限(20,000 字。Windows は 12,000 字)で切れたときは、変えたファイルそのものを読んで残りを確かめます。

**文書とするもの**(`is_doc`): 拡張子が `.md`、`.markdown`、`.rst`、`.adoc` のファイルです。ただし、エージェントやプログラムが
指示として読むものは文書としません。

- 名前が `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、`SKILL.md`(大文字小文字を問わない)
- `.` で始まるフォルダ(`.claude/`、`.github/`、`.kiro/` など)の下
- `worker/`、`skills/`、`prompts/`、`agents/`、`commands/`、`steering/` という名前のフォルダの下(どの深さでも)

PR の分かれた所からの全部のファイル(足した、変えた、消した、名前を変えた前と後)が文書のときだけ、軽い確かめにします。
画像や `.txt` が 1 つでも混ざれば、全部を読むレビューです。`research` ラベルのタスクも、レポートが成果物なので全部を読みます。
差し戻しの後のレビューは、[差し戻しの後のレビュー](#差し戻しの後のレビューrunner-re_review)の `delta` が先です。
`delta` にならず PR の全部を読み直すときに、PR が文書だけなら軽い確かめにします。

この既定と線は、過去のカードでの試行の結果から決めました([lessons.md](lessons.md#レビューの-token-を減らす-3-つの方法を過去のカードで試す-2026-10-29タスク-404))。

- docs だけの 3 枚は、元のレビューと同じ判定でした(Goal の節が丸ごとない穴を 1 件見つけ、2 枚は pass)。
  費用の重みをかけた token は、試した 7 枚で元の 19%、時間は 8% でした。
- 小さなコードの直し(200 行)では、動かして初めて分かる穴を見逃しました。そのため、コードを 1 つでも含む変更には使いません。行数の線は引けませんでした。
- どれも 1 回ずつの結果で、docs だけの変更は 3 枚だけです。docs だけの変更で見逃しがないとは、まだ言えません。
  測り直しで、既定と、文書とするものの線は変わりえます。気になるときは `light_review = off` で今までのレビューに戻せます。
- 試行との違い: 試行の指示は「ほかのファイルを開かない」でした。ここでは、リンクの先、もう一方の言語の版、コマンドのコード、
  文書の決まりを確かめるために、そのファイルだけを開いてよいことにしています。文書で起きやすい穴を確かめる 2〜4 の指示も足しました。
  この違いの分の結果は測っていません。

どの読み方をしたかは、あとからたどれるように次のところに残します。

- レポートのコメントと PR の本文の `## Automated review`: `Verdict:` の次の行に
  `Scope: a light review of the Goal and the diff: every changed file is a document (<数> files)` と書きます
- 機械が読む 1 行の `scope`: `light`
- `metrics.jsonl` の `review_scopes`: そのレビューの位置に `light`
- `usage` の `role` は `light reviewer` です

値が `docs` と `off` 以外なら、エージェントを動かす前にカードを Blocked にします。

### 判定の残し方(Review 欄と機械が読む 1 行)

最後のレビューの判定は、カードを読むだけで分かるように 2 か所に残します。

- **Project の Review 欄**: 単一選択の欄に `pass` / `needs changes` / `blocked` を入れます。判定のないレビューも
  `blocked` です。欄がなければ、初めてのレビューが選択肢つきで作ります(Readiness 欄と同じ作り方)。
  レビューのなかった実行(reviewer がない、エージェントが自分で Blocked にした、変更がない)は、終わるときに欄を空にします。
  前の実行の判定が残らないようにするためです。
  欄を書けなくても、実行は止めません(ログに理由を書きます)。
- **レポートのコメントの 1 行**: `## Automated review` の見出しのすぐ下に、GitHub では見えない 1 行を書きます。
  `attempt` はその実行の何回目のレビューか(1 から)、`scope` は何を読んだか(`full` は PR の全部、`delta` は前の指摘と
  その後の変更だけ。[差し戻しの後のレビュー](#差し戻しの後のレビューrunner-re_review)。`light` は文書だけの PR の Goal と差分。
  [docs だけの変更の軽い確かめ](#docs-だけの変更の軽い確かめrunner-light_review))です。PR の本文にも同じ 1 行が入ります。

```markdown
## Automated review

<!-- task-hub review: {"verdict": "needs changes", "blocking": 2, "minor": 1, "mode": "goldfish", "attempt": 1, "scope": "full"} -->
Verdict: needs changes
```

読む側は次のとおりです。

- `digest()`(イベント、通知、`task show --digest`、`task events --digest`)は、`verdict` をこの行から読みます。
  指摘があれば `findings: 2 blocking, 1 minor (goldfish, attempt 1)` も足します。この行のない古いレポートは、
  今までどおり `Verdict:` の行から読みます。
- `task list` は、Project に Review 欄があれば `review` の列を出します。値は欄の判定です。このマシンで動いたカードは、
  最後の Status イベントの digest から指摘の数を足します(`needs changes (2 blocking, 1 minor)`)。GitHub を読み足しません。

### レビューを試す(task review --no-write)

`[runner] review_mode` の 2 つや、レビューを安くする方法([lessons.md](lessons.md#レビューの-token-を減らす-3-つの方法を過去のカードで試す-2026-10-29タスク-404))を
過去のカードで比べるためのコマンドです。カードのリポジトリのあるコミットのコードを、実行と同じ指示でレビューし、
判定と使った量を表示します。GitHub には何も書きません。

```sh
task review 12 --no-write --ref 1a2b3c4 --base 9f8e7d6 --mode goldfish
task review 12 --no-write --ref 1a2b3c4 --base 9f8e7d6 --mode agent --report-file report.md
```

- `--ref` のコミットを、使い捨ての worktree(`~/.local/share/task-hub/worktrees/<番号>-review-trial`)に取り出して
  レビューします。終わったら消します。`[setup]` と `[env]` は使いません。
- 差分は `--base` から `--ref` までです。`--base` を省くと、カードの Base branch(空ならデフォルトブランチ)から分かれた所です。
- `--mode` を省くと `[runner] review_mode` です。`agent` には、そのときの実装エージェントのレポートを `--report-file` で渡します。
  `--goal-file` を渡すと、Issue の本文の代わりにその文を Goal にします(実行のあとに Goal を編集したカード用)。
- 試すための口が 3 つあります。どれも既定の動きは変えません。
  - `--instructions-file`: `worker/REVIEW.md` の最初の部分(レビューの指示)の代わりに、そのファイルの文を渡します。
    返し方の形(`.task-review.md` の見出し)は、渡す文に書いておきます
  - `--sent-file`: 前のレビューが差し戻した指摘(1 行目が `- ` の項目を 1 件と数える)を、実行の 2 回目のレビューと同じく渡します。
    `--base` を前のレビューが見たコミットにすると、その後の変更だけの差分になります
  - `--setup`: 実行と同じく、`[env]` のファイルを置き、`[setup]` を動かしてからレビューします。テストに準備が要るリポジトリ用です
- モデルは `[agents]` のコマンドのままです。claude なら、環境変数 `ANTHROPIC_MODEL=claude-sonnet-5-5` を付けて動かすと替わります。
- 結果は `~/.local/state/task-hub/review-trials.jsonl` に 1 行ずつ残ります。`metrics.jsonl` には入れません。
  ログは `logs/<番号>-review-trial.log` です。

## PR

- ブランチは `task/<番号>`、ベースはカードの Base branch(空欄ならリポジトリのデフォルトブランチ)、タイトルは Issue のタイトル
- 説明: `## Blocked`(ある場合)、`## Report`、`## Please review`、`Closes <issues repo>#<番号>`、エージェント名のフッター
- マージされると `Closes` によって Issue が閉じ、Project のワークフロー(Item closed)でカードが Done に移ります。
  次の確認で task-hub はカードが開いた列から消えたことに気づき、worktree と herdr のワークスペースを削除します
- GitHub のドキュメントは「`Closes` はデフォルトブランチへのマージのときだけ効く」としています。デフォルトブランチへの
  マージでも閉じなかったことがあります。そのため task-hub が In review と wait for merge のカードすべての
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
