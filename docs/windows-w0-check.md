# Windows の機で確かめてほしいこと(W0)

Kiro IDE 版 task-hub を Windows でも使えるようにするための確認です。所要時間は 15〜20 分です。
結果で、Windows 版の作り方が決まります([prd-kiro-windows.md](prd-kiro-windows.md) の 6 章)。

## やり方

1. スタートメニューで「**Windows PowerShell**」を開きます(「PowerShell 7」ではなく、青い画面の Windows PowerShell)。
2. 下の A、B、C のコマンドを、ブロックごとにコピーして貼り付け、Enter を押します。
3. 出てきた文字を **そのまま全部** コピーして、送ってください(スクリーンショットでも構いません)。
   エラーが出ても止めずに、そのまま次へ進んでください。エラーの文も大事な結果です。

---

## A. 読むだけ(何も変えません)

```powershell
"--- 1. Windows と CPU"; [Environment]::OSVersion.Version; $env:PROCESSOR_ARCHITECTURE; (Get-CimInstance Win32_OperatingSystem).Caption
"--- 2. ユーザー名とホーム"; $env:USERNAME; $env:USERPROFILE
"--- 3. 文字コード"; [System.Text.Encoding]::Default.WebName; (Get-Culture).Name; chcp
"--- 4. git"; git --version; (Get-Command git).Source; git config --show-origin --get http.sslBackend
"--- 5. Python"; Get-Command python, python3, py -All -ErrorAction SilentlyContinue | Format-List Name, Source; python --version; "exit=$LASTEXITCODE"
"--- 6. 実行ポリシーと言語モード"; Get-ExecutionPolicy -List; $ExecutionContext.SessionState.LanguageMode
"--- 8. ネットワーク"; curl.exe -sSI https://github.com | Select-Object -First 1; Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' | Select-Object ProxyEnable, ProxyServer, AutoConfigURL
"--- 11. Kiro の場所"; Test-Path "$env:USERPROFILE\.kiro", "$env:APPDATA\Kiro\User\settings.json", "$env:LOCALAPPDATA\Programs\Kiro"; Get-Command kiro, kiro-cli -ErrorAction SilentlyContinue | Format-List Name, Source
```

## B. 一時フォルダと通知だけ(残るものはありません)

7 番は、GitHub CLI を一時フォルダに落として動くかを見ます(ホームの下の exe が止められていないかの確認)。
10 番は、画面の右下に「task-hub test」という通知が 1 つ出るかを見ます。

```powershell
"--- 7. ホームの下の exe"; curl.exe -fsSLo "$env:TEMP\gh.zip" https://github.com/cli/cli/releases/download/v2.102.0/gh_2.102.0_windows_amd64.zip; tar -xf "$env:TEMP\gh.zip" -C $env:TEMP; & "$env:TEMP\bin\gh.exe" --version; Remove-Item "$env:TEMP\gh.zip", "$env:TEMP\bin", "$env:TEMP\LICENSE" -Recurse -Force -ErrorAction SilentlyContinue
"--- 10. 通知"; [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; $x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1); $x.GetElementsByTagName('text')[0].InnerText='task-hub test'; [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show([Windows.UI.Notifications.ToastNotification]::new($x)); "通知は出ましたか?(出た/出ない を返信に書いてください)"
```

1 番で `PROCESSOR_ARCHITECTURE` が `ARM64` だった人は、7 番の `windows_amd64` を `windows_arm64` に替えて実行してください。

---

## C. 機に変更を加えるもの(許可済み。終わったら元に戻します)

### 9. タスク スケジューラにタスクを登録できるか(登録して、すぐ消します)

```powershell
"--- 9. タスク スケジューラ"; $a=New-ScheduledTaskAction -Execute cmd.exe -Argument '/c exit'; Register-ScheduledTask -TaskName th-probe -Action $a -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) -Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive); Unregister-ScheduledTask th-probe -Confirm:$false; "登録と削除: 終わり"
```

### 12. Kiro のフックが、どのシェルで動くか(試しのフックを置いて、確かめたら消します)

1. 次を PowerShell に貼ります。試しのフックが置かれます。

   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.kiro\hooks" > $null
   [IO.File]::WriteAllText("$env:USERPROFILE\.kiro\hooks\th-probe.json", '{"version":"v1","hooks":[{"name":"th-probe","trigger":"UserPromptSubmit","action":{"type":"command","command":"echo HOME=$HOME UP=%USERPROFILE% > th-hook-probe.txt"}}]}')
   "置きました"
   ```

2. Kiro IDE で、何かフォルダを開いた状態にします。**新しいチャット** を開き、「こんにちは」とだけ送ります。
3. 開いているフォルダに `th-hook-probe.txt` ができているはずです。その中身を送ってください。
   - `HOME=C:\Users\...` のように HOME が展開されていたら PowerShell、`UP=C:\Users\...` のように UP が展開されていたら cmd です。
   - ファイルができていなければ、「できなかった」と送ってください。
4. 次を PowerShell に貼って、試しのフックと結果のファイルを消します。

   ```powershell
   Remove-Item "$env:USERPROFILE\.kiro\hooks\th-probe.json" -Force; "消しました(th-hook-probe.txt はフォルダから手で消してください)"
   ```

### 13. kiro-cli を入れられるか(Windows 11 の人だけ。入れたままで構いません)

Kiro の公式の入れ方を、そのまま実行します。**管理者のパスワード(UAC)を求められたら「いいえ」を押して** 、そのことを送ってください。

```powershell
"--- 13. kiro-cli"; irm 'https://cli.kiro.dev/install.ps1' | iex
```

終わったら、**PowerShell をいったん閉じて開き直し**、次を貼ります(14 番も兼ねます)。

```powershell
"--- 13. 入った場所"; (Get-Command kiro-cli -ErrorAction SilentlyContinue).Source; kiro-cli --version
"--- 14. プロンプトの渡し方"; kiro-cli chat --help
```

送ってほしいのは、入った場所、管理者のパスワードを求められたか(はい / いいえ)、`--help` の出力全部です。

---

## 返信のまとめ方(例)

```
A: (貼り付け)
B: (貼り付け) 通知は 出た / 出ない
9: (貼り付け)
12: th-hook-probe.txt の中身 = ...
13: 入った場所 = ...  UAC = 出なかった
14: (貼り付け)
```
