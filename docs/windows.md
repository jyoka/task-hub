# Windows でのセットアップ(はじめての人向け)

このページだけで、Windows の PC に task-hub を入れて、ボードの Ready のカードを自動で始めるところまで進めます。
コマンドはすべて、PowerShell にコピーして貼り付ければ動くように書いています。

WSL(Windows の中の Linux)は使いません。会社の PC で WSL が禁止されていても使えます。

> **以前、AI に頼んで手で Windows に合わせた task-hub を使っていた人へ**
> その版はもう使いません。この手順で入れ直すと、公式の Windows 対応版に切り替わります。
> 手順 4-3 の「古い `task` が残っていないか」の確認だけは、必ず行ってください。

## 目次

1. [できるようになること](#1-できるようになること)
2. [始める前の確認](#2-始める前の確認)
3. [足りないものを入れる](#3-足りないものを入れる)
4. [task-hub を入れる](#4-task-hub-を入れる)
5. [設定ファイルを作る](#5-設定ファイルを作る)
6. [1 件だけ手で動かして確かめる](#6-1-件だけ手で動かして確かめる)
7. [/task と /chief スキルを入れる](#7-task-と-chief-スキルを入れる)
8. [Ready のカードを自動で始める(常駐)](#8-ready-のカードを自動で始める常駐)
9. [更新する、やめる](#9-更新するやめる)
10. [実機で確かめること(要確認事項)](#10-実機で確かめること要確認事項)
11. [困ったとき(エラーと対処)](#11-困ったときエラーと対処)
12. [mac との違いと、対応していないもの](#12-mac-との違いと対応していないもの)

## 1. できるようになること

- ボード(GitHub Project)でカードを Ready に移すと、この PC でエージェント(kiro-cli、Claude Code、Codex)が作業します。
  終わると PR を出し、カードを In review に動かします
- PC を起動してサインインすると、見張りが自動で始まります。PowerShell の画面を開いておく必要はありません
- In review や Blocked になると、Windows の通知で知らせます

かかる時間の目安は 30 分です(足りないソフトを入れる時間は別です)。

### 先に知っておく言葉

| 言葉 | 意味 |
|---|---|
| PowerShell | Windows のコマンドを打つ画面。スタートメニューで「PowerShell」と検索して開きます。この資料のコマンドは、すべてここに貼り付けます |
| ボード | GitHub の Project。カードが Backlog → Ready → In progress → In review → Done と動きます |
| Ready | 「この PC でやってよい」の列。ここに移したカードを task-hub が始めます |
| 常駐 | 画面を開いていなくても、裏で動き続けること。task-hub では `task watch` が 1 分ごとにボードを確かめます |
| `~` と `$HOME` | 自分のユーザーフォルダー(`C:\Users\<自分の名前>`)のことです |

### ボードをまだ作っていない人

GitHub 側の準備(タスク用の非公開リポジトリ、Project の列と欄)は mac と同じです。先に
[setup.md の「GitHub 側の準備」](setup.md#github-側の準備1-回だけ) の 1 と 2 を済ませてください。
すでに `/task` でカードを登録できている人は、準備は済んでいます。

## 2. 始める前の確認

PowerShell を開き、次のコマンドを 1 つずつ貼り付けて、結果を表と比べます。✗ があっても、ここでは直さずに
先に全部確かめます。直し方は手順 3 にあります。

| # | 確かめること | コマンド | ○ の例 | ✗ のとき |
|---|---|---|---|---|
| 1 | Windows の版 | `winver` | Windows 11(10 でも task-hub は動きます) | kiro-cli は Windows 11 で動くとされています。Windows 10 で kiro-cli を使うなら手順 10 で確かめます |
| 2 | PowerShell の機能が制限されていない | `$ExecutionContext.SessionState.LanguageMode` | `FullLanguage` | `ConstrainedLanguage` なら情シスに相談します(手順 11 の「制約付き言語モード」) |
| 3 | git | `git --version` | `git version 2.xx.x.windows.x` | 手順 4 のインストーラが入れます |
| 4 | GitHub CLI | `gh --version` | `gh version 2.xx.x` | 手順 4 のインストーラが入れます |
| 5 | Python 3.10 以上 | `py -3 --version` | `Python 3.12.x` など(3.10 以上) | 手順 4 のインストーラが入れます。`python --version` で Microsoft Store が開くときも、入っていません |
| 6 | GitHub にログイン済み | `gh auth status` | `Logged in to github.com` と、`Token scopes:` の行に `'project'` | 手順 4 のインストーラが、ログインの窓を開きます |
| 7 | エージェント | `kiro-cli whoami`(Claude Code なら `claude --version`) | ログイン中のアカウントが出る | kiro-cli は手順 4 のインストーラが入れ、ログインの窓を開きます。Claude Code、Codex は自分で入れてログインします |

注: kiro-cli は 2.0 から Windows 11 にネイティブ対応しています([Kiro CLI 2.0 の変更履歴](https://kiro.dev/changelog/cli/2-0/))。

## 3. 足りないものを入れる

### ソフトを入れる

git、GitHub CLI(gh)、Python、kiro-cli は、自分で入れる必要はありません。無ければ、手順 4 のインストーラが自分の
フォルダー(`~\.local`)に入れます。管理者権限は使いません(winget や、MSI をふつうに入れるやり方は、入れるときや
消すときに管理者権限を求めることがあるため使いません)。kiro-cli は、Kiro を使わない人(Claude Code、Codex だけの人)
にも入り、ログインを求めます。

ただし、手順 4-1 の `git clone` には git が要ります(インストーラは、取ってきたリポジトリの中にあるため)。git が
無い PC での始め方は、かんたんセットアップ(準備中)で扱います。それまでは、Git for Windows を入れてから始めます。

入れたものは、公開されているファイルを、公開されているチェックサム(SHA-256)で確かめてから置きます。

| 名前 | 置く場所 |
|---|---|
| git(Git for Windows の MinGit) | `~\.local\lib\git` |
| GitHub CLI | `~\.local\bin\gh.exe` |
| Python 3.12(uv で取る) | `~\.local\bin\uv.exe` と、uv の Python の場所 |
| kiro-cli(公式の MSI を、入れずに展開だけする。約 300 MB) | `~\.local\lib\kiro-cli\kiro-cli.exe` |

kiro-cli は、公式の手順(`C:\Program Files\Kiro-Cli` に入れる。管理者権限が要る)で入れてあれば、それを使います。

### ログイン

GitHub と kiro-cli のログインも、手順 4-2 のインストーラが案内します。ログインしていなければ、ログイン用の
PowerShell の窓を開いて止まります。

- **GitHub**: 窓で Enter を押すとブラウザが開きます。窓に出た 8 文字のコード(例 `ABCD-1234`)をブラウザに入れて
  承認します。Project を読み書きする権限(`project`)も一緒に求めます
- **kiro-cli**: 窓でログインの方法を矢印キーで選び、ブラウザで承認します

終わったら窓を閉じて、インストーラをもう一度実行します。続きから進みます。

## 4. task-hub を入れる

### 4-1. task-hub を取ってくる

task-hub は公開リポジトリなので、ログインなしで取れます。ZIP でダウンロードせず、必ず git で取ってきます。
ZIP だと、スクリプトが「インターネットから来たファイル」として止められることがあるためです。

```
git clone https://github.com/jyoka/task-hub.git $HOME\task-hub-setup
cd $HOME\task-hub-setup
```

### 4-2. インストーラを動かす

```
powershell -ExecutionPolicy Bypass -File windows\install.ps1
```

インストーラは次を行います。何度実行しても安全です。管理者権限は使いません。

1. git、Python 3.10 以上、gh、kiro-cli があるかを確かめ、無いものを自分のフォルダーに入れます(手順 3 の表)。
   開いたあとに入ったソフトも見つけます(PowerShell を開き直さなくてかまいません)。入れたものは
   `~\.local\state\task-hub\install-manifest.json` に記録します
2. GitHub と kiro-cli にログインしているかを確かめ、していなければログインの窓を開いて止まります(手順 3 の「ログイン」)
3. 動かす用の task-hub を `~\.local\lib\task-hub` に取ってきます(すでにあれば最新にします)。
   4-1 のフォルダーとは別にするのは、そちらを書き換えても、動いている task-hub が変わらないようにするためです
4. `task` コマンドを `~\.local\bin` に置き、そのフォルダーを PATH(コマンドを探す場所)に足します。
   Git Bash(Windows の Claude Code が使うシェル)用の `task` も、同じ場所に置きます

うまくいくと、次のように出ます(パスは人によって違います)。

```
task-hub をセットアップします(管理者権限は使いません)
1. 前提の確認: 済み(Windows 11 x64、git、GitHub に接続)
2. Python: 済み(C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe を使います)
3. gh: 済み(C:\Program Files\GitHub CLI\gh.exe)
4. kiro-cli: 済み(C:\Program Files\Kiro-Cli\kiro-cli.exe)
5. GitHub のログイン: 済み(you)
5. kiro-cli のログイン: 済み
6. task-hub 本体: 入れました(clone(main 1a2b3c4)、~\.local\bin\task.cmd、~\.local\bin\task、ユーザーの PATH に ~\.local\bin)
7. ボード: 作りました(https://github.com/users/you/projects/1、you/tasks: private の you/tasks、Project you/1、…)
8. 設定: 作りました(~\.config\task-hub\config.ini。task list で確かめました)
9. Kiro との連携: 入れました(~\.kiro\skills\task(ジャンクション)、…。Kiro を再起動すると読み込まれます)
10. 常駐: 飛ばしました(任意です。Ready のカードを自動で始めるときは -Watch を付けて実行します)
診断:
○ 1. 前提の確認: git、GitHub に接続
…
○ 10. 常駐: 使っていません(任意。使うなら -Watch を付けてインストーラを実行します)
ここまで終わりました。
次にすること: Kiro を再起動し(…)、新しいチャットで /task を試してください
```

無いものを入れたときは「入れました」と出ます。最後の `次にすること:` の行に従います。途中で `止まりました。` の行が
出て止まったときも、その下の `次にすること:` に従います。もう一度実行すると、続きから進みます(済んだ段階は「済み」)。

最後の「診断」は、各段階がそろっているかを ○ と × で並べたものです。× の行の下の `→` が次にすることです。
診断だけを、いつでも動かせます(何も変えません)。

```
powershell -ExecutionPolicy Bypass -File windows\doctor.ps1
```

### 4-3. 新しい PowerShell で確かめる

**PowerShell を閉じて開き直します**(PATH の変更は、新しく開いた画面から効きます)。

```
task --version
Get-Command task -All
```

- `task --version` で版(例 `0.6.0`)が出れば成功です
- `Get-Command task -All` の 1 行目の Source が `C:\Users\<自分>\.local\bin\task.cmd` であることを確かめます。
  **以前の手作りの版の `task` が 1 行目に出たら**、その古いファイルを消すか名前を変えます。
  そのあと PowerShell を開き直して、もう一度確かめます

## 5. 設定ファイルを作る

設定ファイルは `~\.config\task-hub\config.ini` です。**手順 4-2 のインストーラが作ります**(段階 7 と 8)。

- ボード: 設定ファイルに `[board]` が無ければ、自分の GitHub に非公開のリポジトリ `<自分>/tasks` と、Project「task-hub」を
  作ります(すでにあれば、それを使います)。列と欄も task-hub に合わせます
- 設定: 無い項目だけを足します(`[board]`、`[runner] agent = kiro`、`[check] kiro = kiro-cli whoami`)。書いてある値は
  変えません。足す前の内容は `config.ini.bak-<日時>` に残します
- 最後に `task list` を動かして、ボードとつながることを確かめます

**すでにあるボードを使うときは**、インストーラの前に `[board]` だけを書いておきます(下の例の 2 行)。そのボードの列と
欄は、足りないものだけを足し、カードはそのままです。

設定を変えるとき(エージェントを変える、性能の低い PC で同時に動かす数を減らす、など)は、メモ帳で開きます。

```
notepad $HOME\.config\task-hub\config.ini
```

書き方の例です。`;` から後ろはメモ(コメント)なので、残しても消しても構いません。

```ini
[board]
project = <GitHub のユーザー名>/<Project の番号>   ; Project の URL の users/<名前>/projects/<番号>
issues = <GitHub のユーザー名>/tasks              ; タスクの Issue を作るリポジトリ

[runner]
agent = kiro                ; 使うエージェント(kiro、claude、codex)
reviewer = agent            ; 実装のあと、同じエージェントがレビューする。いらなければこの行を消す

[check]
kiro = kiro-cli whoami      ; 始める前にログインを確かめる。失敗したら、クレジットを使う前に止まる
```

**性能の低い PC では**、`[runner]` に `parallel = 1`(または 2)を足します。同時に動かすタスクの数で、既定は 5 です。
エージェントの CLI は 1 つで数百 MB のメモリを使うため、5 つを同時に動かすとメモリが足りなくなります。

**保存のしかた**: メモ帳の「ファイル」→「名前を付けて保存」で、「エンコード」を **UTF-8** にして保存します
(「UTF-8 (BOM 付き)」でも読めます)。PowerShell の `>` や `Out-File` で作ると UTF-16 になり、読めません。

変えたら確かめます。

```
task list
```

次のように出れば、ボードとつながっています(カードの数は人によって違います)。インストーラも同じことを確かめています。

```
counts: Backlog=0, Ready=0, In progress=0, In review=0, wait for merge=0, Blocked=0
tasks: 0 open tasks
needs_you: 0 (Backlog to approve, In review, Blocked)
```

`error:` が出たら、手順 11 の「`task` を動かしたとき」を見ます。

### Windows で書き方が違うところ

- **パスはスラッシュ `/` で書きます。** `\` は消えてしまいます。例: `C:/Users/you/tools/agent.exe {prompt}`。
  空白を含むパスは `'...'` で囲みます
- **npm で入れたエージェント**(`codex`、`claude` など)は、名前だけで書けます。task-hub が中身を見て、
  プロンプトが途中で切れない方法で起動します
- **`[setup]`**(作業の前の準備のコマンド)は PowerShell で動きます。書き方は下の「`[setup]` を書くとき」を見ます
- **API キー**(例 `KIRO_API_KEY`)は、ユーザー環境変数に入れます。入れたら、一度サインアウトしてサインインし直します。
  キーは自分のユーザーのレジストリに平文で入るので、共用の PC では入れないでください

  ```
  [Environment]::SetEnvironmentVariable('KIRO_API_KEY', '<ksk_ で始まるキー>', 'User')
  ```

### `[setup]` を書くとき

テストの前に仮想環境などの準備が要るリポジトリだけに書きます。要らなければ書きません。

```ini
[setup]
you/app = uv venv -q .venv
  uv pip install -q -r requirements.txt --python .venv/Scripts/python.exe
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
```

- 2 行目からは、行の頭に空白を入れます(設定ファイルで「前の行の続き」を表す書き方です)
- コマンドレット(`New-Item` など PowerShell のコマンド)が失敗すると、そこで止まります
- プログラム(uv、npm など)が失敗しても、その場では止まらず次の行に進みます。最後に残った終了コードが 0 以外なら、
  最後に失敗にします。その場で止めたい行のあとには `if ($LASTEXITCODE) { exit $LASTEXITCODE }` を書きます
- プログラムに `2>&1` や `2>$null` を付けないでください。エラー出力が 1 行でも出ると、そこで失敗になります
- 準備で作ったファイルは、git が無視するものでなければなりません(uv の `.venv` はそのままで大丈夫です)

## 6. 1 件だけ手で動かして確かめる

常駐させる前に、手で 1 件動かして、PR まで進むかを確かめます。作業先は、壊れても困らない自分のリポジトリにします。

```
task new --title "README に一行足す" --repo <自分>/<リポジトリ> --goal "README.md の最後に「task-hub の動作確認」と一行足す。"
```

`id: 12` のように番号が出ます。その番号で始めます。

```
task start 12
task log 12
```

- `task start` は裏で始めて、すぐ戻ります。PowerShell を閉じても作業は続きます
- `task log 12` で進み具合を見られます。何度でも実行できます
- 数分から十数分で、カードが In review になり、PR ができます。`task list` で状態を確かめます
- うまくいかずに Blocked になったら、`task show 12` で理由を読み、手順 11 を見ます

確かめ終わったら、PR を閉じて、`task done 12` でカードを片付けます。

## 7. /task と /chief スキルを入れる

エージェントとの会話から `/task`(会話をカードにする)や `/chief`(ボードの相談役)を使うためのものです。

**Kiro の分は、手順 4-2 のインストーラが入れます**(段階 9)。`~\.kiro\skills\task` と `~\.kiro\skills\chief` に
ジャンクション(管理者権限の要らないリンク)を作り、`~\.kiro\steering\task-hub.md` をコピーします。入れたら
Kiro を再起動します。すでに自分のスキルのフォルダーがあれば、それは変えません。

Claude Code や Codex でも使うときは、次をまとめて貼り付けます。

```
foreach ($s in 'task', 'chief') {
  foreach ($d in "$HOME\.claude\skills", "$HOME\.agents\skills") {
    New-Item -ItemType Directory -Force $d | Out-Null
    if (-not (Test-Path "$d\$s")) { New-Item -ItemType Junction -Path "$d\$s" -Target "$HOME\.local\lib\task-hub\skills\$s" | Out-Null }
  }
}
```

以前に手でスキルをコピーしていた人は、先にそのフォルダー(例 `~\.kiro\skills\task`)を消してから実行します。
フォルダーがすでにあると、古いまま残るためです。

## 8. Ready のカードを自動で始める(常駐)

4-1 のフォルダーで、`-Watch` を付けてインストーラを実行します。

```
cd $HOME\task-hub-setup
powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch
```

`10. 常駐:` の行に次のどちらかが出ます(`-Watch` を付けないときは `飛ばしました` と出ます)。

| 表示 | 意味 |
|---|---|
| `10. 常駐: 始めました(タスク スケジューラの「task-hub watch」。…)` | タスク スケジューラに登録して、今すぐ始めました(ふつうはこちら) |
| `10. 常駐: 始めました(タスク スケジューラに断られたので(…)、スタートアップ フォルダーに置きました。…)` | 会社のポリシーでタスク スケジューラに登録できなかったので、代わりにスタートアップ フォルダーに置いて、今すぐ始めました |

### 動いているかを確かめる

```
Get-ScheduledTask -TaskName 'task-hub watch' | Select-Object State
Get-Content $HOME\.local\state\task-hub\watch.log -Tail 20
```

- State が `Running` なら動いています(スタートアップ フォルダーに置いた場合、この行はエラーになります。ログだけで確かめます)
- ログの最後に `starting task watch` と `watch: checking https://github.com/... every 60s` が出ていれば正常です
- そのあとは、カードを始めたときやエラーのときだけ書きます。**何もない間は何も増えません**(止まっているわけではありません)
- ログの最後が `error:` なら、1 分ごとに始め直しています。手順 11 を見ます

最後に、ボードで 1 枚のカードを Ready に移します。1 分ほどで In progress になれば完了です。

### 知っておくこと

- サインインのたびに自動で始まります。その直後に PowerShell の窓が一瞬出て、すぐ隠れます
- 見張りが何かで止まっても、1 分後に自分で始め直します
- 常駐から始めた作業は、見張りとは別に動きます。止めるときは、タスク スケジューラの画面で「終了」を押さずに、
  手順 9 の `-Uninstall` を使います(「終了」は、動いている作業まで止めることがあります)
- 止まった作業のカードは、次の確認で `the run stopped unexpectedly` として Blocked になります。Ready に戻せばやり直せます
- task-hub は日本語を正しく扱うために、自分を UTF-8 モード(`PYTHONUTF8=1`)で動かします。エージェントや、
  エージェントが動かす Python のテストも UTF-8 モードになります

## 9. 更新する、やめる

**更新する**(task-hub に新しい版が出たとき): 4-1 のフォルダーを最新にしてから、インストーラをもう一度実行します。
常駐している人は `-Watch` も付けます。動いている作業は止めずに、見張りだけを新しい版で始め直します。

```
cd $HOME\task-hub-setup
git pull
powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch
```

**やめる**: 常駐と `task` コマンドを外します。

```
powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Uninstall
```

- 止めるのは見張りだけです。動いている作業は最後まで動きます
- `~\.local\lib\task-hub`(本体)、`~\.config\task-hub`(設定)、`~\.local\state\task-hub` と `~\.local\share\task-hub`
  (ログと作業フォルダー)は残します。要らなければ手で消します
- GitHub のボードとログインは変えません

## 10. 実機で確かめること(要確認事項)

次は、作った人の手元に Windows の実機がなく、自動テスト(GitHub Actions の Windows)では確かめられなかったことです。
入れ終わったら上から順に試して、結果を task-hub の担当者に伝えてください。伝えるのは、○ か ×、× なら出た表示です。

| # | 確かめること | やり方 | ○ の条件 |
|---|---|---|---|
| 1 | タスク スケジューラに登録できる | 手順 8 | `10. 常駐: 始めました(タスク スケジューラの「task-hub watch」` が出る。× なら、スタートアップ フォルダーに切り替わったか(`スタートアップ フォルダーに置きました`)と、断られた理由も伝える |
| 2 | サインインし直しても始まる | PC を再起動してサインインし、5 分待って手順 8 の「動いているかを確かめる」 | State が Running で、ログに新しい `starting task watch` がある |
| 3 | 窓が出続けない | サインイン直後と、作業中の様子を見る | PowerShell の窓が一瞬で消える。作業中に黒い窓が次々に開かない |
| 4 | 通知が出る | 手順 6 の作業が In review になったとき | 画面の右下に `#12 In review: ...` の通知が出る。出なければ、手順 11 の「通知が出ない」も試す |
| 5 | 本物のエージェントで PR まで進む | 手順 6 | カードが In review になり、PR ができる。使ったエージェント(kiro / claude / codex)も伝える |
| 6 | 日本語が化けない | 手順 6 のタイトルとログ | `task list` と `task log` の日本語が読める。PR の本文も読める |
| 7 | 作業中に見張りを外しても、作業が続く | 作業中(In progress)に `install.ps1 -Uninstall` を実行する | 作業が最後まで進み、In review になる。確かめたら `install.ps1 -Watch` で常駐を戻す |
| 8 | PowerShell の機能が制限されていない | 手順 2 の #2 | `FullLanguage`。× なら情シスへの相談が要る |
| 9 | スキルが使える | エージェントの会話で `/task` と打つ(手順 7 のあと) | `/task` が候補に出て、カードが Backlog にできる |
| 10 | 使用量の記録 | 作業が終わったあと `task stats` | 使ったクレジットが出る(kiro-cli)。出なくても、作業には影響しない |

## 11. 困ったとき(エラーと対処)

まず 4-1 のフォルダーで診断を動かします。足りないものと、次にすることが出ます(何も変えません)。

```
powershell -ExecutionPolicy Bypass -File windows\doctor.ps1
```

### インストールのとき

| 出る表示 | 原因 | 対処 |
|---|---|---|
| `このシステムではスクリプトの実行が無効になっているため…` | `.ps1` を直接実行した | 手順どおり `powershell -ExecutionPolicy Bypass -File windows\install.ps1` の形で実行する |
| `-ExecutionPolicy Bypass` を付けても上の表示が出る | 会社のポリシーで、スクリプトの実行そのものが禁止されている | 情シスに「PowerShell スクリプトを実行したい(ExecutionPolicy を RemoteSigned 以上に)」と相談する |
| `ダウンロードできませんでした` または `GitHub(https://github.com)に届きません` | ネットワークに出られない(会社のプロキシ) | ブラウザで https://github.com が開けるか確かめる。会社のプロキシがあるなら、下の「プロキシ」 |
| `… のチェックサムが合いません … 入れていません` | ダウンロードしたファイルが、GitHub の公開しているものと違う(途中で壊れた、または書き換えられた) | 何も入れていません。時間をおいてもう一度実行する。続くときは担当者に伝える |
| `入れた git が動きません`、`入れた gh が動きません` | 会社のセキュリティ(AppLocker など)が、ユーザーフォルダーの下のプログラムを止めている | 情シスに相談する |
| `この PC の PowerShell は機能が制限されています` | 制約付き言語モード | 表示された依頼文を情シスに送る |
| `Kiro CLI の MSI を展開できませんでした` | MSI の展開(`msiexec /a`)を会社のポリシーが止めている、または空き容量がない | 空き容量(約 1 GB)を確かめて、もう一度実行する。続くときは、情シスに Kiro CLI を公式の手順で入れてもらう(インストーラはそれを使います) |
| `ログインの窓を開けませんでした` | 新しい PowerShell の窓を開けなかった | 表示されたファイルを、エクスプローラーで右クリックして「PowerShell で実行」する |
| `GitHub にログインしていません。開いた窓で…` | ログインの途中 | 開いた窓でブラウザの承認を終え、窓を閉じて、もう一度実行する。窓が見えなければ、タスクバーを見る |
| `環境変数 GH_TOKEN(または GITHUB_TOKEN)があるので、gh ではログインできません` | 以前の設定でトークンを環境変数に入れている | その環境変数を消してサインインし直すか、`project` の権限があるトークンにする |
| `error: could not clone ...` | ネットワークに出られない(会社のプロキシ)、または URL の誤り | ブラウザで https://github.com/jyoka/task-hub が開けるか確かめる。会社のプロキシがあるなら、下の「プロキシ」 |
| `error: could not update C:\Users\...\.local\lib\task-hub` | 本体のフォルダーを手で書き換えた | `git -C $HOME\.local\lib\task-hub status` で変更を確かめる。要らない変更なら `git -C $HOME\.local\lib\task-hub checkout .` で戻してから、もう一度実行する |
| `error: ...task.cmd does not run` | Python か本体のフォルダーが壊れている | 表示された help のコマンドを実行して、出たエラーを担当者に伝える |
| `タスク スケジューラに断られたので(…)、スタートアップ フォルダーに置きました` | 会社のポリシーで、タスク スケジューラが使えない | エラーではありません。スタートアップ フォルダーで常駐します(手順 10 の #1 として伝える) |
| `~\.kiro\steering\task-hub.md は、このインストーラが入れた内容と確認できないので書き換えていません` | そのファイルを手で書き換えた(または以前に手で置いた) | 中身を確かめて別の場所に移してから、もう一度実行する |

### `task` を動かしたとき

| 出る表示 | 原因 | 対処 |
|---|---|---|
| `用語 'task' は、コマンドレット、関数、スクリプト ファイル、または操作可能なプログラムの名前として認識されません` | PowerShell を開き直していない、またはインストールしていない | 開き直す。それでも出るなら、手順 4-2 をもう一度 |
| Git Bash で `task: command not found` | Git Bash を開き直していない | Git Bash を開き直す。`echo $PATH` に `.local/bin` が入っているか確かめる |
| `error: the board is not configured in ~/.config/task-hub/config.ini` | 設定ファイルがない、または `[board]` の書き方の誤り | 手順 5。`project = 名前/番号`、`issues = 名前/リポジトリ` の形になっているか確かめる |
| `error: ~/.config/task-hub/config.ini is not saved as UTF-8` | PowerShell の `>` などで作った(UTF-16 になっている) | メモ帳で開き、「名前を付けて保存」でエンコードを UTF-8 にして保存し直す |
| `error: cannot read GitHub Project ...` | gh にログインしていない、`project` の権限がない、Project の番号の誤り | `gh auth status` を確かめ、`gh auth refresh -s project` を実行する。Project の URL の番号と設定を見比べる |
| `error: the Project is missing: ...` | Project の列や欄が足りない | 表示された名前の列(例 `Blocked`)や欄(例 `Target repo`)を、Project の設定で足す([setup.md](setup.md#github-側の準備1-回だけ)) |
| `error: GraphQL: API rate limit exceeded` | GitHub の 1 時間あたりの利用上限に届いた | 待てば直ります。詳しくは [operations.md](operations.md#error-graphql-api-rate-limit-exceeded) |
| `error: task 12 not found on the board` | 作ったばかりのカードが、GitHub の一覧にまだ出ていない | ブラウザで Project を開き、そのカードを別の列に動かすと、すぐ出ます |
| `error: unknown agent 'xxx'` | 設定やカードの Agent 欄の名前の誤り | 表示された help の名前(`kiro`、`claude`、`codex` など)にそろえる |

### 作業が Blocked になったとき

理由は `task show <番号>` か、GitHub の Issue の最新のコメントに出ます。作業の記録は `task log <番号> --full` で見ます。
直したら、カードを Ready に戻す(または `task start <番号>` を実行する)と、やり直します。

| 理由やログの表示 | 原因 | 対処 |
|---|---|---|
| `could not start: agent "kiro" is not ready: ...` | `[check]` のコマンドが失敗した(ログインが切れている) | `kiro-cli whoami` を手で実行し、切れていれば `kiro-cli login` |
| ログに `agent not found` | エージェントのコマンドが見つからない | `Get-Command kiro-cli` で場所を確かめる。常駐で動かしているなら、エージェントを入れたあとにサインインし直したか確かめる |
| ログに `agent cannot run: ... is a batch file ...` | エージェントがバッチファイル(.cmd / .bat)で、task-hub が中身を読めなかった | 設定の `[agents]` に、そのバッチファイルが動かしている .exe を、`/` 区切りのパスで書く |
| ログに `agent cannot run:` と `The filename or extension is too long`(日本語の Windows では `ファイル名または拡張子が長すぎます`) | プロンプト(Goal や前回のレポート)が長すぎて、Windows のコマンドの長さの上限(約 32,000 文字)を超えた | Goal を短くするか、タスクを分ける |
| `setup failed (exit N), see task log N` | `[setup]` のコマンドが失敗した | `task log <番号> --full` で `== setup:` のあとを読む。作業フォルダー(`task open <番号>` で場所が出る)で、同じコマンドを手で動かして確かめる |
| `setup left files git would commit (...)` | 準備で作ったファイルが、git に無視されていない | そのファイルをリポジトリの `.gitignore` に足すか、`[setup]` を変える |
| `the run stopped unexpectedly` | 作業のプロセスが止まった(PC の再起動やシャットダウン、タスク スケジューラで「終了」を押した) | Ready に戻せば、続きからやり直します |
| `agent exited without a report (exit N)` | エージェントが途中で落ちた、ログインが切れた、またはクレジットを使い切った | `task log <番号> --full` の最後のほうを読む |

ほかの理由は、[operations.md の「カードが Blocked になった」](operations.md#カードが-blocked-になった) にあります。

### 常駐

| 症状 | 確かめること | 対処 |
|---|---|---|
| Ready に移しても始まらない | 手順 8 の「動いているかを確かめる」 | State が Running でなければ、`install.ps1 -Watch` をもう一度実行する |
| watch.log の最後が `error: ...` | その error の内容 | 上の「`task` を動かしたとき」の表で、同じ表示を探す。直せば、1 分以内に自分で始め直します |
| watch.log がない | 一度も始まっていない | `install.ps1 -Watch` をもう一度実行し、出た表示を担当者に伝える |
| `queue: N Ready task(s) waiting, all M slots busy` | 同時に動かせる上限(`[runner] parallel`、既定 5 件)に達している | 正常です。前の作業が終われば始まります |
| サインインし直すと止まっている | タスク スケジューラの登録 | `Get-ScheduledTask -TaskName 'task-hub watch'` でエラーになるなら、`install.ps1 -Watch` をもう一度 |

### 通知が出ない

1. 「設定」→「システム」→「通知」で、通知がオンになっているか確かめます。task-hub の通知は「Windows PowerShell」の
   名前で出るので、その通知も許可されているか確かめます
2. 「応答不可」(Windows 10 では「集中モード」)がオフか確かめます
3. それでも出なければ、手順 10 の #4 として伝えてください。通知が出なくても、作業そのものには影響しません。
   `task list` や GitHub のボードで状態を確かめられます

### 文字化けする

- `task list` などの日本語が化けるときは、Windows Terminal で PowerShell を開くと直ることがあります
- 作業のログ(`task log`)のうち、エージェントが出した日本語だけが化けるのは、エージェント側の出力の文字コードの
  問題です。作業の結果には影響しません

### プロキシ(会社のネットワーク)

`git clone` や `gh` がつながらない、または時間切れになるときは、会社のプロキシを通す必要があるかもしれません
(推測です。環境によります)。情シスにプロキシのアドレスを聞き、ユーザー環境変数に入れてから、サインインし直します。

```
[Environment]::SetEnvironmentVariable('HTTPS_PROXY', 'http://<プロキシのアドレス>:<ポート>', 'User')
```

### 制約付き言語モード

手順 2 の #2 が `ConstrainedLanguage` の PC では、会社の制限で PowerShell の機能の一部が使えません。インストーラ、常駐、
通知、`[setup]` が動かない可能性があります(確かめていません)。情シスに相談するときは、「PowerShell が
ConstrainedLanguage モードで、スクリプトから .NET を使うツールが動かない」と伝えます。

## 12. mac との違いと、対応していないもの

### mac との違い

| こと | macOS | Windows |
|---|---|---|
| `task` の入れ方 | `~/.local/bin/task` へのリンク | `windows\install.ps1` が書く `~\.local\bin\task.cmd`(Git Bash 用に `task` も) |
| `task watch` の常駐 | launchd の plist | タスク スケジューラ(拒否されたらスタートアップ フォルダー)。`install.ps1 -Watch` |
| 作業の見え方 | herdr のタブ、なければ裏で実行 | いつも裏で実行(herdr は Windows にありません)。`task log <番号>` で追う |
| 通知 | herdr か macOS の通知 | Windows の通知(Windows PowerShell 5.1 から出します) |
| `[setup]` のコマンド | `sh` | PowerShell |
| 作業中かの判定 | `ps` | Windows の API で、プロセスのコマンドラインを読む |
| 常駐の環境変数 | launchd の plist に PATH を別に書く | タスク スケジューラは、サインインしたユーザーの環境変数をそのまま使う |

### 自動テストで確かめていること

GitHub Actions の Windows(`windows-latest`)で、`tests/test_windows.py` が次を確かめています。GitHub とエージェントは
偽物(代わりのスクリプト)で、git、作業フォルダー、プロセスは本物です。

- 日本語のタスクが PR まで進むこと(複数行のプロンプトが切れずに届く)
- 作業中の判定(動いている間は In progress のまま、殺すと Blocked)
- `env NAME=値` の置き換え、npm の .cmd(node のスクリプトと .exe の両方)
- PowerShell での `[setup]` と、その失敗で Blocked になること
- メモ帳の BOM 付き UTF-8 の設定ファイルを読めること、UTF-16 のときに直し方を出すこと
- `install.ps1 -Watch` でタスク スケジューラに登録され、見張りが動くこと。Git Bash から `task` が動くこと。
  `-Uninstall` で見張りが止まって外れ、無関係のプロセスは止めないこと

実機でしか確かめられないことは、手順 10 の表にまとめています。

### Windows に対応していないもの

- herdr(作業ごとのタブ)
- Kiro IDE のフック、ワークフロー、かんたんセットアップ(`kiro/` の中身。mac 用です)
- Claude Code の task-board mod
