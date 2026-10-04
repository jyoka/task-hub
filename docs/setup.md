# セットアップ

ボードはマシン(アカウント)ごとに 1 つです。個人用 Mac は個人の GitHub Project、仕事用 Mac は仕事用の
GitHub Project を使います。手順はどちらも同じです。

Kiro しか使えない Mac で、Kiro IDE からターミナルを開かずに使うときは、このページに加えて
[kiro-ide.md](kiro-ide.md) の手順(設定、steering、フック、ワークフロー、launchd の違い)を使います。

Windows では、[windows.md](windows.md) だけで進められます(インストーラ、タスク スケジューラでの常駐、エラーと対処)。

## 必要なもの

- Python 3.10 以上(`python3 --version`)と git が入った macOS
- GitHub にログイン済みの `gh` で、Projects の権限があること:

  ```
  gh auth refresh -s project
  gh auth status          # Token scopes に project が含まれていること
  ```

- ログイン済みのエージェント CLI が 1 つ以上: `claude`、`codex`、`pi`、`kiro-cli`。[agents.md](agents.md) を参照してください
- 任意: 起動中の herdr。あると、各実行が herdr サイドバーに専用のワークスペースを持ちます。
  herdr がない場合、実行はバックグラウンドで行われ、`task log <id>` で進行を追います
- 任意: `fzf`。`task start` で矢印キーの選択リストを使うためのものです(ない場合は番号付きメニュー)

## 0.4 から 0.5 に上げるとき

Project にテキスト欄 **Base branch** を追加してください(下の「GitHub 側の準備」の 2)。追加するまで、`task` は
`the Project is missing: text field "Base branch"` と表示して止まります。ターミナルからも追加できます:

```
gh project field-create <Project の番号> --owner <you> --name "Base branch" --data-type TEXT
```

## インストール

動かす用の clone を、開発用の clone とは別に作ります。`task` は実行のたびに、リンク先の `bin/task` と
`worker/*.md` を読みます。開発用の clone にリンクすると、そこでブランチを切り替えるたびに、実行中の
タスクボードが使うコードまで変わってしまいます(マージ前のコードで本物のタスクが動く)。

```
git clone https://github.com/jyoka/task-hub.git ~/.local/lib/task-hub
ln -sfn ~/.local/lib/task-hub/bin/task ~/.local/bin/task       # ~/.local/bin must be on PATH
task --version
```

更新は、PR をマージしたあとにこの clone で pull するだけです。`task watch` を動かしているなら、止めてから
起動し直します(実行中のタスクは、始めたときのコードのまま最後まで動きます)。何が変わったか、更新で何が要るかは
[リリースノート](https://github.com/jyoka/task-hub/releases)に書いています([release.md](release.md))。

```
git -C ~/.local/lib/task-hub pull --ff-only
```

Kiro IDE を使っているなら、pull のあとにフックとワークフローの定義をコピーし直します(リンクではなくコピーで
入れているため、pull だけでは変わりません。[kiro-ide.md](kiro-ide.md#5-フックとワークフロー出来事をチャットで知る)):

```
rm -f ~/.kiro/hooks/task-hub-events.json && cp ~/.local/lib/task-hub/kiro/hooks/task-hub-events.json ~/.kiro/hooks/task-hub-events.json
rm -f ~/.kiro/workflows/task-hub-events.workflow.json && cp ~/.local/lib/task-hub/kiro/workflows/task-hub-events.workflow.json ~/.kiro/workflows/task-hub-events.workflow.json
```

task-hub 自体を開発するときは、別の場所に clone して、そこでテストを実行します(`python3 -m unittest discover -s tests -v`)。

## GitHub 側の準備(1 回だけ)

1. **タスク用の非公開リポジトリを作ります。** タスクの Issue はすべてここに作られます。

   ```
   gh repo create <you>/tasks --private
   ```

2. **GitHub Project を用意します**(既存のものでも構いません)。Project の設定で次を追加してください。
   - **Status** 欄: GitHub のかんばん(Kanban)テンプレートで作った Project には `Backlog`、`Ready`、`In progress`、
     `In review`、`Done` が最初からあります。そこに **`Blocked`** を 1 つ追加します(大文字小文字は区別しません)。
     任意で **`wait for merge`** も追加できます(レビュー済みでマージ待ちの列。無くても動きます)
   - テキスト欄 **Target repo**、**Agent**、**Base branch** を追加します(Target repo は作業先リポジトリ `owner/name`、
     Agent は使うエージェント名、Base branch は作業を始めるブランチで、Agent と Base branch は空でも構いません。
     `Repo` という名前は GitHub の予約語なので使えません)
   - Board 表示にして、列を Status でグループ化します
   - Workflows は **「Item closed」(Status を Done にする)だけを有効**にします。無効のままのことがあるので必ず確認します。
     ほかの Status を変えるワークフロー(「Item added to project」「Pull request linked to issue」「Pull request merged」)は
     **無効**にします。task-hub が付けた Status を上書きしてしまいます(実際に、PR を出した直後に Backlog に、マージ後に
     In progress に戻されました)。「Auto-close issue」(カードを Done にすると Issue を閉じる)は有効でも構いません

   足りないものがあると、`task` がそれを名前で教えてくれます。

3. **設定ファイル** `~/.config/task-hub/config.ini` を作ります:

   ```ini
   [board]
   project = <you>/2          ; Project の URL の users/<you>/projects/<番号>
   issues = <you>/tasks

   [runner]
   agent = claude             ; このマシンのデフォルトエージェント
   reviewer = agent           ; 任意: 実装後の自動レビュー。agent = タスクと同じエージェント、名前で固定も可
   replanner = agent          ; 任意: エージェントが Blocked で止まったときの仕分け(コメントだけ)
   ```

   `reviewer` を空にするか省略すると、自動レビューは行いません。有効にすると、エージェントの作業後、PR を出す前に
   reviewer が差分を読み、必要なら 1 回だけ実装エージェントに差し戻します。

   テストに API キーなどが要るリポジトリは、`[env]` に書いたファイルを実行のたびに worktree のルートへコピーできます
   (task-hub は自分用の clone で作業するので、手元のチェックアウトの `.env` はそのままでは届きません):

   ```ini
   [env]
   ; 作業先リポジトリ = コピーするファイル(複数ならカンマ区切り)
   ; そのまま書くと worktree のルートに同じ名前で、「-> 場所」を付けるとその場所に置きます
   jyoka/aica_ra_a2a_poc = ~/AIprogramming PJ/ai-CA_RA-A2A-PoC/.env, ~/AIprogramming PJ/ai-CA_RA-A2A-PoC/voice-agent/.env -> voice-agent/.env
   ```

   置き場所は worktree の中の相対パスで、外を指すもの(`../`、絶対パス)や、同じ場所を 2 回書いたものは止めます。

   テストに仮想環境などの準備が要るリポジトリは、`[setup]` に準備のコマンドを書けます。実行のたびに、`[env]` の
   コピーのあと、エージェントを起動する前に worktree で実行します(出力はそのタスクのタブと `task log` に出ます)。
   複数行に分けて書け、どこかの行が失敗するとそこで止まり、エージェントを起動せずに Blocked にします。

   ```ini
   [setup]
   ; uv は 2 回目から、仮想環境 1 つを 1 秒未満で作り、ディスクもほとんど使いません(brew install uv)
   jyoka/aica_ra_a2a_poc = uv venv -q voice-resume/.venv
     uv pip install -q -r voice-resume/requirements.txt --python voice-resume/.venv/bin/python
   ```

   準備で作ったファイルは、git が無視するものでなければなりません。無視されないファイルが残ったら(PR に入って
   しまうため)、エージェントを起動せずに Blocked にします。uv の `.venv` は中に `.gitignore` を持っているので
   そのままで通ります。設定ファイルでは ` ;` と ` #` のあとがコメントになるので、コマンドをつなぐときは `&&` か
   改行を使います。

   コピーしたファイルはコミットしません。ファイルがない、またはリポジトリで追跡されている名前のときは、開始せずに
   Blocked にします。書いたリポジトリのエージェントは、そのキーで実際に API を呼べる(費用が出る)ことに注意してください。

   In review や Blocked などの出来事は、herdr か macOS の通知で知らせます(LLM は使いません)。止めたいとき、
   出来事を絞りたいときは `[notify]` に書きます([docs/operations.md](operations.md#通知llm-なし)):

   ```ini
   [notify]
   events = In review, Blocked   ; 既定は In review, Blocked, replan, Done, slow。空にすると通知しない
   ```

   IDE でタスクの worktree を開きたいときは、`[ide]` に開くコマンドを書きます。`task open <番号>` がそのタスクの
   worktree(`~/.local/share/task-hub/worktrees/<番号>`)を、このコマンドで開きます。`{path}` はシェルを通さず、
   worktree のパスを 1 つの引数として置き換えます(`[agents]` の `{prompt}` と同じ扱い):

   ```ini
   [ide]
   open = code {path}         ; VS Code。kiro {path}、cursor {path}、idea {path} なども可
   ```

   `[ide] open` を空にするか省略すると、`task open` は何も起動せず、worktree のパスを表示するだけです。worktree が
   ない(このマシンで実行していない、または後片付け済み)ときは、理由を出して失敗します。

   たとえば、Kiro しかない仕事用 Mac では `agent = kiro` にして、`kiro-cli whoami` でログイン済みか確認します
   (実行中にエージェントが自分でログインすることはできません)。無人で動かす(launchd の `task watch`)なら、
   Pro 以上のプランの API キー(`ksk_` で始まる)を `KIRO_API_KEY` に入れ、herdr のペインの実行にも渡します:

   ```ini
   [runner]
   agent = kiro
   pass_env = KIRO_API_KEY    ; herdr のペインで動く実行にも渡す環境変数の名前(カンマか空白区切り)

   [check]
   kiro = kiro-cli whoami     ; 例。始める前に実行し、失敗したらエージェントを起動せずに Blocked
   ```

   task-hub は各タスクを始める前に `[check]` のコマンドを実行し、失敗したらクレジットを使う前に、そのコマンドと
   出力の最後の数行を理由にしてカードを Blocked にします。`[check]` に書いたエージェントだけを確認します(組み込みの
   既定はありません)。`KIRO_API_KEY` だけのときに `kiro-cli whoami` が成功するかは未確認です。**API キーだけで使う
   場合は、先に手で `kiro-cli whoami; echo $?` が 0 になるか確かめてから** `[check]` に書いてください。詳しくは
   [agents.md](agents.md#始める前の確認と実行に渡す環境変数) を参照してください。launchd から動かすときは、
   キーを平文でファイルに残さないよう、macOS のキーチェーンに入れて起動時に読み出します。手順は
   [kiro-ide.md](kiro-ide.md#kiro_api_key-は-plist-に書かずキーチェーンから読む) にあります。キーチェーンを使えないときの
   代わりとして plist の `EnvironmentVariables` に入れることもできますが、その plist はほかの人が読めない権限にしてください。

## /task と /chief スキルのインストール

同じスキルフォルダがすべてのエージェントで使えます。各エージェントがスキルを探す場所にリンクしてください:

```
for s in task chief; do
  ln -sfn ~/.local/lib/task-hub/skills/$s ~/.claude/skills/$s    # Claude Code
  ln -sfn ~/.local/lib/task-hub/skills/$s ~/.agents/skills/$s    # Codex, Pi
  ln -sfn ../../.agents/skills/$s ~/.kiro/skills/$s              # Kiro
done
```

呼び方はエージェントごとに違います(各エージェントの公式ドキュメントで確認、2026-09-27)。

| エージェント | 呼び方 | 補足 |
|---|---|---|
| Claude Code | `/task`、`/chief` | 会話で「タスクにして」と頼んでも `/task` が動きます。`/chief` は打ったときだけです |
| Pi | `/skill:task`、`/skill:chief` | Pi はスキルを `/skill:<名前>` で呼びます。入れたばかりなら `/reload` |
| Codex | `$task`、`$chief`(または `/skills` から選ぶ) | スキルの `agents/openai.yaml` で、頼まれたときだけ使うようにしています |
| Kiro | `/task`、`/chief` | 既定のエージェントでは自動で読み込まれます。カスタムエージェントでは `resources` に `skill://` で足す必要があります |

`/chief` が出来事で自分から知らせてくるには、終わったときにエージェントを起こすバックグラウンド実行が要ります。

- **Claude Code**: そのまま動きます。`/chief` は Monitor で `task events --next --digest` のループを常駐させ、出来事ごとに
  1 回だけ起きます(Monitor が切れたら、最後の `next:` の位置から張り直すので、その間の出来事も落としません。
  `task` が失敗して見張りが止まったときは張り直さず、1 行で知らせます)。
- **Pi**: 標準ではバックグラウンド実行がないので、task-hub の拡張機能を入れます。`/chief` が `task_events_watch` を
  1 回呼ぶと、以後の出来事がメッセージとして届き、Pi を起こします。

  ```
  ln -sfn ~/.local/lib/task-hub/pi/task-events.ts ~/.pi/agent/extensions/task-events.ts
  ```

- **Kiro IDE**: Workflows(IDE 1.2 から。設定の `kiroAgent.workflows.enabled` で有効にします)の `watch` を使います。
  ワークフローの定義 `kiro/workflows/task-hub-events.workflow.json` を入れると、`/chief` が始めるときにそれを動かし、
  `kiro/task-events-watch` が 60 秒ごとに `task events --after` で新しい出来事を確かめます(待っている間はモデルを
  使わず、クレジットを使いません)。出来事があれば、次のステップが要点を `/chief` のチャットに届けます。
  ワークフローが動いていなければ、`/chief` は今までどおり返答のたびに確かめます。Kiro IDE 1.2.4 で、コピーで
  入れたときに出来事が `/chief` に届くことを確かめました(2026-10-01)。詳しい手順は
  [kiro-ide.md](kiro-ide.md#5-フックとワークフロー出来事をチャットで知る) にあります。

  ワークフローの定義は、リンクではなく **コピー** で入れます。Kiro は実体のパスで許可された場所の中にあるかを
  判定するので、リンクでは Recipes に出ず、`run_workflow` も拒否されます。task-hub を更新したらコピーし直します。

  ```
  mkdir -p ~/.kiro/workflows && rm -f ~/.kiro/workflows/task-hub-events.workflow.json && cp ~/.local/lib/task-hub/kiro/workflows/task-hub-events.workflow.json ~/.kiro/workflows/task-hub-events.workflow.json
  ```

- **Codex**: 確かめていません。起こせない場合、`/chief` は返答のたびに `task events` で新しい出来事を確かめます
  (あなたが話しかけるまで気づきません)。

`/chief` は総指揮のエージェントです。作業している herdr の workspace のペインで、エージェントを起動して `/chief` と
打つと、ボードの状況を伝え、何かが起きるたびに知らせ(出来事を裏で見張る)、話した作業を
タスクに分けて提案します。登録と開始は、あなたが「うん」と答えたときだけです。マージ・`task done` は自分からはせず、
あなたが対象を名指しして頼んだとき(「PR #12 をマージして」「#49 を done にして」)だけ実行します。マージの前に競合や
draft でないかを確かめ、マージできなければ理由を伝えます。
頼んだタスクはその workspace のタブで動き、In review になると自分で閉じます。起きたことを自分から知らせるには、
裏で監視を続けられるエージェントが要ります(上記)。

`/chief` は起こされるたびに会話全体を読み直すので、費用は会話の長さでほぼ決まります。ほかの作業とは別の
`/chief` 専用のセッションで動かし、会話が長くなったら閉じて `/chief` を開き直してください(状態はボードにあるので
失うものはありません)。要約と取り次ぎだけなので、安いモデル(例: Opus 5.5)で足ります。出来事は判断用の要点
(`--digest`)で知らせ、`task show --full` はあなたに聞かれたときだけ読みます。2026-09-27 の実測では、別の作業と
同じ長い会話で動かしたセッションが 1 回の呼び出しあたり約 $0.17、専用のセッションが約 $0.03 でした。

### ボードを見るだけなら(Claude Code の task-board mod)

`claude/task-board/` は、ボードをステータスライン(「task: 実行中1 レビュー待ち3 止まり1」)とペインに出す
Claude Code の mod です。`/task-board` でペインを開くと、「要対応」(Blocked → In review → wait for merge)と
「実行中」、「待ち」(Ready)、「Backlog」を枠で囲んで、列ごとの色で出します。見出しの ▸ / ▾ で、どのグループも番号だけの
1 行に畳んだり開いたりでき、次のセッションでも覚えています(初めは Kiro 版と同じく、Backlog と知らない status の
「その他」だけ畳んでいます)。各カードには repo のタグと待ち先
(`waits_for`)が付き、実行中のカードには段階(`review` など)と経過時間 / 普段の時間、In review には判定と PR のリンク、
Blocked には理由が 1 行出ます。

一覧の上には船の絵が出ます(人間が船長、エージェントが乗組員)。実行中のカードは甲板の乗組員で、段階で姿が変わります
(`agent` はハンマー、`review` は虫眼鏡、`retry` は汗)。In review と wait for merge は甲板の木箱で、2 個から船が傾き、
4 個以上で大きく傾きます。Blocked があるとマストに SOS の旗が立ち、乗組員が「?」を出して座り込みます。Ready は桟橋で
待ちます。terminal ではドット絵(波と手が小さく動きます)、desktop では文字の絵です。絵の下の `#番号` にポインタを
乗せると、カードのタイトルが出ます。下の「船を隠す」ボタンで隠せて、次のセッションでも覚えています。

一覧の下には実績のバッジが並びます(retry なしの pass が続いた、1 日に何件 In review にした、エージェントごとの初タスク、
調べものの件数、普段の半分以下の時間で In review など)。解除した瞬間にトーストが 1 回だけ出ます。判定に使うのは
`metrics.jsonl` だけです。

起動するときに読み込みます:

```
claude --plugin-dir ~/.local/lib/task-hub/claude/task-board
```

- Claude Code 専用です(`claude-code` の API を使います)。Kiro、Codex、Pi では動きません。Kiro IDE では、同じ表示の拡張
  ([kiro-ide.md](kiro-ide.md#10-ボードをサイドバーとステータスバーに出す拡張))を使えます。
- LLM を使いません。1 分ごとに `task list` を実行して表示するだけなので、費用はかかりません。
- 実行するのは `$HOME/.local/bin/task list` だけです。素の `task` は Ready のカードを開始するので呼びません。
- 経過時間・判定・理由は、手元の `~/.local/state/task-hub/events.jsonl` と `metrics.jsonl`(と `config.ini` の `[runner] agent`)を読むだけで出します。LLM も GitHub も使いません。ファイルがないときや 4 MiB を超えるときは、その部分が出ないだけです。

mod の API は early access で、Claude Code のリリースごとに変わることがあります(Claude Code 2.1.289 で確認、
2026-10-04)。読み込むと `.claude-plugin/types/` に型が書き出されますが、コミットしません(`.gitignore` 済み)。

### ほかのスキルからボードに Issue を作るとき(to-issues など)

Matt Pocock の `to-prd` / `to-issues` のように Issue を作るスキルは、そのままだと `gh issue create` で作るので、
Target repo も前後関係のリンクも付きません。[issue-tracker.md](issue-tracker.md) に、ボードに作るときの手順
(タスクは `task new --blocked-by`、PRD はボードに載せない普通の Issue)をまとめてあります。スキルの
「issue tracker に publish する」手順の先頭に、これを読むよう 1 行足してください。例(to-issues の「5. Publish」の直後):

```
If the issues go to the user's task-hub board (the `[board] issues` repo in ~/.config/task-hub/config.ini),
follow ~/.local/lib/task-hub/docs/issue-tracker.md instead of creating them with `gh issue create`.
```

スキルを更新すると、この 1 行は消えることがあります。消えても、本文の `Blocked by` に書かれた開いたカードは
task-hub が開始を待たせるので、前後関係を無視して並行に始まることはありません([task-format.md](task-format.md))。

## Ready のカードを自動で始める

`task watch` を動かしておくと、1 分ごとにボードを確認し、Ready のカードを(同時 5 つまで)始めます。外出先で
スマホからカードを Ready に移すだけで、Mac が起きていれば作業が始まります。`task watch` を動かしていないときは、
`task` を実行したタイミングで始まります。

動かし方は 2 通りあります。どちらか一方を選びます。

### herdr のペインで動かす

herdr のペインを 1 つ用意して、次を動かしたままにします:

```
task watch
```

出力をそのまま目で追えるのが利点です。ターミナルやペインを閉じると止まるので、IDE 中心で作業していて
ターミナルを開いたままにしないなら、次の launchd での常駐を選びます。

### launchd で常駐させる(ターミナルを開いておかない)

macOS のユーザーエージェント(launchd)に登録すると、ログインしている間はずっと `task watch` が動き、落ちても
自動で立ち上がり直します。ターミナルや herdr のペインを開いておく必要はありません。

`~/Library/LaunchAgents/com.task-hub.watch.plist` を次の内容で作ります(`youruser` は自分のユーザー名に、
パスは自分の環境に合わせて置き換えます):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.task-hub.watch</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/youruser/.local/bin/task</string>
    <string>watch</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/Users/youruser/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key>
    <string>/Users/youruser</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/Users/youruser/.local/state/task-hub/watch.out.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/youruser/.local/state/task-hub/watch.err.log</string>
</dict>
</plist>
```

- **`RunAtLoad`** は登録した瞬間とログインのたびに起動し、**`KeepAlive`** は落ちても立ち上げ直します。
- **`StandardOutPath` / `StandardErrorPath`** に `task watch` の出力とエラーを書き出します。上の例では
  実行ログと同じ `~/.local/state/task-hub/` に置いています(このディレクトリは `task` が使うので通常はすでに
  あります。なければ `mkdir -p ~/.local/state/task-hub` で作ります)。個々のタスクのエージェント出力はこれとは別に
  `~/.local/state/task-hub/logs/<番号>.log`(`task log`)に残ります。
- **`EnvironmentVariables` の `PATH`** が要です。launchd から起動したプロセスの PATH は最小限で、ログインシェルの
  `.zshrc` などは読まれません。`task` 自身に加えて、それが呼び出す `git`、`gh`、エージェントの CLI(`claude`、
  `kiro-cli` など)、Homebrew で入れたコマンドが見えるように、それらの置き場所をすべて `PATH` に並べます。
  上の例は Apple Silicon の Homebrew(`/opt/homebrew/bin`)を含めています。Intel Mac なら `/usr/local/bin`、
  エージェントの CLI を別の場所(`~/.local/bin` や `/opt/homebrew/bin` 以外)に入れているならそのディレクトリも
  足します。自分の対話シェルでの `echo $PATH` を参考にすると確実です。`gh` がログイン情報を読めるよう `HOME` も
  渡しています。

登録・停止・再起動は `launchctl` で行います(`gui/$(id -u)` は自分のログインセッションを指します):

```
# 登録して起動する
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.task-hub.watch.plist

# 動いているか確認する
launchctl print gui/$(id -u)/com.task-hub.watch

# 止めて登録も外す
launchctl bootout gui/$(id -u)/com.task-hub.watch

# その場で再起動する(plist を書き換えたあとや、更新後に効かせるとき)
launchctl kickstart -k gui/$(id -u)/com.task-hub.watch
```

plist を書き換えたら、`bootout` してから `bootstrap` し直すと確実です(`kickstart -k` はプロセスを入れ替える
だけで、plist の変更を読み直したいときは登録し直します)。

**task-hub を更新したとき。** 動かす用の clone を pull したら(`git -C ~/.local/lib/task-hub pull --ff-only`)、
常駐している `task watch` を再起動して新しいコードを読ませます(Kiro IDE の Workflows を使っているなら、
[インストール](#インストール) のとおりワークフローの定義もコピーし直します)。herdr のペインで動かしているときに
止めてから起動し直すのと同じで、launchd では次のどちらかです(実行中のタスクは、始めたときのコードのまま最後まで
動きます)。

```
launchctl kickstart -k gui/$(id -u)/com.task-hub.watch
# または
launchctl bootout   gui/$(id -u)/com.task-hub.watch
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.task-hub.watch.plist
```

**herdr のタブと通知はどうなるか。** launchd から動かした `task watch` が始めたタスクは、watch のペインが
ないので、そのタスクの置き場所は「登録時に記録された workspace」→「そのリポジトリの checkout を開いている
ペインがある workspace」→「タスク専用の workspace を新しく作る」の順で決まります(herdr のペインで動かした
場合も、`task watch` が始めたタスクは watch の場所には置かないので、扱いは同じです。README の
「見え方と、手元に残るもの」と [operations.md](operations.md#実行の様子を見る) を参照)。通知は、実行が
終わったプロセス自身が出します。herdr が動いていれば herdr の通知、動いていなければ macOS の通知
(`osascript`)になるので、launchd から動かしていても In review や Blocked は届きます([operations.md](operations.md#通知llm-なし))。

## 初回の実行

まずは使い捨てのリポジトリで試してください:

```
gh repo create <you>/task-sandbox --private --add-readme
task new --title "Add hello.txt" --repo <you>/task-sandbox \
  --goal "Add hello.txt at the repo root containing 'hello'. Acceptance: the file exists."
```

Project に Backlog のカードができます。それを Ready に移すと、`task watch`(または `task`)が拾って
"task 1: Add hello.txt" という herdr ワークスペースで実行します。終わるとカードは In review に移り、Issue に
レポートのコメントが付き、ブランチ `task/1` の PR ができています。PR をマージすると Issue が閉じ、カードは Done になります。
