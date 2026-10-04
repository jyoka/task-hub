# Kiro IDE 版のセットアップ

> **はじめて使う人は [kiro-quickstart.md](kiro-quickstart.md) へ。** Kiro IDE でこのリポジトリを開き、チャットに
> 「セットアップして」と言うだけで、このページの手順をインストーラ(`sh kiro/install.sh`)が行います。
> このページは、**インストーラが行うこと** の説明です。中身を知りたいとき、手で入れるとき、うまくいかないときに読みます。

Kiro しか使えない仕事用の Mac で、ターミナルを開かずに task-hub の一周(登録 → Ready → 実行 → 知らせ → レビュー →
マージ)を回すための手順です。

GitHub 側の準備(タスク用リポジトリ、Project の Status と欄)と、動かす用の clone のインストールは
[setup.md](setup.md) と同じです。このページは、その上で Kiro に合わせて変えるところと足すものだけを書きます。
`bin/task` は Kiro でもほかのエージェントでも同じもので、Kiro 用の部品はリポジトリの `kiro/` にあります。

| 部品 | 役割 |
|---|---|
| `kiro/steering/task-hub.md` | `/task` と `/chief` を頼まれたときだけ使う、という約束(steering) |
| `kiro/hooks/task-hub-events.json` と `kiro/task-events-since` | 話しかけたときに、前回からの出来事をチャットの文脈に足すフック |
| `kiro/workflows/task-hub-events.workflow.json` と `kiro/task-events-watch` | 話しかけていないときに出来事を待ち、`/chief` のチャットに届けるワークフロー |
| `kiro/board-extension/` | ボードをサイドバーとステータスバーに出す拡張(VSIX。インストーラは入れません。[10 章](#10-ボードをサイドバーとステータスバーに出す拡張)) |

### インストーラが行うこと

`sh kiro/install.sh` は、次の段階を順に確かめ、済んでいないものだけを行います(何度実行しても安全です)。
このページの各章の手作業は、その段階が行うことの説明です。

| 段階 | 行うこと | このページ |
|---|---|---|
| 1. 前提の確認 | macOS、CPU、git(無ければ情シスへの依頼文で止まる)、GitHub に届くか、システム設定のプロキシ | 1 章 |
| 2. Python | 3.10 以上が無ければ uv を入れ、uv で Python 3.12 を取る | 1 章 |
| 3. gh | 無ければ GitHub Releases の zip をチェックサムで確かめて `~/.local/bin` に置く | 1 章 |
| 4. kiro-cli | あるものを `~/.local/bin/kiro-cli` にリンク。無ければ公式の DMG を `~/Applications` に展開する(**公式の手順ではありません**。公式のスクリプトは管理者権限の要る `/Applications` に入れます) | 1 章 |
| 5. ログイン | gh と kiro-cli(開いたターミナルの案内に沿ってブラウザで承認。git にも gh のログインを使わせる)。ここで止まり、本人がログインしてからもう一度実行する。task-hub は private なので、clone より前に行う | 1 章 |
| 6. task-hub 本体 | `~/.local/lib/task-hub` に clone し(配布する版、つまり一番新しい `kiro-v*` のタグ。2 回目からは新しいタグがあれば切り替える)、`~/.local/bin/task`(その Python で動かす wrapper)と `~/.zprofile` の PATH | 1 章、9 章 |
| 7. ボード | `<you>/tasks`(private)と Project「task-hub」を作り、Status と欄をそろえる | [setup.md](setup.md#github-側の準備1-回だけ) |
| 8. 設定 | config.ini に足りない項目だけを足し、`task list` で確かめる | 2 章 |
| 9. Kiro との連携 | スキルと steering はリンク、フックとワークフローはコピー、Workflows を有効に | 3〜5 章 |
| 10. 常駐(任意) | `--with-launchd` で plist を置き、`--start-launchd` で始める | 6 章 |
| 11. 診断 | `sh kiro/doctor.sh` を呼び、全段階を ○ / × の一覧で出す(何も変えない) | — |

- GitHub と kiro-cli のログインは同じ Terminal の起動経路を使います。システム設定から取得したプロキシと、
  明示したプロキシ・証明書・`GH_CONFIG_DIR` の設定をログインにも渡します。ログイン用ファイルは本人だけが読める
  権限で作り、開始時に自分自身を消します。
- **診断** `sh kiro/doctor.sh` は、いつでも単独で実行できます。× の行の下に、次にすることが出ます。
  判定するのは「インストーラの形か」ではなく「task-hub が動くか」です。[setup.md](setup.md) の手順で手で入れた構成
  (`~/.local/bin/task` が clone の `bin/task` へのリンク、PATH にある kiro-cli、gh 以外のログインで GitHub に届く git、
  説明だけが違うフックのコピー)は、動いていれば ○ にして、その下に「手で入れた構成です」などの注記を出します。
- **アンインストール** `sh kiro/uninstall.sh` は、消すものの一覧を出すだけで、`--yes` を付けると消します。消すのは、
  インストーラが `~/.local/state/task-hub/install-manifest.json` に記録したものだけです。GitHub のボード、ログイン、
  Kiro の settings.json、task-hub のデータ(worktree、ログ)は消しません(ボードの消し方は出力に出ます)。
  Kiro のスキルや steering のリンク先を変えた場合、フックやワークフローのコピーを編集・置換した場合も残します。
  コピーの内容は SHA-256 で記録し、再インストールによる更新にも同じ確認を使います。手動で作ったスキルのリンクは
  新たな削除対象にしません。旧版の記録に SHA-256 がないコピーは、更新前の配布ファイルと完全に同じときに
  識別情報を補ってから更新します。異なるコピーは自動で更新・削除できないため、内容を確認して別の場所に移してから
  再実行してください。kiro-cli のリンクも作成時のリンク先を記録し、付け替えられたものは残します。旧版の記録に
  リンク先がない kiro-cli のリンクは、自動削除せず残します。
- Kiro のチャットで「セットアップして」と言ったときにこれらを実行させる約束は、リポジトリの
  `.kiro/steering/setup.md` にあります(`inclusion: auto`。セットアップの話のときだけ読み込まれます)。

実機ではまだ確かめていないところがあります。入れ終わったら、8 章の「人が実機で確かめること」を順に試してください。

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
- `/chief` の中では、提案への「うん」か、対象を名指しした明示的な依頼(開始・`task done`・マージ)にだけ従う
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

In review、Blocked、replan、Done、slow は、何もしなくても macOS の通知で届きます([operations.md](operations.md#通知llm-なし))。
次の 2 つを入れると、IDE のチャットでも知れます。どちらも `task events --after <番号>` を読むだけで、`task` が
PATH になければ `~/.local/lib/task-hub/bin/task` を使います。

### 話しかけたとき: Prompt Submit のフック

```
mkdir -p ~/.kiro/hooks && rm -f ~/.kiro/hooks/task-hub-events.json && cp ~/.local/lib/task-hub/kiro/hooks/task-hub-events.json ~/.kiro/hooks/task-hub-events.json
```

ワークフローと同じく、リンクではなく **コピー** します(Kiro はフックのシンボリックリンクを読みません。下の「Workflows の watch」の 2)。
task-hub を更新したら、同じコマンドでコピーし直します(`sh kiro/install.sh` を実行し直しても同じです)。

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
2. ワークフローの定義をユーザーの場所 `~/.kiro/workflows/` に **コピー** します(リンクにはしません):

   ```
   mkdir -p ~/.kiro/workflows && rm -f ~/.kiro/workflows/task-hub-events.workflow.json && cp ~/.local/lib/task-hub/kiro/workflows/task-hub-events.workflow.json ~/.kiro/workflows/task-hub-events.workflow.json
   ```

   Kiro は、ワークフローのファイルが許可された場所(`~/.kiro/workflows/` など)の中にあるかを、リンクの先の実体の
   パスでも判定します。シンボリックリンクだと実体が `~/.local/lib/task-hub/kiro/workflows/` にあるので、Recipes に
   出ず、`run_workflow` も拒否されます。コピーしたあとは、Kiro のコマンド「Refresh Recipes」を実行するか、
   新しいチャットを開くと読み直されます。先に `rm -f` するのは、前の手順で作ったリンクが残っていると、`cp` が
   リンク先と同じファイルだとして何もせずに失敗するためです。

   **task-hub を更新したら**(`git -C ~/.local/lib/task-hub pull --ff-only`)、上の同じコマンドでコピーし直し、
   「Refresh Recipes」か新しいチャットで読み直させます。コピーなので、更新しても自動では変わりません。
3. `/chief` 専用のチャットを開いて `/chief` と打ちます。`/chief` は始めるときに `run_workflow` で
   `task-hub-events` を 1 回動かします。

ワークフローの `watch`(`events`)は 60 秒ごとに `kiro/task-events-watch` を動かし、`task events --after` で新しい
出来事を確かめます。待っている間はモデルを使わないので、クレジットを使いません。出来事があれば、次のステップ
(`tell-chief`)が要点をまとめ、`send_message` で `/chief` のチャットに届けます。これは出来事のまとまりごとに
繰り返し、500 回で一時停止します。ワークフローが動いていない、または止まったときは、`/chief` がそう伝え、
返答のたびに確かめる動きに戻ります。

`/chief` を重ねて開いても、古いワークフローは 1 分以内に自分で終わり、出来事は一番新しい `/chief` にだけ届きます
(`/chief` が起動のたびに新しい印を `~/.local/state/task-hub/kiro-chief-token` に書き、印が違う `watch` が終わるため)。
定義はコピーで入れているので、この動きは task-hub を更新したあと `sh kiro/install.sh` を実行してコピーし直してから効きます。

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
5. **マージ**: GitHub で PR を読み、マージします。Issue が閉じ、カードは Done になります。マージするかを決めるのは
   人だけです。IDE から離れずに済ませたいときは、`/chief` に「PR #12 をマージして」「#49 を done にして」と
   名指しで頼めば実行します(頼まれずに自分からマージすることはありません)。

## 8. 人が実機で確かめること

エージェントは IDE の画面を動かせないので、次は人が確かめます。
確かめた日付と IDE の版を書き添えておくと、次に版が上がったときに役立ちます。

これまでに確かめた版: 2026-10-01、Kiro IDE 1.2.4、kiro-cli 2.2.0(以下「2026-10-01 の試験」)。

- [ ] **`/task` が候補に出て動くか**: Kiro IDE のチャットで `/` を打ち、`task` と `chief` が候補に出るか。
  使い捨てのリポジトリ(`<you>/task-sandbox`)について話してから `/task` を呼び、`task new` まで動いて Backlog に
  カードができるか
- [x] **steering がリンクで読み込まれるか**: 2026-10-01 の試験で、`~/.kiro/steering/task-hub.md` へのシンボリック
  リンクが Kiro のセッションに読み込まれていた(リンクで動く)
- [ ] **頼んでいないのに登録しないか**: `/task` と打たずに「この修正、あとでやりたい」のように話したとき、
  エージェントが `task new` や `task start` を実行しようとしないか(steering の約束が効いているか)
- [ ] **フックの出力がチャットに入るか**: 何か 1 つ話しかけたあと、カードを In review か Blocked にする出来事を
  起こし(たとえば使い捨てのタスクを実行する)、もう一度話しかけたときに、エージェントがその出来事に触れるか。
  Hooks の一覧に `task-hub events` が出ているか。2026-10-01 の試験では未確認(`~/.kiro/hooks/task-hub-events.json`
  はシンボリックリンクのままだった。2026-10-02 に、Kiro IDE 1.2.4 はフックのリンクを読まないと分かったので、コピーで入れる)
- [x] **Workflows で出来事が届くか**: 2026-10-01 の試験で確認。
  - 設定 `kiroAgent.workflows.enabled`(IDE 1.2 から)は、ユーザーが手で有効にした
  - ワークフローの定義を **シンボリックリンク** で `~/.kiro/workflows/` に置くと、Recipes に出ず、`/chief` の
    `run_workflow` も「許可された場所なのに拒否される」で失敗した(Kiro が実体のパスで場所を判定するため)
  - **コピー** に替えると、Recipes に出て、`run_workflow` で起動でき、`task done` の Done の出来事が 24 秒後に
    `/chief` のチャットに届いた
- [ ] **重ねて開いた `/chief` の古いワークフローが終わるか**: `/chief` を 2 つのチャットで続けて開き、1 分ほどして
  古い方のワークフローが completed になり(`inspect_workflow`)、次の出来事が新しい方のチャットにだけ届くか
- [ ] **ワークフローが待っている間にクレジットが減らないか**: `/chief` でワークフローを動かしたまま、出来事のない
  時間を置いて、クレジットの残りが変わらないか
- [x] **kiro-cli での実行**: 2026-10-01 の試験で確認。`[check] kiro = kiro-cli whoami` は IAM Identity Center での
  ログインで終了コード 0。kiro-cli での実行(tasks#49)は 68 秒で In review になり、0.65 クレジットが
  `metrics.jsonl` に入った
- [ ] **`kiro -n` で新しいウィンドウが開くか**: `kiro -n ~/.local/share/task-hub/worktrees/<番号>` で、今のウィンドウを
  置き換えずに新しいウィンドウで開くか。開くなら `[ide] open = kiro -n {path}` にして、`task open <番号>` で確かめる。
  2026-10-01 の試験では、`kiro -n` も `task open` も未確認
- [ ] **ボード表示の拡張が動くか**: 10 章の VSIX を入れ、アクティビティバーに task-hub が出るか。カードの並びと
  ステータスバーの数が `task list` と合うか。Dock から起動した Kiro でも「読めない」にならないか。
  1 回目の起動で出ないときは、ウィンドウの再読み込みで出るか(tasks#129 の試作では、1 回目に起動しなかった)
- [ ] **launchd からの無人実行が続くか**: IDE を閉じ、ターミナルも開かずに、スマホからカードを Ready に移して
  In review まで進むか。翌日(ログインし直したあと)も同じように動くか。`kiro-cli whoami` が API キーだけで
  0 になるか、キーチェーンの読み出しで確認のダイアログが出ないか(`~/.local/state/task-hub/watch.err.log` と
  `task log <番号>` で見ます)

## 9. 配布する版を出す

配るのは、開発中の main ではなく、`kiro-v<数字>` のタグを付けた版です。インストーラ(段階 6)は、次のように版を選びます。

- **新しく clone するとき**: origin にある `kiro-v<数字>` のうち、数字が一番大きいもの(`kiro-v10` は `kiro-v9` より
  新しい)を checkout します。タグが 1 つもなければ、既定のブランチ(main)です。
- **2 回目から**: インストーラが入れた clone(manifest の `task-hub` に記録がある、またはタグの上にある)は、
  `git fetch --tags` して、もっと新しい `kiro-v*` があれば切り替えます。結果は「6. task-hub 本体」の行に出ます
  (例: `入れました(kiro-v1 → kiro-v2)`)。
- **ブランチの上の clone を手で入れたとき**(開発用。main を追う clone): 今までどおり `git pull --ff-only` だけで、
  タグには切り替えません。
- **開発者が版を選ぶとき**: `sh kiro/install.sh --ref main` や `--ref kiro-v1`(ブランチかタグ)。その回だけです。
  次に `--ref` なしで実行すると、インストーラが入れた clone は一番新しい `kiro-v*` に戻ります。
- 今の版と、もっと新しい版があるかは、`sh kiro/doctor.sh` の「6. task-hub 本体」の行に出ます(何も変えません)。

版を出す手順:

1. main に、配りたい変更がすべて入っていることを確かめます。
2. 人が、使い捨ての macOS ユーザーで通しの確認をします(下の 7 つ)。テストではなく、本物の Mac と Kiro IDE で
   確かめます。この時点ではタグがまだ無いので、clone は main になります(確かめるのは、これから付ける版と同じ
   コミットです)。
   1. システム設定 →「ユーザとグループ」で **管理者でない** ユーザーを作り、そのユーザーでログインする
   2. Kiro IDE を開き、[kiro-quickstart.md](kiro-quickstart.md) の 1 章どおり「Clone Repository」で
      このリポジトリを開く
   3. チャットで「セットアップして」と言い、止まるたびに案内どおりにログインして「続けて」と言う。管理者パスワードを
      一度も聞かれないことと、かかった時間(30 分以内か)を記録する
   4. 最後の「診断:」がすべて ○ かを見る(画面での操作が残れば、ガイド 4 章のとおりにして「続けて」)
   5. Kiro を再起動し、新しいチャットで `/task` → Backlog にカードができる → Ready に移す → In review と通知まで
      進むか確かめる
   6. 「診断して」で ○ の一覧が出ることを確かめる。次に「アンインストールして」→「はい」と言い、`~/.local/bin`、
      `~/.local/lib/task-hub`、`~/.kiro` のリンクとコピーが消えて、GitHub のボードが残ることを確かめる
   7. ボードを GitHub の画面で消し、使い捨てのユーザーを削除する
3. 確かめたコミット(main)に、次の番号のタグを付けて push します。

   ```
   git tag -a kiro-vN -m "kiro-vN: <この版で変わったこと>" <確かめたコミット>
   git push origin kiro-vN
   ```

   番号は、今ある一番大きい `kiro-v*` の次です(`git ls-remote --tags origin 'kiro-v*'` で見られます)。
4. 同僚は、Kiro のチャットで「セットアップして」ともう一度言うと、新しい版に切り替わります。

**タグは消したり、付け替えたりしません。** 同僚の clone は、手元にあるタグを信じています。付け替えると
`git fetch --tags` が失敗し(古い版のまま進みます)、同じ名前で中身の違う版が出回ります。直したいときは、
直したコミットに次の番号のタグを付けます。

## 10. ボードをサイドバーとステータスバーに出す(拡張)

`kiro/board-extension/` は、task-hub のボードを Kiro IDE のサイドバーとステータスバーに出す拡張です。
Claude Code の mod(`claude/task-board/`)と同じ役割で、`task list` と `events.jsonl`・`metrics.jsonl` の読み方
(`claude/task-board/hooks/parse.ts`、`panel.ts`)も共有しています。インストーラ(`sh kiro/install.sh`)は入れないので、
手で入れます。

- アクティビティバーの「task-hub」に、カードを「要対応 N」(Blocked、In review、wait for merge)、「実行中 N」、
  「待ち N」(Ready)、「Backlog N」の折りたためるグループに分けて出します。Backlog と知らない status の「その他」は
  初めは畳んでいます。空のグループは出しません。
- アイコンの色は状態ごとです(Blocked は赤、In review は黄、wait for merge は緑、実行中は水色)。
- 各行に `#番号`、タイトル、repo 名(owner なし)、待ち先が出ます。要対応のカードには列、実行中のカードには段階
  (`agent`、`review`、`retry`)と「12分 / 普段9分」が出ます。普段を超えたらアイコンが警告色、`bin/task` が遅いと
  判断する時間を超えたらエラー色になります。
- カードの下に判断材料が 1 行出ます。In review は自動レビューの判定、Blocked は理由です。PR があれば、
  押すとブラウザで開く行が足されます。カードにマウスを乗せると、タイトルの全文と詳細が出ます。
- アクティビティバーのアイコンに要対応の件数が出ます(0 なら出ません)。
- 経過時間・判定・理由・PR は `~/.local/state/task-hub/` の `events.jsonl` と `metrics.jsonl` から読みます。
  ファイルがない、読めない、壊れた行があるときは、その分が出ないだけで一覧は出ます。
- ステータスバーに、0 でない数だけ「task: 実行中1 レビュー待ち3 止まり1」のように出します。押すとボードが開きます。
  左端に置いているので、ウィンドウが狭いと後ろ(止まり)から切れて見えることがあります。
- 1 分ごとに読み直します。ビューの上の更新ボタンで、すぐに読み直せます。
- `task list` が失敗したら、空のボードには見せません。ビューに「読めませんでした: 理由」、ステータスバーに
  「task: 読めない (理由)」と出します。
- LLM を使いません。実行するのは `~/.local/bin/task list`(ホームを展開した絶対パス)だけです。
  素の `task` は Ready のカードを開始するので呼びません。
- 使うのは VS Code の拡張 API だけです。VS Code でも動くはずですが、確かめていません。

### VSIX を作る

Node.js 22.18 以上か 23.6 以上が要ります。TypeScript の型を外すのを Node に任せているためです。
依存がないので、`npm install` は要りません。

```
cd ~/.local/lib/task-hub/kiro/board-extension
npm test
npm run package
```

インストーラが入れた clone は `kiro-v*` のタグの版です(9 章)。そのタグに `kiro/board-extension/` がまだなければ、
main を追う開発用の clone で作ります。

`npm run package` は、`out/` にビルドしてから `task-hub-board-<版>.vsix` を `package.json` の隣に書き出します。
`vsce` は使わず、`zip` で固めます(macOS には `/usr/bin/zip` があります)。Node のない Mac では、ほかの Mac で
作った `.vsix` を使えます。

### 入れる

会社の Mac では、入れる前に tasks#129 の「本人が確かめること」(Kiro の版、構成プロファイルの `AllowedExtensions` /
`ExtensionGalleryServiceUrl`、社内規程)を済ませてください。

次のどちらかで入れます。管理者権限は要りません。

- Kiro の拡張ビュー(Extensions)の上にある「…」メニューから「Install from VSIX...」を選び、作った `.vsix` を選ぶ
- ターミナルで `--install-extension` を使う:

  ```
  kiro --install-extension ~/.local/lib/task-hub/kiro/board-extension/task-hub-board-0.1.0.vsix
  ```

入れたあと、アクティビティバーに task-hub が出なければ、コマンド「Developer: Reload Window」で再読み込みします。
task-hub を更新したら、作り直して入れ直します(同じ版なら `kiro --install-extension <vsix> --force`)。
外すときは、拡張ビューでアンインストールするか、`kiro --uninstall-extension jyoka.task-hub-board` を実行します。
