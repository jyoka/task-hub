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
- **途中経過**: 組み込みのエージェント(claude、codex、pi、kiro)は、手順ごとに 1 行をログ(herdr のタブ、`task log`、
  task-rs の `l`)に出します。ツールの呼び出しは `· ツール名: 何を`、エージェントの文は先頭の 1 行、サブエージェントの
  手順は 2 字下げです。最後の結果の文は全部残ります。ツールの結果の中身は出さず、1 行は 200 字までです。
  ツール名は各 CLI のものです(claude は `Bash`、`Read`、codex は `shell`、`apply_patch`、pi は `bash`、`read`、
  kiro は `shell`、`read`、`write`)。
  ```
  == agent: claude
  I'll look at the TUI first.
  · Read: rust/src/tui.rs
  · Grep: "log_tail"
  · Edit: rust/src/tui.rs
  · Bash: cargo test -p task-rs
  ```
  `slow` が届いたら、最後の行がいつのものかで、進んでいるのか止まっているのかを判断します。`config.ini` でコマンドを
  自分で書いていて、組み込みと同じ出力のフラグ(claude と kiro は `--output-format stream-json`、codex は `--json`、
  pi は `--mode json`)がなければ、今までどおり出力をそのまま書きます
  ([agents.md](agents.md#エージェントの変更と追加))。そのとき claude と pi は最後の結果だけ、codex はツールの出力と
  プロンプトも含めた全部、kiro は `[tool] Running: ...` の行が出ます。
  エージェントが失敗で終わると、その理由が `ERROR: ...`(codex)、`== pi ended with error: ...`、
  `== kiro ended with an error: ...`、`== claude ended with ...` の行に出ます。
- **段階**: `task list` の status 列と `task show <番号>` の `status:` は、実行が生きている間、今の段階を
  `In progress › review` のように付けて出します。段階は `preparing`(worktree とタブの準備)、`setup`、`agent`、
  `review`、`retry`(差し戻しを受けた実装エージェント)、`finishing`(push、PR、コメント)、`replanning` です
  (詳しくは [design.md](design.md) の「In progress の段階」)。`Blocked › replanning` は、カードはもう Blocked でも
  replanner がまだ動いているという意味です。段階は手元の `runs/<番号>.json` の `stage` にだけあり、GitHub のボードと
  `events.jsonl` には出ません。実行が終わると何も付かなくなります。
- **生きている実行があるタスクは始まりません**: replanner が動いている間などに Ready に戻したカードは、`task` と
  `task list` の `waits_for` に `its last run, still running (replanning)` と出て待ち、その実行が終わったあとの確認
  (`task watch` なら 1 分以内)で始まります。同じ worktree で 2 つの実行が動かないようにするためです。`task done` も
  `still running` で断るので、急ぐときはそのタブで Ctrl-C してから実行します。
- エージェントに伝えた内容: `~/.local/share/task-hub/prompts/<番号>.md`。

### ボードを隣のペインに出し続ける(`task list --watch`)

`task list --watch` は、`task list` と同じ一覧を 1 分ごとに描き直し続けます。エージェントの隣のペイン(herdr、tmux、
ターミナルの別の窓)で動かしておけば、Claude Code でも kiro-cli でも、どのエージェントの横でも同じようにボードが見えます。
herdr なら、エージェントのペインを右に分けて(`herdr pane split --current --direction right` でも分けられます)、
新しいペインで次を実行します。

```sh
task list --watch
```

- 読み取り専用です。`task list` と同じく、カードの開始・移動・同期はしません。Ready のカードを自動で始めるのは
  `task watch` です
- 端末では画面を消して描き直し、見出しに最終更新の時刻(このマシンのローカル時刻、例: `2026-10-04 14:12:26 JST`)を出します。前の回から status 列が変わった行は太字の黄色で出ます
- パイプやファイルに流すと、ANSI の色や画面の消去を使わず、`== <時刻>` の行と `task list` と同じ行を毎回追記します
- GitHub のエラーでは止まりません。`error:` の行を出して、次の回にまた読みます。止めるときは Ctrl-C です

### ボードの読み取りを共有する(`--max-age`)

Claude Code の mod と Kiro の拡張は、窓ごとに 1 分おきに `task list` を実行します。窓が増えても GitHub への
問い合わせが増えないように、`task list` は直近に読んだボードを共有します。

- task-hub のコマンドが GitHub から開いているカードを読むと、`~/.local/state/task-hub/board-cache.json` に書きます。
  `task watch` は 1 分ごとに書くので、動いていれば窓の `task list` は GitHub を呼びません
- `task list` と `task list --watch` は、これが 90 秒より新しければそれを出します。秒数は `--max-age <秒>` で変えられ、
  `0` なら必ず GitHub から読みます。古ければ 1 つの窓だけが GitHub を読み、ほかの窓はその結果を待って使います
- 共有するのは GitHub から読んだカードだけです。段階(stage)、`waits_for`、実行中かどうかは毎回このマシンで計算します
- task-hub がボードを変えたとき(開始、移動、`task new`、`task done` など)は、それより前に読んだボードを使いません。
  変更はすぐに出ます。GitHub の画面で動かしたカードやマージで閉じた Issue は、最大 90 秒遅れて出ます
- mod と拡張の「今すぐ更新」ボタンは `--max-age 0` で読みます
- Project の id と欄の id は `~/.local/state/task-hub/board-meta.json` に 1 時間取っておきます。ボードで欄や選択肢の名前を
  変えたら、`task list --max-age 0` で読み直します

### 並び順と、古い Done のアーカイブ

- **並び順**: task-hub はカードの Status を変えるたびに、そのカードを Project のいちばん上に置きます。列の上にあるのが、
  最後に動いたカードです(作った順ではありません)。`task list`、`task`、mod のペイン、Kiro のビューは、カードを最後に
  変えた時刻(GitHub の updatedAt)の新しい順に並べるので、GitHub の画面で動かしたカードも上に来ます。GitHub の画面で
  欄だけを書き換えたカードは、こちらでは上に来ても、GitHub の列では動きません。Board の表示に Sort を付けていると、
  GitHub の列はこの並びになりません([setup.md](setup.md) の「GitHub 側の準備」)
- **始める順番**: Ready のカードが枠より多いときは、表示の順ではなく、作った順(番号の小さい順)に始めます
- **アーカイブ**: タスクのカード(Issue リポジトリの Issue)が 100 枚を超えると、Done のカードを、動いたのが古い順に
  アーカイブして 100 枚に戻します。確かめるのは、`task watch` を始めたとき、`task done` のとき、このマシンで動いた
  タスクが Done になったとき(マージ)です。GitHub の画面だけで閉じた Issue では確かめないので、次のどれかまで 100 枚を
  超えたままのことがあります
  - アーカイブするのは、Done で Issue も閉じているカードだけです。開いているカード(Backlog、Ready、In progress、
    In review、Blocked)と、Issue を閉じずに Done へ動かしたカードは、古くてもアーカイブしません。開いているカード
    だけで 100 枚を超えることもあります
  - Issue は閉じたまま残ります。カードは Project の「Archived items」から戻せます
  - アーカイブしたカードは task-hub から見えません。`task show <番号>` も `not found on the board` になります。
    中身は Issue を直接見ます(`gh issue view <番号> --repo <Issue リポジトリ>`)

## 起きたことを受け取る(events.jsonl)

task-hub はカードの列を動かすたびに、`~/.local/state/task-hub/events.jsonl` に 1 行書きます。GitHub を見に行かなくても、
このファイルを見張れば、何かが起きた瞬間に分かります。`task events` は最近の 20 件を、`task events --follow` は
新しい出来事を起きるたびに 1 行ずつ出します。`task events --next` は次の出来事を待って出力し、続きから読むための
コマンドを `next: task events --next --after <n> ...` の行に出して終わります(`<n>` は events.jsonl の行番号なので、
2 回の実行の間に起きたことも取りこぼしません)。総指揮のエージェント(`/chief`)は、Claude Code では
`--next --after <n> --digest` をたどるシェルのループを Monitor で常駐させ、出来事と要点を 1 回の通知で受け取ります
(出来事ごとの動かし直しも、出力ファイルを読む手間もありません)。Monitor は最長でも 30 分ほどで切れるので、
`/chief` は最後に受け取った `next:` の `<n>` から張り直します。`--follow` はファイルの末尾から読み始めるため、
張り直すまでの間に起きた出来事を落とします。そのため `/chief` は `--follow` を使いません。`task` が失敗したとき
(PATH にない、`--after` の値が不正など)は、ループが `watch stopped: <エラー>` の行を出してコード 1 で終わり、
`/chief` は張り直さずに人に 1 行で知らせます。Monitor のないハーネスでは `--next --digest` を裏で動かし、終わって
起こされるたびに `next:` のコマンドで動かし直します。Pi では拡張機能が同じ `--next --digest` のループを回します。

待てない呼び出し側には、`--next` を付けない `task events --after <n>` があります。`<n>` 行目より後の出来事を出し、
最後に `next: task events --after <m> ...` の行を出して、**待たずに** 終わります(出来事がなくても `next:` の行は出し、
コード 0 で終わります)。`--only` と `--digest` もそのまま使えます。Kiro IDE の Prompt Submit フック
(`kiro/task-events-since`)はこれを使い、話しかけるたびに前回からの In review、Blocked、replan、Done、slow を文脈に足します。
Kiro Workflows の `watch` が呼ぶ `kiro/task-events-watch` も同じものを使い、`next:` の番号を Workflows のカーソルにします。

```json
{"time": "2026-09-26T14:05:00Z", "id": "41", "title": "保存できる項目に…", "repo": "jyoka/aica_ra_a2a_poc", "event": "In review", "pr": "https://github.com/jyoka/aica_ra_a2a_poc/pull/36", "digest": {"verdict": "pass", "review": ["api/save.py: 必須項目の判定", "マイグレーションの順番"], "pr": "https://github.com/jyoka/aica_ra_a2a_poc/pull/36"}}
{"time": "2026-09-26T14:20:00Z", "id": "32", "title": "求人検索と…", "repo": "jyoka/aica_ra_a2a_poc", "event": "Blocked", "reason": "前提の PR #26 がまだマージされていない", "digest": {"reason": "前提の PR #26 がまだマージされていない"}}
{"time": "2026-09-26T14:21:00Z", "id": "32", "title": "求人検索と…", "repo": "jyoka/aica_ra_a2a_poc", "event": "replan", "decision": "human", "digest": {"decision": "human", "question": "PR #26 を先にマージしてよいですか?"}}
```

`event` は列の名前(`Backlog`、`Ready`、`In progress`、`In review`、`Blocked`、`Done`)か、replanner が仕分けたときの
`replan`、実行がいつもより長引いているときの `slow`、実行が予算を超えたときの `over budget`([予算と残高](#予算と残高))、マージキューの出来事(`queued`、`updated`、`conflict-fix`、`ci-wait`、
`merged`、`conflict`。[マージキュー](#マージキュー))です。`reason`(Blocked の 1 行、`slow` では
`running 40 min, usually 8 min for kiro` のような経過時間といつもの時間)、`pr`、`decision`、`digest` は、あるときだけ
入ります。マシンごとのファイルで、そのマシンの task-hub が動かしたものだけが書かれます。
GitHub が Done にしたカード(PR のマージで Issue が閉じたときの「Item closed」や、GitHub 上で手で閉じたとき)も、
このマシンで動かしたカードなら、`task` の同期が気づいたときに Done を 1 回だけ書きます。

`slow` は、`task` の同期(`task watch` なら 1 分ごと)が、このマシンで生きている In progress の実行に 1 回だけ出します。
しきい値は、そのエージェントの終わった実行の所要時間の中央値の 3 倍で、最低 15 分、終わった実行が 3 件未満なら
30 分です。設定はありません。task-hub は実行を止めません。止めるなら herdr のそのタスクのタブで Ctrl-C です
(途中までの変更は push され、カードは Blocked になります)。

### 判断用の要点(digest)

In review、Blocked、replan のイベントには、人が判断するための要点 `digest` が入ります。task-hub が Issue に書く
レポートや replanner のコメントと同じ内容から、書くその場で作るので、GitHub を読み直しません。読む側も
`task show <番号> --full` を読まずに、イベントだけで判断できます。

| キー | 入るとき | 中身 |
|---|---|---|
| `verdict` | 自動レビューがあるとき | 自動レビューの判定(`pass`、`needs changes`、`blocked`) |
| `reason` | Blocked | 止まった理由の 1 行 |
| `report` | PR のない In review(research タスク) | Report の要点(`### Summary` の箇条書きを 1 行にしたもの。要点のない古いレポートは、最初の `###` 見出しより前) |
| `review` | レポートに Please review があるとき | 項目を最大 3 つ。多いときは `(+N more)` を足す |
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
- 本文: 要点を `verdict: pass`、`reason: ...`、`report: ...`、`review: ...`、`decision: human`、`question: ...` のように 1 行ずつ。
  最後の行が PR の URL(あれば)
- 出し方: herdr が動いていれば `herdr notification show`(Blocked と replan は `--sound request`、ほかは
  `--sound done`)。herdr がなければ macOS の通知(`osascript` の `display notification`)、Windows のトースト、
  Linux の `notify-send`(Blocked と replan は `--urgency critical`)の順で、このマシンにあるもの。どれもなければ出しません
- スマートフォンへ: `[notify] ntfy` を書くと、上のこのマシンの通知に**加えて**、同じ見出しと本文を
  [ntfy](https://ntfy.sh) のトピックにも送ります(下記)

通知はイベントを書いたプロセス(実行中の `task _run`、`task watch`、`task`、`task start` など)がそのまま出します。
見張り役のプロセスを別に動かす必要はなく、`task watch` を止めていても、実行が終わった瞬間に届きます。通知のコマンドは
待たずに切り離して起動するので、通知が出せない、失敗する、止まったままになる、のどれでも task-hub の処理は
そのまま続きます(その通知は出ないだけです)。

`update` はタスクの出来事ではなく、task-hub 自身の新しい版です。`task watch` が 1 日 1 回まで origin のタグを確かめ、
新しい版を見つけたときに、その版について 1 回だけ出します(見出し `task-hub v0.7.0`。events.jsonl には書きません)。
更新は `task update` です([setup.md](setup.md#インストール))。

どの出来事で通知するかは `~/.config/task-hub/config.ini` の `[notify]` で変えられます:

```ini
[notify]
events = In review, Blocked, replan, Done, slow, update, conflict, autopilot, over budget   ; 既定。列の名前か replan、slow、over budget、update、マージキューの出来事をカンマ区切りで。空にすると通知しない
ntfy = https://ntfy.sh/<トピック>   ; 既定は空(送らない)。自分の ntfy サーバーなら https://<サーバー>/<トピック>
ntfy_token = tk_...                ; 任意。アクセス制御のあるトピックのトークン(Authorization: Bearer で送る)
```

通知は、このマシンで task-hub が書いた出来事だけです(events.jsonl と同じ)。macOS で通知が見えないときは、
システム設定の「通知」で、herdr または「スクリプトエディタ」(osascript の通知はこの名前で出ます)が許可されて
いるか確かめます。

Blocked や In review を席にいないときにも知るための方法(ntfy、GitHub の通知メールなど)を比べた結果は
[notifications.md](notifications.md) にあります。

#### スマートフォンに届ける(ntfy)

`ntfy` を書くと、`events` に入っている出来事を ntfy のトピックにも送ります。スマートフォンの ntfy アプリで
そのトピックを購読しておけば、席を離れていても届きます。このマシンの通知(herdr、macOS など)はそのまま出ます。

- 送り方: ntfy の JSON での送信(サーバーの URL に POST し、トピックは本文に入れる)。見出しに日本語が入っても
  そのまま届きます。使うのは Python 標準ライブラリの `urllib` だけです
- 優先度: Blocked と replan は高(4)、ほかは既定(3)
- タップしたときに開く URL: PR があれば PR、なければ Issue(`[board] issues` から作ります)。`update` には付けません
- ボタン: `task intake` を設定していれば、実行が終わって In review になった通知に Merge、Reject、View PR の
  ボタンが付きます([スマートフォンから PR を承認する](#スマートフォンから-pr-を承認するボタン))
- 値が空、または `<サーバー>/<トピック>` の形でないときは送りません(それまでと同じ動き)

送るのも、通知のコマンドと同じく切り離した別のプロセス(`python -I -c`、待つのは 10 秒まで)です。サーバーが
落ちている、名前が引けない、つながったまま答えない、のどれでも、`task _run`、`task watch`、ほかのコマンドは
待たずにそのまま続きます(その通知が届かないだけで、エラーも出しません)。トピックの名前は知っている人なら
誰でも購読できるので、ntfy.sh を使うときは推測されにくい名前にするか、トークンで守ります。

## スマートフォンからカードを作る(`task intake`)

`task intake` は ntfy のトピックを購読し続け、スマートフォンから送った文を Backlog のカードにします。カードを
作ったら、`[notify] ntfy` のトピックにカードの番号とリンクを返します。LLM は使いません。常駐のさせ方(Linux の
systemd)は [setup.md](setup.md#スマートフォンから登録するtask-intake) にあります。

```ini
[notify]
ntfy = https://ntfy.sh/<通知のトピック>   ; 必須。サーバー、トークン、返事の送り先をここから使う
ntfy_token = tk_...                       ; 任意。購読にも使う

[intake]
topic = <登録のトピック>   ; 必須。[notify] ntfy と同じサーバーの、通知とは別のトピック(推測されにくい名前に)
secret = <合言葉>          ; 必須。16 文字以上、空白なし。python3 -c "import secrets; print(secrets.token_urlsafe(16))"
repo = owner/name          ; 任意。文に owner/name: がないときの作業先(Target repo)
```

### 送る文の形

ntfy アプリで登録のトピックを開き、次の形で送ります:

```
<合言葉> owner/name: ログイン画面のボタンを直す
スマートフォンで下のフッターに重なる。
```

| 部分 | 意味 |
|---|---|
| 1 語目 | 合言葉(`[intake] secret`)。完全に同じでなければ、その文は捨てる |
| `owner/name:`(任意) | 作業先のリポジトリ。なければ `[intake] repo`。どちらもなければ登録しない |
| 残り全部 | Goal(Issue の本文)。最後に「From the phone (`task intake`, ntfy message <id>, <時刻>).」を足す。合言葉は本文に入れない |
| タイトル | ntfy アプリの見出し(Title)を書けばそれ。なければ Goal の 1 行目(72 文字まで。長ければ語の切れ目で `...`) |

`owner/name:` は 2 語目が `<英数字と . _ ->/<同じ>:` の形のときだけ作業先と見なします(`fix http://...:` は Goal の
一部です)。リポジトリがあるかは登録のときには確かめず、始めたときに clone できなければ Blocked になります。返事の
`repo:` を見て、違っていればカードの Target repo 欄を直します。

### 安全のための決まり

- カードは必ず **Backlog** に作ります。Ready には動かしません。始めるのは、あなたがボードで Ready に移すか
  `task start <番号>` を実行したときだけです
- 公開の ntfy.sh のトピックは、名前を知っていれば誰でも読み書きできます。合言葉のない文、違う文は、
  ログに `intake: ignored: no secret (message <id>, <文字数> chars)` や `ignored: wrong secret` と 1 行書くだけで、
  カードも返事も作りません(本文はログに残しません)
- 合言葉は送った文としてトピックに残り、購読できる人には読めます。トピックの名前も推測されにくくするか、
  アクセス制御のある自分の ntfy サーバー(`ntfy_token`)を使います。漏れたと思ったら `secret` を変えて再起動します
- `[intake] topic` は `[notify] ntfy` のトピックと同じにできません(返事を自分で読まないため)

### 返事と記録

| こんなとき | ntfy への返事(`[notify] ntfy` のトピック) | ログの 1 行 |
|---|---|---|
| 登録した | `#<番号> Backlog: <タイトル>`、本文に `repo:` と `task start <番号>`。タップで Issue が開く | `intake: #<番号> Backlog in <repo>: ...` |
| Goal が空、作業先がない | `task intake: not registered`(理由つき、優先度 4) | `intake: rejected: ...` |
| GitHub に登録できなかった | 同上(`GitHub: ...`) | `intake: error: ...` |
| 合言葉がない、違う | なし | `intake: ignored: ...` |

返事は `[notify] events` に関係なく送ります(送った人が待っているため)。送り方は通知と同じ、切り離した別のプロセスです。

### つながりと取りこぼし

- ntfy の JSON の購読(`GET <サーバー>/<topic>/json?since=...`)を開いたままにします。120 秒何も来なければ
  切れたと見なしてつなぎ直します(ntfy は 45 秒ごとに keepalive を送ります)
- サーバーが落ちている、トークンが違う(`HTTPError: HTTP Error 403`)などは、`intake: ... connecting again in 5s` と
  記録して待ちます。待つ時間は失敗が続くたびに倍にし、300 秒までです
- 扱った最後の文の id を `~/.local/state/task-hub/intake.json` に書き、つなぎ直しや再起動のあとはその次の文から
  受け取ります(ntfy.sh が文を持っている 12 時間のうち)。初めて起動したときは、起動したあとの文だけです
- 1 つの文からカードを 2 枚作らないよう、id はカードを作る前に書きます。GitHub の失敗で登録できなかった文は
  もう一度は試さないので、送り直します

## スマートフォンから PR を承認する(ボタン)

`task intake` を設定していると、実行が終わって In review になったときの ntfy の通知に、ボタンが 3 つ付きます。
外出先でも、通知を 1 回タップするだけでマージキューに入れたり、PR を閉じたりできます。LLM は使いません。

| ボタン | すること | 付くとき |
|---|---|---|
| Merge | その PR をマージキューに入れる(`task merge <番号>` と同じ) | `[merge] queue = on` のときだけ |
| Reject | PR を閉じ、カードを Blocked にする(下記) | いつも |
| View PR | PR をブラウザで開く(task-hub には何も送らない) | いつも |

Merge と Reject は、ntfy アプリが `[intake] topic` に 1 行の文を送るボタンです(ntfy の `http` アクション)。
`task intake` がそれを受け取り、確かめてから実行し、`[notify] ntfy` のトピックに結果を返します。設定は
`task intake` と同じで、増えるものはありません。`task intake` を設定していない(`[intake] topic` か `secret` が
正しくない)ときは、ボタンは付かず、今までの通知のままです。

ボタンが付くのは、`task _run` が push して In review にした通知だけです(`task merge --cancel` で In review に
戻したときの通知などには付きません)。

### Reject のあと

Reject は PR を閉じ(`gh pr close`、「Rejected from the phone」のコメントつき)、マージキューに入っていれば外し、
Issue に「Rejected」のコメントを書いて、カードを **Blocked**(`rejected from the phone: the PR was closed`)にします。
Done にしないのは、Reject は「この PR は要らない」であって、タスクが済んだかは分からないからです。Issue も
ブランチも残るので、あとで次のどちらかを選びます。

- 直してほしいことを Issue にコメントしてから `task start <番号>` で再実行する(同じブランチで続け、新しい PR を開きます)
- やめるなら `task done <番号>`

In review、wait for merge、Blocked 以外のカード、実行中のカードには Reject は効きません(理由を返します)。

### 安全の仕組み

ボタンの文は、公開の ntfy.sh なら名前を知っている人が誰でも送れるトピックに届きます。そこで、ボタンごとに
使い捨てのトークンを付け、`task intake` が確かめてから動きます。

- ボタンの文は `task-hub <merge|reject> <カードの番号> <owner/name>#<PR の番号> <PR の先頭のコミット> <トークン>` です。
  トークンは、これらの値(する事、カード、リポジトリ、PR、コミット)の HMAC-SHA256 の先頭 32 文字です
- HMAC の鍵は、このマシンだけにある `~/.local/state/task-hub/action.key` です(初めて要るときに作る。0600。
  どこにも送りません)。`[intake] secret`(合言葉)は通知に入れません。鍵を消すと、それまでのボタンはすべて効かなくなります
- トークンは 1 つのカード、1 つの PR、1 つのコミット、1 つの操作にしか合いません。Merge のトークンで Reject はできず、
  別の PR にも使えません
- **古いコミット**: `task intake` はボタンを受けると `gh pr view` で PR の今の先頭のコミットを読み、トークンのものと
  違えば断ります。PR に新しい push があれば(競合の修正、再実行、手での push)、その前の通知のボタンでは承認できません。
  最新のコミットを見たうえで、`task merge <番号>` で入れます
- **使い捨て**: 実行したトークンは `~/.local/state/task-hub/intake-actions.json` に記録し、同じボタンを 2 度押しても
  2 回目は断ります(新しい順に 2000 個まで覚えます)。断ったとき(古い、閉じた PR など)や GitHub の失敗では記録しないので、
  理由を直せば同じボタンをもう一度押せます
- **偽物**: トークンが合わない文、ボタンの形でない文は、ログに 1 行書くだけで、何もせず、返事もしません
  (合言葉の違う文と同じく、外から確かめられないように)
- ボタンが送る先は `[intake] topic` です。サーバーがトークンを求めるとき(`[notify] ntfy_token`)は、ボタンが
  `Authorization` ヘッダーにそのトークンを持ちます。通知のトピックを読める人にはそのトークンも見えるので、
  `ntfy_token` は通知と登録の 2 つのトピックにだけ使えるものにします。トークンが漏れても、ボタンの HMAC の鍵は
  漏れないので、勝手にマージや Reject はできません
- Merge は承認するだけです。マージするのは、チェックが通ったあとのマージキューです(`--match-head-commit` で、
  チェックを通ったコミットに限ります)

### 返事と記録

| こんなとき | ntfy への返事(`[notify] ntfy` のトピック) | ログの 1 行 |
|---|---|---|
| Merge した | `#<番号> PR queued: <タイトル>`、本文にキューの位置 | `intake: queued <PR> at position <n>: merge #<番号> (...)` |
| もうキューにある | `#<番号> already queued: <タイトル>` | `intake: already queued: ...` |
| Reject した | `#<番号> rejected: <タイトル>` | `intake: closed <PR>, the card is Blocked: reject #<番号> (...)` |
| 使ったボタン、古いコミット、閉じた PR、キューがオフ、カードがない、など | `#<番号> merge refused`(または `reject refused`)、本文に理由(優先度 4) | `intake: refused: <理由>: ...` |
| GitHub の失敗 | 同上(`GitHub: ...`) | `intake: error: ...` |
| トークンが合わない、ボタンの形でない | なし | `intake: refused: forged token: ...`、`intake: refused: not a button's message ...` |

ログの 1 行には、する事、カード、PR、コミットの先頭 7 文字、ntfy の文の id が入ります。トークンは書きません。

## マージキュー

いくつものタスクを並べて動かすと、1 つの PR がマージされるたびに残りの PR が古くなり、main と競合します。
`[merge] queue = on` にすると、あなたが承認した PR を `task watch` が 1 つずつ base に追いつかせ、競合はエージェントに
解かせ、チェックが通ったらマージします。既定はオフで、オフのときは今までと何も変わりません(wait for merge の列も、
人がマージするまで待つだけの列のままです)。

```ini
[merge]
queue = on          ; 既定は off。キューを動かす
prefix = off        ; on: キューに入れていない In review の PR も、競合したら承認の前に解いておく(マージはしない)
checks = all        ; all(既定): PR のチェックをすべて待つ。required: ブランチの保護で必須のものだけ
ci_minutes = 60     ; チェックを待つ長さ(分)。過ぎたら Blocked
```

### キューに入れる

キューに入るのは、あなたが承認した PR だけです。入れ方は 2 つです。

- `task merge <番号>`: In review(または wait for merge、Blocked)のカードの PR をキューの最後に入れます。ボードに
  wait for merge の列があればカードをそこに動かし、なければ In review のままです。Blocked のカードを直したあとに
  入れ直すときも同じです
- カードを wait for merge の列に動かす(GitHub の画面やスマートフォンで): 次の確認でキューの最後に入ります(動かした順)
- In review の通知の Merge ボタンを押す(`task intake` が要ります。[スマートフォンから PR を承認する](#スマートフォンから-pr-を承認するボタン))
- `[autopilot]` に書いたリポジトリでは、自動レビューが `pass` の In review の PR を、task-hub があなたの代わりに入れます
  ([autopilot.md](autopilot.md))

`task merge` は今のキューを、`task merge <番号> --cancel` はキューから外します(wait for merge のカードは In review に
戻します)。カードを wait for merge(列がなければ In review)から別の列に動かしても外れます。

### 1 つずつ進める

`task watch`(と `task`)は、確認のたびにリポジトリごとにキューの先頭の PR だけを 1 段進めます。1 つがマージされると、
次の PR が取り込む base が変わるからです。

1. PR のブランチに今の base をマージします(`git merge origin/<base>`。2 つの親を持つ本当のマージコミット)。
   きれいに入れば push します。もう追いついていれば何もしません。push が失敗したら、マージコミットを worktree に
   残したまま(捨てません)理由を付けて Blocked にします。直してから入れ直すと、残したコミットを push します
2. 競合したら、タスクの worktree(PR のブランチ)でエージェントに解かせます(`task _fix`、[worker/CONFLICT.md](../worker/CONFLICT.md))。
   手で登録していた「競合を解く」タスクと同じ手順です: 両方の機能を残し、両方が足した番号付きの一覧(設計の決定事項など)は
   base の番号を残してこちらの番号を付け直します。エージェントはファイルを直してレポートを書くだけで、マージコミットと
   push は task-hub が行います(push が失敗したときは 1 と同じく、マージコミットを残して Blocked)。解けなかったら(エージェントが `## Blocked` を書いた、競合の印が残った、エージェントが
   自分でコミットや中止をした)、マージを取り消してカードを Blocked にします
3. PR のチェックを待ちます(`gh pr checks`)。落ちたら、そのチェックのリンクを付けて Blocked にします。PR の最後の
   コミットから 2 分たつまでは、チェックがまだ 1 つも出ていなくても、出てくるのを待ちます。`checks = required` なら
   必須のチェックだけを見ます。必須でないチェックが動いている、または落ちていても待たず、止めません
4. `gh pr view --json mergeable,mergeStateStatus` が `CLEAN`(`checks = required` なら、必須でないチェックが通っていない
   ときの `UNSTABLE` も)なら、チェックが通ったコミットのまま
   (`--match-head-commit`)`gh pr merge --merge` でマージし、カードを Done にして、次の PR に進みます。
   その間に base が進んでいれば(`BEHIND`、`DIRTY`)、1 に戻ります

競合を解いている間も、カードは wait for merge(または In review)のままです。`task list` には
`wait for merge › conflict-fix` と出て、`task log <番号>` に経過が残ります。Blocked にしたときは、理由を
`merge queue: ...` で始まる 1 行にして、Issue に `<!-- task-hub merge -->` のコメントを書きます(タスクのレポートではないので、
再実行のプロンプトには入りません)。直したら `task merge <番号>` でもう一度入れます。

### 承認していない PR の競合

キューに入れていない In review の PR が base と競合したら、`conflict` の出来事を 1 回書いて通知します(PR のコミットごとに
1 回)。毎分すでに読んでいるマージの確認(REST)の `mergeable_state` を見るだけなので、GitHub の呼び出しは増えません。
`[merge] prefix = on` なら、そのまま競合を解いて push しておきます(カードは In review のまま。マージはしません)。

### 出来事

| `event` | いつ | `reason` |
|---|---|---|
| `queued` | キューに入った | キューの何番目か |
| `updated` | base をマージして push した(競合を解いたときも) | 何をどこにマージしたか、解いたファイル |
| `conflict-fix` | 競合を解くエージェントを始めた | 競合したファイル |
| `ci-wait` | チェックを待ち始めた(コミットごとに 1 回) | 待っているチェック |
| `merged` | マージした(すぐあとに `Done` も出る) | マージ先 |
| `Blocked` | 止めた(いつもの Status の出来事) | `merge queue: ...` |
| `conflict` | キューにない In review の PR が競合した | 競合した base |

どれも `task events`、`/chief`(`--only` に足したもの)、ntfy(`[notify] events` に足したもの)から見えます。通知の既定には
`conflict` と(いつもの)`Blocked`、`Done` が入っています。

### 止まったとき

| 理由(`merge queue: ...`) | 対処 |
|---|---|
| `the conflict fixer could not resolve them: ...` | エージェントが人の判断を求めました。手で解くか、Goal に答えを書いて Ready に戻し、終わったら `task merge` |
| `conflict markers are left in ...`、`the conflict fixer ended the merge itself ...`、`the conflict fix did not resolve the conflicts ...` | 解けませんでした(マージは取り消してあります)。`task log <番号>` を読み、手で解いて push してから `task merge` |
| `check <名前> failed: <リンク>` | リンクのチェックを直します。PR に push すれば、`task merge` でまた入れられます |
| `its checks did not finish in N min: ...` | チェックが止まっていないか確かめます。長いなら `[merge] ci_minutes` を延ばします |
| `GitHub does not allow the merge (BLOCKED: ...)` | 必須のレビューやブランチのルールが足りません。満たしてから `task merge` |
| `its PR was closed without merging`、`its PR is a draft` | PR を開き直す、または Ready for review にしてから `task merge` |

チェックを待つ間や、GitHub がまだ計算中(`UNKNOWN`)のときは、キューの同じリポジトリのほかの PR も待ちます。
別のリポジトリのキューは止まりません。

## 実行の結果を集計する

`task stats` は、このマシンで終わった実行を集計します(0.6 から記録しています)。列ごとの件数、エージェントごとの
件数と所要時間の中央値、自動レビューの最初の判定と差し戻しで直った数、差し戻しをやめた理由(`review_stops`。
`limit`、`repeated`、`no change`、`not converging`。[task-format.md](task-format.md#自動レビューの差し戻し))、
Blocked の理由、replanner の判定、
`slow` の出来事が出た実行の数(自動で止めるかを決める材料)、PR の大きさ(ベースから分かれた時点からの変更行数の中央値と、大きい順の 3 件)、エージェントの使用量(下記)です。10〜15 分でレビューできる
数百行を大きく超えるタスクが続くなら、分け方を見直す合図です(基準は `/task` と `/chief` のスキルにあります)。
Blocked の理由は次のどれかです。

| 理由 | 意味 |
|---|---|
| `agent` | エージェント自身が `## Blocked` を書いた |
| `review` | 自動レビューが通らなかった(`blocked`、判定なし、差し戻しをやめたあとも `needs changes` など) |
| `no report` | エージェントがレポートを書かずに終わった |
| `no changes` | レポートはあるが、ファイルを変えなかった |
| `start` | 開始できなかった(Target repo、Base branch、`[env]` など) |
| `setup` | `[setup]` の準備が失敗した、または git が無視しないファイルを残した |
| `balance` | Goal の `paid api:` の残高が足りなかった、または `[balance]` の確認が失敗した([予算と残高](#予算と残高)) |
| `finish error` | 終了処理(push、PR、GitHub への書き込み)が失敗した |

### エージェントの使用量

実行の記録の `usage` は、エージェントを起動するたびに 1 件です(`role` は `agent` / `agent retry after review` /
`reviewer` / `replanner`)。`agent`(エージェント名)と `seconds` は必ず入ります。エージェントの CLI の記録を読めたときだけ、
Claude Code なら `calls`(API 呼び出しの数。サブエージェントの分を含む)、`input`、`cache_creation`、`cache_read`、
`output`(トークン数)、`subagent_calls`、`models` が、pi なら `calls`、`input`、`cache_creation`、`cache_read`、`output`、
`cost`(USD。pi がモデルの価格から計算した値)、`models` が、Kiro なら `calls`(リクエスト数)、`credits`(小数 2 桁)、`models`
が入ります。Kiro の記録にはトークン数がないので、トークンの欄はありません。ほかのエージェント(codex など)では秒数だけです。
読めたときは、ログ(herdr のタブと `task log`)にも起動ごとに 1 行出ます:

```
== agent used 42 calls, 1.2M tokens (18k out), 3 subagent calls, models claude-opus-5-5
== agent used 12 calls, 410k tokens (9.8k out), $0.4210, models gpt-5.5
== agent used 64 calls, 19.21 credits, models auto
```

pi の記録は `~/.pi/agent/sessions/` のセッションのファイルです(`PI_CODING_AGENT_SESSION_DIR` か `PI_CODING_AGENT_DIR` が
あればそちら。pi の `settings.json` の `sessionDir` は読みません)。最初の行の `cwd` がその worktree のファイルだけを開き、
時刻がその起動の間の、使用量のある行(assistant の返事、圧縮の要約、キャッシュの温め)を 1 回の呼び出しとして数えます。
pi は再開(`--session-id`)で同じファイルに書き足すので、前の起動の行は時刻で外れます。ChatGPT のアカウントで動かす
`openai-codex` でも pi は価格から `cost` を出します。実際の請求とは違うことがあります。

`task stats` の `tokens:` の行は、トークン数を測れた実行の数と、1 実行あたりのトークン数(input、cache_creation、
cache_read、output の合計)と呼び出し数の中央値です。測れなかった実行(記録を始める前のもの、Claude Code 以外)の数も
出します。Kiro の実行はトークン 0 としては数えず、`credits:` の行に、クレジットを測れた実行の数と 1 実行あたりの
クレジットの中央値を出します。`cost:` の行は、費用を測れた実行(今は pi だけ)の数と、1 実行あたりの費用の中央値です。
`over budget:` の行は、出来事 `over budget` の数です。`roles` は役割ごとの起動回数、トークンを測れた回数、秒数とトークン数の中央値、
`heaviest` はトークン数の多い 3 実行です。
起動の間にその worktree で動いた Claude Code と pi の呼び出しと kiro-cli の会話は、すべてその起動の分として数えます(エージェント自身が
起動したものも、あなたが同じ worktree で `claude` を開いたものも)。予算を超えたときは出来事を出すだけです(下記)。
止めるかどうかは、この数字と `over budget` の数を見て決めます。

### 予算と残高

**予算**: エージェントを起動し終えるたびに、その実行のここまでの使用量(`usage` の合計)を予算と比べます。
再開した実行では、再開のあとの分だけです(`metrics.jsonl` の `usage` と同じ。前の分は落ちた `task _run` のメモリにありました)。超えた
ものがあれば、出来事 `over budget` を出して通知します。測るものは 4 つで、出来事は測るものごとに実行 1 回につき 1 回です。
今は知らせるだけで、実行は止めません。

| 測るもの | 予算(Goal に `Budget` がないとき) |
|---|---|
| 時間(起動ごとの `seconds` の合計) | そのエージェントの終わった実行の中央値の 10 倍、最低 1 時間。実績が 10 件未満なら 3 時間 |
| トークン(Claude Code、pi) | 中央値の 5 倍、最低 200 万。実績が 10 件未満なら 2000 万 |
| 費用(USD、pi) | 中央値の 5 倍、最低 $1。実績が 10 件未満なら $10 |
| クレジット(Kiro) | 中央値の 5 倍、最低 5。実績が 10 件未満なら 20 |

- 実績は `metrics.jsonl` の、同じエージェント(カードの Agent)の実行です。エージェントが動かなかった実行
  (`blocked_by` が `start`、`setup`、`balance`)は数えません
- カードごとの予算は Goal の `Budget` の見出しに書きます([task-format.md](task-format.md#budget-予算と有料-api))。
  書いたものだけが上の表の代わりになります
- 値はコードの定数です。設定はありません(`slow` と同じ理由です。決定事項 19)
- 確かめるのは起動が終わったときです。1 回の起動が長いと、出来事はその起動が終わるまで出ません。
  長さは `slow` が実行中に知らせます
- `reason` は `used 25.1M tokens, over 20.0M tokens (5 x the median of 30 runs of claude)` のような 1 行です

**残高**: Goal の `Budget` に `paid api: openai` と書いたカードは、`[setup]` のあと、エージェントを起動する前に、
`[balance]` のその名前のコマンドで残高を確かめます。

```ini
[balance]
openai = python3 scripts/check_openai_balance.py   ; 例。worktree で動く。0 で終われば足りている
```

- コマンドは worktree で、`[setup]` と同じように動きます(`sh -c`、Windows は PowerShell。`[sandbox]` ではエージェントの
  ユーザー)。リポジトリの `.env`(`[env]` で写したもの)も読めます
- 0 で終われば足りています。0 以外なら、エージェントを起動せずに Blocked にします。理由には、コマンドの出力の
  最後の行が入ります(`not enough balance on openai ([balance] openai exited 3: ...); add credit, then move the card to Ready again`)
- 60 秒で終わらなければ止めて、Blocked にします
- `[balance]` にその名前がないと、開始の前に Blocked にします(`could not start: ...`)
- 再開した実行では、もう一度は確かめません(確かめるのは最初から始めるときだけです)

OpenAI には API キーで残高を読む公式の API が見当たりません(2026-10-26 に調べた範囲)。確かめ方は
リポジトリごとに決めます。たとえば、いちばん安いモデルに 1 トークンだけの要求を送り、429 の
`insufficient_quota` が返れば 0 以外で終わるスクリプトです。わずかに費用がかかります。

1 行が 1 回の実行の JSON なので、細かく見たいときは `metrics.jsonl` をそのまま読めます。replanner の自動で Ready に
戻す段階に進むか、reviewer をどのエージェントにするかは、この数字を見て決めます。

## 弱い PC で重くないか測る

`task watch` の常駐のメモリと CPU、`task list` の時間は `tests/bench.py` で測ります。手順、目安、今わかっている値は
[benchmark.md](benchmark.md) にあります。

## 保存場所

| 内容 | 場所 |
|---|---|
| タスク(ボード) | GitHub: Issue リポジトリと Project(非公開) |
| 設定 | `~/.config/task-hub/config.ini` |
| 実行中の情報 | `~/.local/state/task-hub/runs/<番号>.json`(このマシンだけ) |
| マージキュー | `~/.local/state/task-hub/merge-queue.json`(このマシンだけ) |
| ログ | `~/.local/state/task-hub/logs/<番号>.log` |
| 実行ごとの記録(`task stats` が集計) | `~/.local/state/task-hub/metrics.jsonl` |
| トリガーが作ったものの記録([triggers.md](triggers.md)) | `~/.local/state/task-hub/triggers.json` |
| 直近に読んだボード(`task list` が共有) | `~/.local/state/task-hub/board-cache.json`、`board-meta.json` |
| リポジトリのクローン | `~/.local/share/task-hub/repos/<owner>/<name>` |
| worktree | `~/.local/share/task-hub/worktrees/<番号>` |
| プロンプト | `~/.local/share/task-hub/prompts/<番号>.md` |

## カードが Blocked になった

理由は Issue の最新の task-hub コメント(`task show <番号>` でも見られます)に書かれています。よくある理由:

再実行は元のリポジトリと worktree で続けます。最初の実行後に Target repo を変えると開始を拒否します。
元の値に戻すか、別のリポジトリの仕事を新しいタスクとして登録してください。`task done` の片付けは保存した
実行情報に従うので、カードの Target repo を変えても元の worktree とローカルブランチを片付けます。

| 理由 | 対処 |
|---|---|
| エージェント自身が書いた行(`## Blocked` から) | 求められたものを与えます。Issue の本文に答えを書き足すか、環境を修正します |
| `agent exited without a report (exit N)` | `task log <番号>` を読みます。多くの場合、エージェントがクラッシュした、ログインしていない、または予算を使い切ったのが原因です |
| `the watchdog stopped the agent: no output and no CPU used` | エージェントが 45 分以上黙っていて、その子孫も CPU を使っていませんでした(下の「黙って止まったコマンド」)。`task log <番号>` の `== watchdog:` の行の前を読みます |
| `agent wrote a report but changed no files` | エージェントはやることがないと判断しました。Goal を明確にします |
| `automated review did not pass after ...`、`automated review stopped after ...: <止まった条件>` | 自動レビューの `needs changes` が、差し戻しのあとも残りました([task-format.md](task-format.md#自動レビューの差し戻し))。Issue のレポートの最後の `## Suggested instructions` を読み、よければそのまま Ready に戻します。指摘が誤りなら、そのコメントを直すか、理由をコメントに書いてから戻します |
| `automated review: blocked: ...` | reviewer が、人にしか出せない情報が要ると判断しました。求められたものを Issue に書いてから Ready に戻します |
| `the run stopped unexpectedly again, after resuming once at <段階>` | `task _run` プロセスが予期せず止まり(クラッシュ、kill、Mac の再起動、herdr のペインを閉じた)、task-hub が 1 回だけ再開しましたが、再開した実行もまた止まりました。`task log <番号>` で止まったところを見てから Ready に戻します |
| `the run stopped unexpectedly; not resumed: <わけ>` | `task _run` プロセスが止まりましたが、再開しませんでした。わけは、Ctrl-C で止めた(`it was stopped with Ctrl-C`)、worktree が消えた、worktree で誰かがコミットした(`HEAD moved`)、続けるのに要る記録やプロンプトがない、などです。直してから Ready に戻します |
| `the run stopped unexpectedly; could not resume it: <わけ>` | 再開しようとしましたが、起動できませんでした(残ったエージェントが止まらない、herdr のタブが開かない、など)。わけを直してから Ready に戻します |
| `the run stopped unexpectedly` | 実行は終わっていましたが、カードを動かす前に GitHub に届きませんでした。残ったレポートはこのコメントに載っています。再開した実行が終わったあとでも、この理由です |
| `no run of this task on this machine` | カードが手で In progress に移されましたが、このマシンでは何も動いていません。Ready に移してください |
| `could not start: ...` | クローン、worktree の準備、カードの Target repo や Agent に問題があります。`gh auth status` とカードの欄を確認します |
| `could not start: the run did not start in herdr tab ...` | herdr のペインが 16 秒の間に `task _run` を始めませんでした(シェルが立ち上がらない、など)。そのタブを見てから Ready に戻します(戻すと、そのタブは閉じます)。あとからそのタブで実行が始まることはありません |
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

## `queue: N Ready task(s) waiting, all M slots busy`

正常な状態です。M は同時に動かすタスクの数(`[runner] parallel`、既定 5)です。実行中のタスクが終わると、次の確認(`task watch` なら 1 分以内)で開始されます。

## `error: GraphQL: API rate limit exceeded`

GitHub Projects は GraphQL API だけで操作でき、GraphQL には 1 時間あたり 5000 ポイントの利用上限があります
(アカウント全体で共有)。task-hub は必要な欄だけを取るので、`task` 1 回は約 2 ポイント、`task watch` は 1 時間で
約 60 ポイントです。mod や拡張の窓は直近に読んだボードを共有するので、窓が増えてもほとんど増えません
(「ボードの読み取りを共有する」)。上限に届くのは、ほかのツールやエージェントが重い呼び出しを繰り返しているときです。たとえば
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
表示された名前のものを追加してください。追加したら `task list --max-age 0` で読み直します(欄の id は 1 時間取っておくため)。

## PR をマージせずに閉じた

task-hub はカードを動かしません(確認するのは PR がマージされたかどうかだけです)。
やり直すならカードを Ready に戻し、やめるなら Issue を閉じてください。

## 実行中のタスクを止める

herdr のそのタスクのタブでエージェントを停止します(Ctrl-C)。ランナーは最後まで処理を行い、変更された内容を
push してカードを Blocked にします。やめるなら `task done <番号>` です(下の「タスクを取り消す」)。

ペインを閉じても止まりません。予期せず止まった実行(クラッシュ、kill、Mac の再起動、ペインを閉じた)は、次の確認で
task-hub が 1 回だけ自動で再開します。カードは In progress のままで、続きは止まった段階(エージェント、レビュー、
差し戻し、finish)からです。新しいタブ(またはバックグラウンド)で動き、Issue のレポートに `Resumed once at <段階>` の
1 行が入ります。出来事 `resumed` も出ますが、既定では通知しません(`[notify] events` に `resumed` を足せば通知します)。
再開した実行もまた止まったら、`the run stopped unexpectedly again, after resuming once at <段階>` として Blocked になります。

### 黙って止まったコマンド

エージェントの出力が 45 分なく、エージェントが動かしたコマンド(その子孫)も前の確認から CPU を使っていなければ、
`task _run` がそのコマンドを止めます(SIGTERM、10 秒後に SIGKILL)。エージェント自身は止めないので、
コマンドの失敗を受け取って続けます。ログには次の行が出ます。

```text
== watchdog: no output for 45 min and no CPU used by what the agent started: stopping it (4242 sleep)
```

CPU を使って黙っているコマンド(出力しない長いテストやビルド)は止めません。止めたあと(止めるものがなければ 45 分から)
さらに 10 分黙っていて、子孫も CPU を使っていなければ、エージェントも止め(`== watchdog: no output for 55 min: stopping the agent`)、
その場で 1 回だけ再開します(上の予期せず止まった実行の再開と同じ 1 回に数えます)。再開したエージェントも止められると、
カードは Blocked になります。しきい値は設定できません(決定事項 19)。Windows では子孫の CPU が分からないので、watchdog は
何も止めません。

## タスクを取り消す

Issue を閉じるか、`task done <番号>` を実行します。そのタスクの herdr のタブ(またはタスク専用の workspace)を閉じ、worktree を削除し、
カードを Done にします。task-hub の clone の中のブランチ `task/<番号>` も消しますが、GitHub のブランチと PR は残ります。
必要であれば、GitHub 上で PR をクローズしてください。

## 同時実行数の上限を変更する

`~/.config/task-hub/config.ini` の `[runner]` に `parallel = <数>` を書きます(1 以上、既定 5)。次の確認から
その数まで始めます。エージェントの CLI は 1 つで数百 MB のメモリを使うので、性能の低い PC では 1 か 2 にします。
0 や数でない値を書くと、`error: [runner] parallel must be a whole number, 1 or more` で止まります。

## ディスクの整理

worktree と、clone の中のブランチ `task/<番号>` は、タスクが完了すると削除されます。消せなかったときは
`cleanup: task <番号>: ...; trying again at the next check` と表示し、次の確認でやり直します(0.6 より前に完了したタスクの
ブランチは残っていることがあります。`git -C ~/.local/share/task-hub/repos/<owner>/<name> branch --list 'task/*'` で
確かめ、完了済みのものは `git branch -D` で消せます)。`~/.local/share/task-hub/repos/` 内のクローンは次の実行を
速くするために残されており、いつでも削除できます。
