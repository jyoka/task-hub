# PRD: Kiro IDE 版 task-hub の Windows 対応 (2026-10-02)

## 1. 背景

- Kiro IDE 版 task-hub は、Mac 向けのかんたんセットアップ(`kiro/install.sh`)で配っています(配布版 kiro-v2)。
  詳しくは [prd-kiro-installer.md](prd-kiro-installer.md) と [kiro-quickstart.md](kiro-quickstart.md) にあります。
- 社内では **Windows を使う同僚も多い** ので、Windows でも同じように使えるようにします。
- 調べもの dip-ka-jo/tasks#69(2026-10-02)の要点:
  - **task-hub 本体(`bin/task`)は、そのままでは Windows で動きません。** 直すのは 150〜250 行ほどの見込みです。
    - 一番の問題は、日本語の Windows の文字コード(cp932)
    - ほかに、プロセスの生死の判定(`ps` がない)、バックグラウンドでの起動、コマンドの探し方
  - **git、Python(uv)、gh は、管理者権限なしで入れられます。**
  - **kiro-cli は Windows 11 だけ** で、x64 版しかありません。MSI はユーザー単位で入る見込みです(要確認)。
  - **常駐はタスク スケジューラで作れます**(ユーザー単位)。通知は Windows PowerShell 5.1 のトーストで出せます。
  - **WSL は使いません**(有効にするのに管理者権限が要るため)。
- 同僚 1 人の Windows 機で確かめたこと(2026-10-02):
  - PowerShell の実行ポリシー: MachinePolicy と UserPolicy は Undefined、LocalMachine は RemoteSigned
  - git: `2.54.0.windows.1`

## 2. 目的

Windows の同僚も、Mac と同じく「Kiro IDE でリポジトリを開き、チャットに『セットアップして』と言う」だけで、最初のタスクまで進めるようにします。

| # | 目的 |
|---|---|
| G1 | task-hub 本体(`bin/task`)が Windows 10 / 11 で動く。macOS の動きは変えない |
| G2 | 管理者権限なしの 1 コマンドのインストーラ(`kiro\install.cmd`)が、Mac 版と同じ段階を進める |
| G3 | Kiro との連携が Windows で動く: `/task`、`/chief`、フック、Workflows |
| G4 | 常駐(タスク スケジューラ)と通知(トースト)が、Windows で動く |
| G5 | テストが Windows でも走る(GitHub Actions)。日本語の Windows と管理者権限なしの確認は、同僚の実機で行う |

**成功の基準**: Windows 11 の同僚が、管理者権限なしで、30 分以内に最初のタスクを In review まで進められる。

## 3. 決めたこと(2026-10-02、ユーザーが承認)

1. **インストーラは「`.cmd` の入口 + Python の本体」にする。`.ps1` は配らない。**
   - `.cmd`(`kiro\install.cmd`)は、Python を用意するところまでを行う。Python がなければ、`curl.exe`、`certutil`、`tar.exe` で uv を取る。
   - 残りの段階は、すべて Python(`kiro/install.py`)で行う。
   - こうすると、実行ポリシー(Restricted の人がいても)と、ダウンロードしたファイルの印(Mark of the Web)の両方を避けられる。
   - 通知やタスク スケジューラで PowerShell が要るところは、`powershell.exe -EncodedCommand` で呼ぶ。スクリプトのファイルではないので、実行ポリシーの対象外。
2. **Windows では、スキル、steering、フック、ワークフローを全部コピーで入れる。**
   - リンクやジャンクションは使わない。シンボリックリンクには権限が要ること、Kiro が実体のパスで許可された場所かを調べることが理由。
   - 更新のあとは、インストーラを再実行すればコピーし直される。
3. **最初の版では、Windows で herdr も WSL も使わない。**
4. **`task` コマンドの入口を `task.cmd` にするか、`uv tool install --editable` で作る `task.exe` にするかは、インストーラの PBI(W4)で試してから決める。**
   - `.cmd` には、引数に `&`、`%`、`"` が入ると壊れる問題(BatBadBut)がある。

## 4. やらないこと

- WSL での動作。
- Windows で herdr を使うこと。
- `.ps1` を配ること、zip をブラウザで落として配ること(clone で配る今の流れを続ける)。
- Windows 10 で kiro-cli を使うこと(公式の動作環境は Windows 11 だけ)。
  - Windows 10 の人は、Kiro IDE で `/task` と `/chief` を使う範囲に限る。worker は Windows 11 か Mac の機で動かす。
- Mac 版のインストーラ(`install.sh`)を Python に書き直すこと。将来の候補として残す。

## 5. 作り(Windows のインストーラの段階)

段階の名前、manifest、doctor、uninstall の考え方は Mac 版と同じです。置き場所は `%USERPROFILE%` の下(`.local\bin`、`.local\lib\task-hub`、`.config\task-hub`、`.kiro`)です。

| 段階 | Windows での中身 | 本人の操作 |
|---|---|---|
| 1. 前提の確認 | Windows の版(10 / 11)、CPU、git、ユーザー名に空白がないか、GitHub に届くか、プロキシ(HKCU の Internet Settings)。git がなければ、情シスへの依頼文を出して止まる | — |
| 2. Python | 既にある Python 3.10 以上を使う(Microsoft Store の中継の `python.exe` は除く)。なければ uv の zip を `.local\bin` に置き、`UV_SYSTEM_CERTS=1 uv python install 3.12` | — |
| 3. gh | `gh_<ver>_windows_{amd64,arm64}.zip` を `checksums.txt` で確かめてから、`bin\gh.exe` を置く(MSI は管理者権限が要るので使わない) | — |
| 4. kiro-cli | Windows 11 だけ。manifest の MSI を sha256 で確かめ、`msiexec /i <msi> /qn` で入れる(ユーザー単位の見込み)。Windows 10 では飛ばして先へ進む | UAC が出たら断る |
| 5. ログイン | Mac と同じ順番。GitHub(device flow、`gh auth setup-git`)と kiro-cli のログインを、clone の前に行う | ブラウザで承認 |
| 6. task-hub 本体 | `.local\lib\task-hub` に clone、`task` の入口(3 章の 4)、ユーザーの PATH(HKCU の `Path`、`REG_EXPAND_SZ`。`setx` は使わない) | — |
| 7. ボード | Mac と同じ(`kiro/install-board` を使い回し、文字コードを UTF-8 に直す) | — |
| 8. 設定 | `.config\task-hub\config.ini`。パスは `/` 区切りで書く | — |
| 9. Kiro との連携 | 4 つを全部コピー。フックとワークフローの `command` は、絶対パスの `.cmd` に書き換えてからコピーする(`$HOME` は使わない)。`%APPDATA%\Kiro\User\settings.json` で Workflows を有効にする | Kiro の再起動 |
| 10. 常駐(任意) | タスク スケジューラに、自分のログオンで起動するユーザー単位のタスクを入れる(Interactive、Limited、`pythonw.exe`、時間の上限と電池の条件を外す) | 始めるときに「はい」と言う |
| 11. 診断 | `kiro/doctor.py`。実行ポリシー、git の sslBackend、PATH が今の窓に効いているかも出す | — |

**守ること**
- ダウンロードはすべてチェックサムで確かめる。
- 文字コードはすべて UTF-8 を明示する。
- `HOME` ではなく `USERPROFILE` を使う。
- 管理者権限が要る操作は一切しない。

## 6. 決まっていないこと(W0 で確かめる)

同僚の Windows 機での確認([windows-w0-check.md](windows-w0-check.md))で決めます。

| 確かめること | 決まるもの |
|---|---|
| 文字コード(cp932 か) | W1 の文字コードの直し方が必須か |
| Kiro のフックが PowerShell と cmd のどちらで動くか | W6 のフックの `command` の書き方 |
| kiro-cli の MSI がユーザー単位で入るか、UAC が出るか | W5 の段階 4 |
| kiro-cli にプロンプトをファイルか stdin で渡せるか | W3 の長いプロンプトの直し方 |
| ホームの下の exe が動くか(AppLocker / WDAC) | Windows 版がそもそも成り立つか |
| タスク スケジューラにユーザー単位で登録できるか、トーストが出るか | W6 の常駐と通知 |
| Kiro の `settings.json` の場所、`kiro` の CLI の名前 | W6 の段階 9、`[ide] open` |

## 7. PBI

| # | タイトル | 中身 | 待ち先 |
|---|---|---|---|
| W1 | 本体を Windows で動かす(中核) | 文字コード(UTF-8 の明示)、プロセスの生死の判定、バックグラウンドでの起動、コマンドの探し方(`.exe` / `.cmd`、`env K=V`)、Windows で herdr を使わない。macOS の動きは変えない | なし(W0 の文字コードの結果があれば反映) |
| W2 | テストを Windows でも走らせる、GitHub Actions | `tests/test_task.py` を Windows でも動くようにし、`.github/workflows/test.yml` で macOS と Windows に並べる。文字コードの指定漏れを CI で見つける(`-X warn_default_encoding`)。走らせるのは手動か、`bin/task` を変える PR だけ | W1 |
| W3 | 本体の残り | 長いプロンプト(ファイルか stdin で渡す)、`[setup]` のシェル、トースト通知、kiro-cli の記録の場所、`cleanup` と追記の Windows 対応 | W1、W0(kiro-cli) |
| W4 | Windows のインストーラの中核 | `kiro\install.cmd` と `kiro/install.py` の段階 1〜3、6、8、manifest。`task` の入口を試して決める(3 章の 4)。`tests/test_install_windows.py` | W1 |
| W5 | ログイン、ボード、kiro-cli | 段階 4、5、7 | W4、W0(kiro-cli) |
| W6 | Kiro との連携と常駐 | 段階 9、10。`kiro/task-events-since` を Python に書き直す。`skills/chief` の sh の書き方を、`task` のサブコマンドに置き換える | W4、W5、W0(フックのシェル) |
| W7 | 診断、アンインストール、ガイド | `kiro/doctor.py`、`kiro/uninstall.py`、`docs/kiro-quickstart-windows.md`、「セットアップして」の steering に Windows の分岐を足す | W4〜W6 |

## 8. 確認の進め方

- 各 PBI は、手元(Mac)のテストと、GitHub Actions の Windows の環境で確かめる。
  - Actions は管理者として、英語の環境で動く。そのため「管理者権限なし」と「日本語の Windows」の問題はそこでは出ない。
- 最後に、**同僚の Windows 11 の機で通しの確認** をする(Mac 版の kiro-v1 / v2 と同じ手順)。合格したら、Windows 対応を入れた版を次の `kiro-v*` として配る。
