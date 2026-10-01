# Kiro IDE 版のセットアップ

Kiro しか使えない仕事用の Mac で、ターミナルを開かずに task-hub の一周(登録 → Ready → 実行 → 知らせ → レビュー →
マージ)を回すための手順です。計画と背景は [prd-kiro-ide.md](prd-kiro-ide.md) にあります。

GitHub 側の準備(タスク用リポジトリ、Project の Status と欄)と、動かす用の clone のインストールは
[setup.md](setup.md) と同じです。このページは、その上で Kiro に合わせて変えるところと足すものだけを書きます。
`bin/task` は Kiro でもほかのエージェントでも同じもので、Kiro 用の部品はリポジトリの `kiro/` にあります。

| 部品 | 役割 |
|---|---|
| `kiro/steering/task-hub.md` | `/task` と `/chief` を頼まれたときだけ使う、という約束(steering) |
| `kiro/hooks/task-hub-events.json` と `kiro/task-events-since` | 話しかけたときに、前回からの出来事をチャットの文脈に足すフック |
| `kiro/workflows/task-hub-events.workflow.json` と `kiro/task-events-watch` | 話しかけていないときに出来事を待ち、`/chief` のチャットに届けるワークフロー |

実機ではまだ確かめていないところがあります。入れ終わったら、最後の「人が実機で確かめること」を順に試してください。

## 1. 前提

- **Kiro IDE**: グローバルのフック(`~/.kiro/hooks/`)は **1.0.182 から**、Workflows は **1.2 から** です。
  版はメニューの Kiro → About Kiro で確かめます。
- **kiro-cli**: タスクの実行は kiro-cli で動きます。ログイン済みか確かめます:

  ```
  kiro-cli whoami; echo $?
  ```

- **`gh`**: GitHub にログイン済みで、Projects の権限があること([setup.md](setup.md#必要なもの)):

  ```
  gh auth refresh -s project
  gh auth status
  ```

- **Pro 以上のプラン**: 無人で動かす(launchd の `task watch`)には、`KIRO_API_KEY`(`ksk_` で始まる API キー)が
  確実です。API キーは Pro 以上のプランで作れます。クレジットは IDE、CLI、Web で共通なので、task-hub の実行も
  同じクレジットを使います。
- **`kiro` コマンド**: `task open` が worktree を Kiro IDE で開くのに使います。PATH にあるか確かめます:

  ```
  command -v kiro
  ```

  何も出なければ、Kiro の公式ドキュメント(https://kiro.dev/docs/ide/setup/ )の手順で `kiro` を PATH に入れます。
- Python 3.10 以上と git(macOS の開発者ツール)。

インストールは [setup.md](setup.md#インストール) のとおりです:

```
git clone https://github.com/jyoka/task-hub.git ~/.local/lib/task-hub
mkdir -p ~/.local/bin && ln -sfn ~/.local/lib/task-hub/bin/task ~/.local/bin/task
task --version
```

## 2. config.ini

`~/.config/task-hub/config.ini` に、[setup.md](setup.md#github-側の準備1-回だけ) の `[board]` に加えて次を書きます:

```ini
[board]
project = <you>/<番号>        ; Project の URL の users/<you>/projects/<番号>
issues = <you>/tasks

[runner]
agent = kiro                  ; 実行は kiro-cli(kiro-cli chat --no-interactive --trust-all-tools)
reviewer = agent              ; 自動レビューもタスクと同じ kiro で、実装を見ていない新しいコンテキストで動かす
replanner = agent             ; Blocked の仕分けも kiro。クレジットを節約したいなら、どちらも空にする
pass_env = KIRO_API_KEY       ; herdr のペインで動く実行にも渡す変数の名前

[check]
kiro = kiro-cli whoami        ; 始める前に実行し、失敗したらクレジットを使う前に Blocked にする

[ide]
open = kiro {path}            ; task open <番号> で worktree を Kiro IDE で開く
```

- **`reviewer` と `replanner`**: Kiro しかないマシンでは、別のベンダーのモデルで見直すことはできないので、`agent`
  (タスクと同じ kiro を、新しいコンテキストで起動)にします。どちらも kiro-cli を 1 回ずつ余分に動かし、
  クレジットを使います。費用を抑えたいときは、空にするか行ごと消すと、そのしくみは動きません
  ([agents.md](agents.md#自動レビュー))。
- **`[check]`**: `[runner] agent`、`reviewer`、`replanner` のエージェントを、タスクを始める前(worktree を作る前、
  クレジットを使う前)に確かめます。0 以外で終わると、そのコマンドと出力の最後の数行を理由に Blocked にします。
  **`KIRO_API_KEY` だけで(ブラウザでのログインなしに)使うときに `kiro-cli whoami` が 0 で終わるかは確かめていません。**
  キーだけで使うなら、ブラウザでログインしていない状態で、キー(6 章の手順でキーチェーンに入れたもの)を渡して
  0 になるか確かめてから書いてください:

  ```
  KIRO_API_KEY=$(security find-generic-password -s task-hub-kiro-api-key -w) kiro-cli whoami; echo $?
  ```

- **`pass_env`**: herdr のペインで動く実行に、`KIRO_API_KEY` を渡します。値は起動スクリプトに一度だけ書かれ、
  始まった直後に消えます。`[check]` の出力に値が出ても、コメントと出来事では `***` に置き換えます
  ([agents.md](agents.md#始める前の確認と実行に渡す環境変数))。herdr がなければ、実行はもともと `task watch` の
  環境をすべて引き継ぎます。
- **`[ide] open`**: `{path}` は worktree のパス 1 つに置き換わります(シェルは通しません)。新しいウィンドウで
  開く `kiro -n` は Kiro の公式ドキュメントに載っていません。**`kiro -n <フォルダ>` で新しいウィンドウが開くことを
  確かめてから**、`open = kiro -n {path}` にしてください。確かめるまでは `kiro {path}` のままにします。

設定を書いたら、読めているか確かめます(読むだけで、何も始めません):

```
task list
```

## 3. スキル(/task と /chief)

`/task` と `/chief` は、ほかのエージェントと同じスキルフォルダを使います。Kiro のグローバルのスキルの場所
`~/.kiro/skills/` にリンクします:

```
mkdir -p ~/.kiro/skills
for s in task chief; do ln -sfn ~/.local/lib/task-hub/skills/$s ~/.kiro/skills/$s; done
```

ほかのエージェントも同じマシンで使うなら、[setup.md](setup.md#task-と-chief-スキルのインストール) のループで
まとめて入れても同じです(Kiro には `~/.agents/skills/` を経由したリンクができます)。

- **既定のエージェント**では、`~/.kiro/skills/` のスキルが自動で読み込まれ、チャットで `/task`、`/chief` と打って呼べます。
- **カスタムエージェント**では自動で読み込まれません。エージェントの設定の `resources` に `skill://` で足します:

  ```json
  {
    "resources": ["skill://~/.kiro/skills/*/SKILL.md"]
  }
  ```

- Kiro IDE はスキルの引数(`$ARGUMENTS`)を置き換えません。`/task` に添えたいこと(作業先のリポジトリ、
  使うエージェント、やらないこと)は、同じメッセージにふつうの文で書きます。

## 4. steering(頼まれたときだけ使う約束)

`skills/task/SKILL.md` と `skills/chief/SKILL.md` は、`disable-model-invocation: true` で「ユーザーが呼んだときだけ
使う」ことにしています。Kiro のスキルにはこの項目が載っていないので、同じ約束を steering で入れます。
`kiro/steering/task-hub.md` は、次のことを書いています:

- `/task` と `/chief` は、ユーザーが明示的に頼んだとき(`/task`、`/chief` と打った、またはタスクにしてと言った)だけ使う
- タスクを自分から登録(`task new`)、開始(`task start`、引数なしの `task`)、承認しない
- フックが足した出来事は知らせるためのもので、何かを始める合図ではない

グローバルの steering の場所 `~/.kiro/steering/` にリンクします(IDE と CLI の両方で、すべてのワークスペースに効きます):

```
mkdir -p ~/.kiro/steering && ln -sfn ~/.local/lib/task-hub/kiro/steering/task-hub.md ~/.kiro/steering/task-hub.md
```

**`inclusion: always` にした理由。** steering の読み込み方は `always`(毎回)、`auto`(説明文を見て、関係がありそうなときだけ)、
`manual`(`#task-hub` と書いたときだけ)、`fileMatch`(特定のファイルを開いているときだけ)の 4 つです
(https://kiro.dev/docs/steering/ )。この約束が要るのは、モデルが「これはタスクにできそうだ」と自分で判断しかけた
ときで、そのときにこそ読み込まれていなければなりません。`auto` はその判断をモデルに任せ、`manual` と `fileMatch` は
ユーザーやファイルの操作に頼るので、肝心のときに抜けるおそれがあります。中身は数行なので、毎回読み込む
`always` にしても文脈はほとんど増えません。

## 5. フックとワークフロー(出来事をチャットで知る)

In review、Blocked、replan、Done は、何もしなくても macOS の通知で届きます([operations.md](operations.md#通知llm-なし))。
次の 2 つを入れると、IDE のチャットでも知れます。どちらも `task events --after <番号>` を読むだけで、`task` が
PATH になければ `~/.local/lib/task-hub/bin/task` を使います。

### 話しかけたとき: Prompt Submit のフック

```
mkdir -p ~/.kiro/hooks && ln -sfn ~/.local/lib/task-hub/kiro/hooks/task-hub-events.json ~/.kiro/hooks/task-hub-events.json
```

- トリガーは `UserPromptSubmit` です。チャットで送信するたびに `kiro/task-events-since` が動き(LLM は使いません)、
  前回からの出来事を `task-hub: new events since your last message:` に続けて文脈に足します。
- 最初の 1 回は、読んだ位置(`~/.local/state/task-hub/kiro-cursor`)を今に合わせるだけで、何も足しません(過去の出来事は
  知らせません)。
- 失敗しても送信を止めないよう、いつもコード 0 で終わり、1 行の注意だけを出します。
- 手で試すとき: 2 回続けて動かします。1 回目は(初めてなら)何も出さず、2 回目は、その間に出来事があればそれを出します。

  ```
  ~/.local/lib/task-hub/kiro/task-events-since; ~/.local/lib/task-hub/kiro/task-events-since
  ```

`~/.kiro/hooks/` のフックが Kiro の Hooks の一覧に出なければ、IDE の版(1.0.182 以上)を確かめます。

### 話しかけていないとき: Workflows の watch

1. Workflows を有効にします。設定(Settings)で Workflows をオンにするか、`settings.json` に次を足します:

   ```json
   "kiroAgent.workflows.enabled": true
   ```

   設定に Workflows がなければ、まだそのアカウントでは使えません(フックと通知だけで使えます)。
2. ワークフローの定義をユーザーの場所 `~/.kiro/workflows/` にリンクします:

   ```
   mkdir -p ~/.kiro/workflows && ln -sfn ~/.local/lib/task-hub/kiro/workflows/task-hub-events.workflow.json ~/.kiro/workflows/task-hub-events.workflow.json
   ```

3. `/chief` 専用のチャットを開いて `/chief` と打ちます。`/chief` は始めるときに `run_workflow` で
   `task-hub-events` を 1 回動かします。

ワークフローの `watch`(`events`)は 60 秒ごとに `kiro/task-events-watch` を動かし、`task events --after` で新しい
出来事を確かめます。待っている間はモデルを使わないので、クレジットを使いません。出来事があれば、次のステップ
(`tell-chief`)が要点をまとめ、`send_message` で `/chief` のチャットに届けます。これは出来事のまとまりごとに
繰り返し、500 回で一時停止します。ワークフローが動いていない、または止まったときは、`/chief` がそう伝え、
返答のたびに確かめる動きに戻ります。

手で試すとき(1 回目は、今の位置をカーソルにした `idle` を返します):

```
echo '{"cursor": null}' | ~/.local/lib/task-hub/kiro/task-events-watch
```

フックと `/chief` の両方が同じ出来事を拾うことがありますが、`/chief` はワークフローが届けた出来事を繰り返さない
ようにしています。

## 6. launchd で常駐させるとき(Kiro で違うところ)

IDE を閉じていても Ready のカードを始めるには、`task watch` を launchd で常駐させます。plist の作り方、登録、
再起動は [setup.md](setup.md#launchd-で常駐させるターミナルを開いておかない) のとおりです。Kiro では次の 2 点が違います。

### PATH に kiro-cli の場所を入れる

launchd から起動した `task watch` には、ログインシェルの PATH が渡りません。kiro-cli がどこにあるかを確かめ、
そのディレクトリを plist の `EnvironmentVariables` の `PATH` に足します:

```
dirname "$(command -v kiro-cli)"
```

`gh`、`git` の場所(`/opt/homebrew/bin` など)も同じ `PATH` に並べます。

### KIRO_API_KEY は plist に書かず、キーチェーンから読む

plist の `EnvironmentVariables` にキーを書くと、ファイルにキーが平文で残ります。代わりに、macOS のキーチェーンに
入れ、`task watch` を起動するときに読み出すことを勧めます。

1. キーをキーチェーン(ログインキーチェーン)に入れます。最後の `-w` のあとで、キーを聞かれるので貼り付けます
   (コマンドの履歴にキーが残りません):

   ```
   security add-generic-password -a "$USER" -s task-hub-kiro-api-key -w
   ```

2. 読み出せるか確かめます(キーが表示されるので、人のいるところでは実行しないでください):

   ```
   security find-generic-password -s task-hub-kiro-api-key -w >/dev/null && echo ok
   ```

3. plist の `ProgramArguments` を、キーを読んでから `task watch` を起動する形にします(`youruser` は自分の
   ユーザー名に置き換えます)。`EnvironmentVariables` の `PATH` と `HOME` はそのまま残し、`KIRO_API_KEY` は書きません:

   ```xml
   <key>ProgramArguments</key>
   <array>
     <string>/bin/sh</string>
     <string>-c</string>
     <string>KIRO_API_KEY=$(/usr/bin/security find-generic-password -s task-hub-kiro-api-key -w) || { echo "task-hub: no task-hub-kiro-api-key in the keychain" >&amp;2; exit 1; }; export KIRO_API_KEY; exec /Users/youruser/.local/bin/task watch</string>
   </array>
   ```

4. 登録し直します:

   ```
   launchctl bootout gui/$(id -u)/com.task-hub.watch 2>/dev/null; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.task-hub.watch.plist
   launchctl print gui/$(id -u)/com.task-hub.watch | grep -E 'state|last exit'
   ```

キーが読めないと、`task watch` は起動せず、`~/.local/state/task-hub/watch.err.log` に
`task-hub: no task-hub-kiro-api-key in the keychain` が出ます(launchd は間をおいて起動し直します)。
キーを替えたときは、手順 1 を `-U` 付き(`security add-generic-password -U -a "$USER" -s task-hub-kiro-api-key -w`)で
実行し、`launchctl kickstart -k gui/$(id -u)/com.task-hub.watch` で読み直させます。

`task watch` が始めた実行は、この環境(`KIRO_API_KEY` を含む)を引き継ぎます。herdr のペインで動く実行には、
`[runner] pass_env = KIRO_API_KEY` で渡ります。キーチェーンを使えない事情があるときだけ、[setup.md](setup.md) の
とおり plist の `EnvironmentVariables` に入れ、plist を本人だけが読める権限(`chmod 600`)にします。

## 7. 1 日の流れ

1. **登録**: Kiro IDE のチャットで作業の話をし、タスクにしたくなったら `/task` と打ちます。Backlog にカードが
   でき、Issue の URL が返ります。いくつかまとめて頼みたいときは、`/chief` 専用のチャットで話し、提案に
   「うん」と答えます。
2. **Ready**: GitHub の Project の画面(ブラウザ、スマホでも可)で、カードを Ready に移します。常駐している
   `task watch` が 1 分以内に拾い、kiro-cli で実行を始めます。ログインかキーがなければ、クレジットを使う前に
   理由つきで Blocked になります。
3. **知る**: In review や Blocked になると、macOS の通知が届きます。Kiro のチャットに話しかけたときはフックが、
   `/chief` を開いているときはワークフローが、同じ出来事をチャットに届けます。
4. **確かめる**: 手元で動かして確かめたいタスクは、`task open <番号>` で worktree を Kiro IDE で開きます。
   Kiro のチャットで「`task open <番号>` を実行して」と頼むか、Kiro の中のターミナルで実行します。
   Blocked のタスクは、`/chief` に答えを渡して頼むか、Issue の Goal に答えを書き足してカードを Ready に戻します。
5. **マージ**: GitHub で PR を読み、マージします。Issue が閉じ、カードは Done になります。マージは人だけが行います。

## 8. 人が実機で確かめること

エージェントは IDE の画面を動かせないので、次は人が確かめます([prd-kiro-ide.md](prd-kiro-ide.md) の 7 章)。
確かめた日付と IDE の版を書き添えておくと、次に版が上がったときに役立ちます。

- [ ] **`/task` が候補に出て動くか**: Kiro IDE のチャットで `/` を打ち、`task` と `chief` が候補に出るか。
  使い捨てのリポジトリ(`<you>/task-sandbox`)について話してから `/task` を呼び、`task new` まで動いて Backlog に
  カードができるか
- [ ] **頼んでいないのに登録しないか**: `/task` と打たずに「この修正、あとでやりたい」のように話したとき、
  エージェントが `task new` や `task start` を実行しようとしないか(steering の約束が効いているか)
- [ ] **フックの出力がチャットに入るか**: 何か 1 つ話しかけたあと、カードを In review か Blocked にする出来事を
  起こし(たとえば使い捨てのタスクを実行する)、もう一度話しかけたときに、エージェントがその出来事に触れるか。
  Hooks の一覧に `task-hub events` が出ているか
- [ ] **Workflows で出来事が届くか**: `/chief` を開き、`task-hub-events` のワークフローが動いていることを確かめて
  から、話しかけずに出来事を起こし、`/chief` のチャットに知らせが届くか(待っている間にクレジットが減らないか)
- [ ] **`kiro -n` で新しいウィンドウが開くか**: `kiro -n ~/.local/share/task-hub/worktrees/<番号>` で、今のウィンドウを
  置き換えずに新しいウィンドウで開くか。開くなら `[ide] open = kiro -n {path}` にして、`task open <番号>` で確かめる
- [ ] **launchd からの無人実行が続くか**: IDE を閉じ、ターミナルも開かずに、スマホからカードを Ready に移して
  In review まで進むか。翌日(ログインし直したあと)も同じように動くか。`kiro-cli whoami` が API キーだけで
  0 になるか、キーチェーンの読み出しで確認のダイアログが出ないか(`~/.local/state/task-hub/watch.err.log` と
  `task log <番号>` で見ます)
