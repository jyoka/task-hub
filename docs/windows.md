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
| 3 | git | `git --version` | `git version 2.xx.x.windows.x` | 手順 3 |
| 4 | GitHub CLI | `gh --version` | `gh version 2.xx.x` | 手順 3 |
| 5 | Python 3.10 以上 | `py -3 --version` | `Python 3.12.x` など(3.10 以上) | 手順 3。`python --version` で Microsoft Store が開くときも、入っていません |
| 6 | GitHub にログイン済み | `gh auth status` | `Logged in to github.com` と、`Token scopes:` の行に `'project'` | 手順 3 の「GitHub にログインする」 |
| 7 | エージェント | `kiro-cli whoami`(Claude Code なら `claude --version`) | ログイン中のアカウントが出る | エージェントを入れてログインする(下の注) |

注: kiro-cli は 2.0 から Windows 11 にネイティブ対応しています([Kiro CLI 2.0 の変更履歴](https://kiro.dev/changelog/cli/2-0/))。
入れ方は Kiro の公式ドキュメントに従ってください。入れたら `kiro-cli login` でログインし、`kiro-cli whoami` で確かめます。

## 3. 足りないものを入れる

### ソフトを入れる

会社の PC では、ソフトを入れる権限がないことがあります。そのときは、下の表の「名前」を情シスに伝えて入れてもらいます。
自分で入れられるなら、PowerShell で次を実行します(`winget` は Windows に標準で入っているソフト管理ツールです)。

| 名前 | コマンド |
|---|---|
| Git for Windows | `winget install --id Git.Git -e` |
| GitHub CLI | `winget install --id GitHub.cli -e` |
| Python 3.12 | `winget install --id Python.Python.3.12 -e` |

**入れたら、PowerShell をいったん閉じて開き直します。** 開いたままの画面からは、新しく入れたソフトが見えません。
開き直したら、手順 2 の表をもう一度確かめます。

### GitHub にログインする

```
gh auth login
```

質問には次のように答えます(矢印キーで選び、Enter で決定します)。

1. `Where do you use GitHub?` → `GitHub.com`
2. `What is your preferred protocol for Git operations?` → `HTTPS`
3. `Authenticate Git with your GitHub credentials?` → `Yes`
4. `How would you like to authenticate GitHub CLI?` → `Login with a web browser`
5. 画面に出た 8 文字のコード(例 `ABCD-1234`)を控え、開いたブラウザに入力して承認します

続けて、Project を読み書きする権限を足します。同じようにブラウザで承認します。

```
gh auth refresh -s project
```

最後に `gh auth status` を実行します。`Token scopes:` の行に `'project'` が入っていれば完了です。

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

インストーラは次を行います。何度実行しても安全です。

1. git、gh、Python 3.10 以上があるかを確かめます。何も入れません(無ければ入れ方を出して止まります)
2. 動かす用の task-hub を `~\.local\lib\task-hub` に取ってきます(すでにあれば最新にします)。
   4-1 のフォルダーとは別にするのは、そちらを書き換えても、動いている task-hub が変わらないようにするためです
3. `task` コマンドを `~\.local\bin` に置き、そのフォルダーを PATH(コマンドを探す場所)に足します。
   Git Bash(Windows の Claude Code が使うシェル)用の `task` も、同じ場所に置きます

うまくいくと、最後のほうに次のように出ます(パスは人によって違います)。

```
task-hub: python: C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe
task-hub: cloned https://github.com/jyoka/task-hub.git to C:\Users\you\.local\lib\task-hub
task-hub: added C:\Users\you\.local\bin to your PATH (new terminals see it)
0.6.0
task-hub: done. Next: docs/windows.md (config, then `task list`). ...
```

`error:` で始まる行が出て止まったら、手順 11 の「インストールのとき」を見ます。

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

設定ファイルは `~\.config\task-hub\config.ini` です。メモ帳で作ります。

```
New-Item -ItemType Directory -Force $HOME\.config\task-hub | Out-Null
notepad $HOME\.config\task-hub\config.ini
```

「新しいファイルを作成しますか？」と聞かれたら「はい」を押します。次を貼り付けて、`<...>` を自分のものに書き換えます。
`;` から後ろはメモ(コメント)なので、残しても消しても構いません。

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

**保存のしかた**: メモ帳の「ファイル」→「名前を付けて保存」で、「エンコード」を **UTF-8** にして保存します
(「UTF-8 (BOM 付き)」でも読めます)。PowerShell の `>` や `Out-File` で作ると UTF-16 になり、読めません。

保存したら確かめます。

```
task list
```

次のように出れば、ボードとつながっています(カードの数は人によって違います)。

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
リンクの代わりに「ジャンクション」を作ります。管理者権限は要りません。次をまとめて貼り付けます。

```
foreach ($s in 'task', 'chief') {
  foreach ($d in "$HOME\.claude\skills", "$HOME\.kiro\skills", "$HOME\.agents\skills") {
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

最後に次のどちらかが出ます。

| 表示 | 意味 |
|---|---|
| `registered and started the scheduled task 'task-hub watch'` | タスク スケジューラに登録して、今すぐ始めました(ふつうはこちら) |
| `Task Scheduler refused (...); using the Startup folder instead` と `added ... and started it` | 会社のポリシーでタスク スケジューラに登録できなかったので、代わりにスタートアップ フォルダーに置いて、今すぐ始めました |

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
| 1 | タスク スケジューラに登録できる | 手順 8 | `registered and started the scheduled task` が出る。× なら、スタートアップ フォルダーに切り替わったか(`added ... and started it`)も伝える |
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

### インストールのとき

| 出る表示 | 原因 | 対処 |
|---|---|---|
| `このシステムではスクリプトの実行が無効になっているため…` | `.ps1` を直接実行した | 手順どおり `powershell -ExecutionPolicy Bypass -File windows\install.ps1` の形で実行する |
| `-ExecutionPolicy Bypass` を付けても上の表示が出る | 会社のポリシーで、スクリプトの実行そのものが禁止されている | 情シスに「PowerShell スクリプトを実行したい(ExecutionPolicy を RemoteSigned 以上に)」と相談する |
| `error: git is not installed` | git がない、または PowerShell を開き直していない | 手順 3 で入れて、PowerShell を開き直す |
| `error: gh (GitHub CLI) is not installed` | gh がない | 同上 |
| `error: Python 3.10 or later is not installed` | Python がない、古い、または Microsoft Store の偽の `python` しかない | 手順 3 で Python 3.12 を入れて、開き直す |
| `error: could not clone ...` | ネットワークに出られない(会社のプロキシ)、または URL の誤り | ブラウザで https://github.com/jyoka/task-hub が開けるか確かめる。会社のプロキシがあるなら、下の「プロキシ」 |
| `error: could not update C:\Users\...\.local\lib\task-hub` | 本体のフォルダーを手で書き換えた | `git -C $HOME\.local\lib\task-hub status` で変更を確かめる。要らない変更なら `git -C $HOME\.local\lib\task-hub checkout .` で戻してから、もう一度実行する |
| `error: ...task.cmd does not run` | Python か本体のフォルダーが壊れている | 表示された help のコマンドを実行して、出たエラーを担当者に伝える |
| `Task Scheduler refused (...); using the Startup folder instead` | 会社のポリシーで、タスク スケジューラが使えない | エラーではありません。スタートアップ フォルダーで常駐します(手順 10 の #1 として伝える) |

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
| `queue: N Ready task(s) waiting, all 5 slots busy` | 同時に動かせる上限(5 件)に達している | 正常です。前の作業が終われば始まります |
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
