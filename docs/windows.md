# Windows でのセットアップ

`bin/task` は Windows でもそのまま動きます(WSL は使いません)。このページは、[setup.md](setup.md) の手順のうち
Windows で違うところだけを書きます。GitHub 側の準備(タスク用リポジトリ、Project の Status と欄)は setup.md と同じです。

## mac との違い

| こと | macOS | Windows |
|---|---|---|
| `task` の入れ方 | `~/.local/bin/task` へのリンク | `windows\install.ps1` が書く `~\.local\bin\task.cmd`(Git Bash 用に `task` も) |
| `task watch` の常駐 | launchd の plist | タスク スケジューラ(拒否されたらスタートアップ フォルダー)。`install.ps1 -Watch` |
| 実行の見え方 | herdr のタブ、なければ裏で実行 | いつも裏で実行(herdr は Windows にありません)。`task log <番号>` で追う |
| 通知 | herdr か macOS の通知 | Windows のトースト通知(Windows PowerShell 5.1 から出します) |
| `[setup]` のコマンド | `sh` | PowerShell |
| 実行中かの判定 | `ps` | Windows の API でプロセスのコマンドラインを読む |

## 必要なもの

- Windows 10 か 11。PowerShell でスクリプトを実行できること
- git(Git for Windows)、`gh`(GitHub CLI)、Python 3.10 以上。会社の PC で入っていなければ情シスに頼むか、
  `winget install --id Git.Git -e`、`winget install --id GitHub.cli -e`、`winget install --id Python.Python.3.12 -e`
- `gh` のログインと Projects の権限:

  ```
  gh auth login
  gh auth refresh -s project
  ```

- ログイン済みのエージェント CLI が 1 つ以上。kiro-cli は 2.0 から Windows 11 で動きます
  ([Kiro CLI 2.0 の変更履歴](https://kiro.dev/changelog/cli/2-0/))。Claude Code、Codex も使えます([agents.md](agents.md))
- 会社の PC で PowerShell が制約付き言語モード(Constrained Language Mode)のときは、インストーラ、常駐、通知が
  動かない可能性があります(確かめていません)。`$ExecutionContext.SessionState.LanguageMode` が `FullLanguage` なら問題ありません

## インストール

task-hub を clone したフォルダで、PowerShell から実行します:

```
powershell -ExecutionPolicy Bypass -File windows\install.ps1
```

インストーラは次を行います。何度実行しても安全です。

1. git、gh、Python 3.10 以上があるかを確かめます。何も入れません(無ければ入れ方を出して止まります)
2. 動かす用の clone を `~\.local\lib\task-hub` に作ります。すでにあれば `git pull --ff-only` で更新します
   (開発用の clone とは分けます。理由は [setup.md](setup.md#インストール))
3. `~\.local\bin\task.cmd` を書き、`~\.local\bin` をユーザーの PATH に足します。新しく開いたターミナルで `task` が使えます。
   Git Bash(Windows の Claude Code が Bash ツールに使うシェル)は .cmd を実行しないので、同じ場所に sh 用の `task` も書きます

更新するときも、同じコマンドをもう一度実行します。

## 設定

設定ファイルは `%USERPROFILE%\.config\task-hub\config.ini` です。中身は [setup.md](setup.md#github-側の準備1-回だけ)
と同じですが、次の 3 点が違います。

- **パスはスラッシュで書きます。** `[agents]` などのコマンドは shlex の規則で引数に分けるため、`\` は消えます。
  `C:/Users/you/tools/agent.exe {prompt}` のように書きます。空白を含むパスは `'...'` で囲みます
- **npm で入れたエージェント**(`codex.cmd`、`claude.cmd` など)は、そのまま名前で書けます。task-hub は .cmd の中の
  スクリプトを node で直接動かします(.cmd が .exe を指していれば、その .exe を直接動かします)。バッチファイルは
  引数を最初の改行で切ってしまい、複数行のプロンプトが届かないためです。中身を読めない .cmd や .bat は、実行せずに
  その理由を出します。そのときは .exe を直接書きます
- **`[setup]` は PowerShell で動きます。** コマンドレットが失敗するとそこで止まります。プログラム(uv、npm など)が
  0 以外で終わってもその場では止まらず、次の行に進みます(最後に残った終了コードが 0 以外なら、最後に失敗にします)。
  その場で止めたい行のあとには `if ($LASTEXITCODE) { exit $LASTEXITCODE }` を書きます。プログラムの出力に `2>&1` や
  `2>$null` を付けると、エラー出力の 1 行目で止まるので付けません

  ```ini
  [setup]
  you/app = uv venv -q .venv
    uv pip install -q -r requirements.txt --python .venv/Scripts/python.exe
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  ```

組み込みの `claude` は `env NAME=値 ... claude -p ...` の形です。Windows に `env` はないので、task-hub が先頭の
`env NAME=値` を環境変数に置き換えて起動します。自分で書くコマンドでも同じ形が使えます。

## スキル(/task と /chief)

リンクの代わりにジャンクションを作ります(管理者権限が要りません):

```
foreach ($s in 'task', 'chief') {
  foreach ($d in "$HOME\.claude\skills", "$HOME\.kiro\skills", "$HOME\.agents\skills") {
    New-Item -ItemType Directory -Force $d | Out-Null
    if (-not (Test-Path "$d\$s")) { New-Item -ItemType Junction -Path "$d\$s" -Target "$HOME\.local\lib\task-hub\skills\$s" | Out-Null }
  }
}
```

## Ready のカードを自動で始める(常駐)

```
powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch
```

ログオンのたびに `task watch` を始め、今すぐにも始めます。中身は `windows\task-watch.ps1` で、`task watch` が
終わっても(設定の誤りなど)1 分後に始め直します。

- **登録先**: タスク スケジューラの「task-hub watch」。会社の PC で登録を拒否されたときは、スタートアップ フォルダーに
  ショートカットを置きます(インストーラがそう表示します)
- **ログ**: `~\.local\state\task-hub\watch.log`。始めるたびに `starting task watch` の行が出ます。そのあとは、
  カードを始めたときやエラーのときだけ書きます(何もない間は何も出ません)
- **確認**: `Get-ScheduledTask -TaskName 'task-hub watch'` の State が Running で、watch.log の最後が `error:` でないこと
- **止める**: `powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Uninstall`。常駐と `task.cmd` を外します。
  clone、設定、データは残します。止めるのは常駐のループと `task watch` だけで、動いている実行はそのまま最後まで動きます
- **ウィンドウ**: ログオンの直後に PowerShell の窓が一瞬出て、すぐ隠れます
- **環境変数**: タスク スケジューラから始めた `task watch` は、ログオンしたユーザーの環境変数(PATH を含む)を
  そのまま使います。launchd と違い、PATH を別に書く必要はありません。`KIRO_API_KEY` などは、ユーザー環境変数に
  入れてから、いったんサインアウトしてサインインし直します

`task watch` が始めた実行は、`task watch` とは別のプロセスとして、タスク スケジューラのジョブの外で動きます
(ジョブが外に出ることを許さないときは中で動きます)。タスク スケジューラの画面から「task-hub watch」を「終了」すると、
ジョブの中の実行も止まることがあるので、止めるときは `-Uninstall` を使います。止まった実行は、次の確認で
「the run stopped unexpectedly」として Blocked になります。

task-hub は自分を UTF-8 モード(`PYTHONUTF8=1`)で動かし、エージェントやそのテストにもこの環境変数が渡ります。
Python のプログラムは、日本語の Windows の既定(cp932)ではなく UTF-8 でファイルを読み書きします。

## 確かめたこと、確かめていないこと

GitHub Actions の Windows(`windows-latest`)で、次を自動テスト(`tests/test_windows.py`)で確かめています。GitHub と
エージェントは偽物(`gh` とエージェントの代わりのスクリプト)で、git、worktree、プロセスは本物です。

- 日本語のタスクが PR まで進むこと(複数行のプロンプトが切れずに届く)
- 実行中の判定(動いている間は In progress のまま、殺すと Blocked)
- `env` の置き換え、npm の .cmd(node のスクリプトと .exe の両方)
- PowerShell での `[setup]` と、その失敗で Blocked になること
- `install.ps1 -Watch` でタスク スケジューラに登録され、`task watch` が動くこと。Git Bash から `task` が動くこと。
  `-Uninstall` で常駐が止まって外れ、プロンプトに task-watch.ps1 を含むような無関係のプロセスは止めないこと

次は実機で確かめていません。

- トースト通知が実際に出るか(Actions には画面がないため)
- 会社の PC のポリシーの下で、タスク スケジューラへの登録とスタートアップ フォルダーへの切り替え
- 常駐から始めた実行が、`-Uninstall` や再インストールのあとも最後まで動くこと(ジョブの外に出られるかは環境しだい)
- kiro-cli、Claude Code、Codex の Windows 版での実行。kiro-cli の使用量(クレジット)の記録は、Windows では
  セッションの保存場所が mac と違う可能性があり、出ないことがあります

次は Windows に対応していません: herdr、Kiro IDE のフックとワークフローとかんたんセットアップ(`kiro/`)、
Claude Code の task-board mod。
