<#
.SYNOPSIS
  Removes what windows/install.ps1 put on this PC, and only that: what it recorded under "installed" in
  ~\.local\state\task-hub\install-manifest.json.

.DESCRIPTION
  uninstall.ps1        lists what it would remove, and removes nothing
  uninstall.ps1 -Yes   removes it (install.ps1 -Uninstall does the same)
  Never removed: the board on GitHub (the tasks repository and the Project; it only says how), the GitHub and kiro-cli
  logins, and task-hub's own data (worktrees, logs, events). A junction is removed as a link, never what it leads to.
  While a task runs (task _run), -Yes only stops the watch: the run uses the clone and the Python, and goes on.
  Running it again is safe: what is gone already is skipped.
  Without a manifest (an install from before the easy setup) it stops the watch and removes task.cmd and `task`, as
  install.ps1 -Uninstall did.
  For tests: TASK_INSTALL_USER_ENV, as windows/install.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1
#>
param([switch]$Yes)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false  # Japanese, whatever the console's code page
$Root = $env:USERPROFILE
$Lib = Join-Path $Root '.local\lib\task-hub'
$BinDir = Join-Path $Root '.local\bin'
$State = Join-Path $Root '.local\state\task-hub'
$Manifest = Join-Path $State 'install-manifest.json'
$Marker = 'task-hub: made by windows/install.ps1'
$TaskName = 'task-hub watch'
$Startup = [IO.Path]::Combine([Environment]::GetFolderPath('Startup'), 'task-hub watch.lnk')
$Again = 'powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1 -Yes'
# The order things are removed in: the watch first (it runs task), then what Kiro reads, task, and what they use;
# uv last, after the Python it installed. PATH entries go before the folders they name.
$Keys = 'watch', 'slack-triage-autostart', 'slack-triage', 'kiro-hook', 'kiro-workflow', 'kiro-steering', 'kiro-skill-task', 'kiro-skill-chief', 'kiro-settings',
  'config', 'task', 'task-sh', 'user-path',
  'kiro-cli-path', 'git-path', 'task-hub', 'kiro-cli', 'gh', 'uv-python', 'uv', 'git'

function Tilde($p) { if ("$p".StartsWith("$Root\")) { '~' + "$p".Substring($Root.Length) } else { "$p" } }
function Mine($p) { "$p".StartsWith("$Root\") -and "$p".Length -gt $Root.Length + 1 }  # never outside the user folder

$script:n = 0
$script:failed = 0
function Remove-Thing($what, [scriptblock]$how) {  # only listed without -Yes
  $script:n++
  if (-not $Yes) { Write-Host "- $what"; return }
  try {
    $ErrorActionPreference = 'Stop'
    & $how
    Write-Host "消しました: $what"
  } catch {
    Write-Host "消せませんでした: $what($($_.Exception.Message.Trim()))"
    $script:failed++
  }
}

function ConvertTo-AsciiPath($p) {
  # A shortcut (.lnk, the Startup folder) keeps its arguments in the code page: a path with letters it lacks (a Japanese
  # user folder on an English Windows) would come back as ?. Its short 8.3 name has none of those. A process started that way
  # has the short name on its command line, so it is looked for by both names
  $ansi = [Text.Encoding]::Default  # the code page a shortcut keeps its arguments in
  $keeps = { param($s) $ansi.GetString($ansi.GetBytes($s)) -eq $s }
  if (& $keeps "$p") { return "$p" }
  try {
    $fso = New-Object -ComObject Scripting.FileSystemObject
    $s = if (Test-Path -LiteralPath $p -PathType Container) { $fso.GetFolder($p).ShortPath } else { $fso.GetFile($p).ShortPath }
    if ($s -and (& $keeps $s)) { return $s }
  } catch { }
  return "$p"
}

function Test-Runs($commandLine, $path) {  # the command line names $path, by its long or its short name
  $commandLine -and ($commandLine.Contains($path) -or $commandLine.Contains((ConvertTo-AsciiPath $path)))
}

function Stop-Watch {
  # the loop (task-watch.ps1) and the `task watch` it started, and nothing else: a run goes on, and so does an agent
  # whose prompt happens to name task-watch.ps1. Not Stop-ScheduledTask, which can end every process the task started
  $loop = Join-Path $Lib 'windows\task-watch.ps1'
  Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { Test-Runs $_.CommandLine $loop } |
    ForEach-Object {
      $id = $_.ProcessId
      Get-CimInstance Win32_Process -Filter "ParentProcessId = $id" |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  }
  if ([IO.File]::Exists($Startup)) { Remove-Item -LiteralPath $Startup }
}

function Remove-UserPath($dir) {
  $hook = $env:TASK_INSTALL_USER_ENV
  $k = if ($hook) { [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($hook) }
       else { [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment') }
  try {
    $now = $k.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $k.SetValue('Path', (($now -split ';' | Where-Object { $_ -and $_ -ne $dir }) -join ';'), 'ExpandString')
  } finally { $k.Close() }
  if (-not $hook) { [Environment]::SetEnvironmentVariable('TASK_HUB_PATH_CHANGED', $null, 'User') }  # tells Explorer
}

function Test-OnUserPath($dir) {
  $hook = $env:TASK_INSTALL_USER_ENV
  $k = if ($hook) { [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($hook) }
       else { [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment') }
  if (-not $k) { return $false }
  try { return (($k.GetValue('Path', '', 'DoNotExpandEnvironmentNames') -split ';') -contains $dir) } finally { $k.Close() }
}

function Get-Sha256($file) {
  $sha = [Security.Cryptography.SHA256]::Create()
  $s = [IO.File]::OpenRead($file)
  try { return -join ($sha.ComputeHash($s) | ForEach-Object { $_.ToString('x2') }) } finally { $s.Dispose(); $sha.Dispose() }
}

function Get-JunctionTarget($p) {  # where a junction leads, or $null when it is not one
  $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
  if ($item -and $item.LinkType -eq 'Junction' -and $item.Target) { return [IO.Path]::GetFullPath(@($item.Target)[0]).TrimEnd('\') }
  return $null
}

function Show-Kept {
  Write-Host '消さないもの:'
  Write-Host '- GitHub のログイン(gh)と kiro-cli のログイン'
  Write-Host '- task-hub のデータ: ~\.local\share\task-hub(worktree)、~\.local\state\task-hub(ログ、出来事)'
  if ($script:settings) { Write-Host "- $(Tilde $script:settings) の Workflows の設定(インストーラは有効にしただけです)" }
  $config = Join-Path $Root '.config\task-hub\config.ini'
  $project, $issues = '', ''
  if (Test-Path -LiteralPath $config) {
    $board = $false
    foreach ($line in [IO.File]::ReadAllLines($config)) {
      if ($line -match '^\s*\[(.+)\]') { $board = $Matches[1] -eq 'board' }
      elseif ($board -and $line -match '^\s*(project|issues)\s*[=:]\s*([^;#\s]+)') {
        if ($Matches[1] -eq 'project') { $project = $Matches[2] } else { $issues = $Matches[2] }
      }
    }
  }
  if ($project -or $issues) {
    Write-Host "- GitHub のボード($(if ($issues) { $issues } else { '?' }) と Project $(if ($project) { $project } else { '?' }))。要らなければ、GitHub の画面で消します:"
    if ($issues) { Write-Host "    リポジトリ: https://github.com/$issues/settings の一番下「Delete this repository」" }
    if ($project -match '^(.+)/(\d+)$') {
      Write-Host "    Project: https://github.com/users/$($Matches[1])/projects/$($Matches[2])/settings の一番下「Delete this project」"
    }
  } else {
    Write-Host '- GitHub のボード(タスク用のリポジトリと Project)。要らなければ、GitHub の画面の Settings から消します'
  }
}

# --- an install from before the easy setup: what install.ps1 -Uninstall removed then ---
if (-not (Test-Path -LiteralPath $Manifest)) {
  Write-Host "windows\install.ps1 の記録($(Tilde $Manifest))がありません。以前の入れ方のものだけを扱います。"
  Remove-Thing '常駐の task watch(タスク スケジューラ、スタートアップ フォルダー)' { Stop-Watch }
  foreach ($f in (Join-Path $BinDir 'task.cmd'), (Join-Path $BinDir 'task')) {
    if (Test-Path -LiteralPath $f) { Remove-Thing (Tilde $f) ([scriptblock]::Create("Remove-Item -LiteralPath '$($f -replace "'", "''")'")) }
  }
  Write-Host "残すもの: $(Tilde $Lib)、~\.config\task-hub、~\.local\state\task-hub、~\.local\share\task-hub(要らなければ手で消します)"
  if ($Yes) { exit ([int]($script:failed -gt 0)) }
  Write-Host "次にすること: 消してよければ、$Again を実行してください"
  exit 0
}
try { $m = [IO.File]::ReadAllText($Manifest) | ConvertFrom-Json } catch { $m = $null }
if (-not $m -or -not $m.version) {
  Write-Host "$(Tilde $Manifest) を読めません。何も消していません。"
  Write-Host '次にすること: そのファイルを task-hub の担当者に見せてください'
  exit 1
}

# a task at work uses the clone and the Python: with -Yes, only the watch is stopped while one runs
$runs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine.Contains((Join-Path $Lib 'bin\task')) -and $_.CommandLine -match '\s_run\s+(\S+)' } |
  ForEach-Object { if ($_.CommandLine -match '\s_run\s+"?(\w+)') { "#$($Matches[1])" } } | Sort-Object -Unique)

if ($Yes) { Write-Host 'windows\install.ps1 が入れたものを消します' }
else { Write-Host 'windows\install.ps1 が入れたもので、消すもの(まだ何も消していません):' }
if ($runs -and $Yes) {
  if ($m.installed.watch) { Remove-Thing '常駐の task watch' { Stop-Watch } }
  Write-Host "作業中のタスクがあります($($runs -join '、'))。作業が使う task-hub と Python は、まだ消していません。"
  Write-Host "次にすること: 作業が終わってから(task list で In progress がなくなってから)、もう一度 $Again を実行してください"
  exit 1
}

$installed = $m.installed
foreach ($k in $Keys) {
  $v = if ($installed) { $installed.$k } else { $null }
  if (-not $v) { continue }
  switch ($k) {
    'watch' {
      if (-not ((Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) -or [IO.File]::Exists($Startup))) { continue }
      Remove-Thing "常駐の task watch($(if ($v -like 'scheduled-task:*') { "タスク スケジューラの「$TaskName」" } else { Tilde $v }))。動いている作業は止めません" { Stop-Watch }
    }
    { $_ -in 'kiro-skill-task', 'kiro-skill-chief' } {
      if (-not (Mine $v) -or -not (Test-Path -LiteralPath $v)) { continue }
      $want = [IO.Path]::GetFullPath((Join-Path $Lib "skills\$($k.Substring(11))")).TrimEnd('\')
      if ((Get-JunctionTarget $v) -ne $want) { Write-Host "残しました: $(Tilde $v)(ジャンクションの先が変わっています)"; continue }
      # the junction, never the folder it leads to (Remove-Item -Recurse would empty the clone's skills)
      Remove-Thing "$(Tilde $v)(ジャンクション)" ([scriptblock]::Create("[IO.Directory]::Delete('$($v -replace "'", "''")')"))
    }
    'slack-triage-autostart' {  # the program that waits for Slack triage's key, and its start at logon
      $hotkey = Join-Path $Lib 'windows\slack-triage-hotkey.ps1'  # quoted or not on the command line
      $how = if ($v -like 'scheduled-task:*') { "タスク スケジューラの「$($v.Substring(15))」" } else { Tilde $v }
      if (-not ($v -like 'scheduled-task:*' -and (Get-ScheduledTask -TaskName $v.Substring(15) -ErrorAction SilentlyContinue)) -and
          -not [IO.File]::Exists($v)) { continue }
      Remove-Thing "Slackトリアージの起動キーを待つ常駐($how)" ([scriptblock]::Create(@"
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" | Where-Object { Test-Runs `$_.CommandLine '$($hotkey -replace "'", "''")' } | ForEach-Object { Stop-Process -Id `$_.ProcessId -Force -ErrorAction SilentlyContinue }
if ('$($v -replace "'", "''")' -like 'scheduled-task:*') { Unregister-ScheduledTask -TaskName '$($v.Substring(15) -replace "'", "''")' -Confirm:`$false }
else { Remove-Item -LiteralPath '$($v -replace "'", "''")' }
"@))
    }
    'slack-triage' {  # the command, only while it is the installer's
      if (-not (Mine $v) -or -not (Test-Path -LiteralPath $v) -or -not ([IO.File]::ReadAllText($v)).Contains($Marker)) { continue }
      Remove-Thing (Tilde $v) ([scriptblock]::Create("Remove-Item -LiteralPath '$($v -replace "'", "''")'"))
    }
    'kiro-settings' {  # a file of the user's that the installer changed one setting in: said, not removed
      $script:settings = $v
    }
    { $_ -in 'kiro-steering', 'kiro-hook', 'kiro-workflow' } {  # copies, which may have been edited since
      if (-not (Mine $v) -or -not (Test-Path -LiteralPath $v)) { continue }
      if ((Get-Sha256 $v) -ne $m.sha256.$k) { Write-Host "残しました: $(Tilde $v)(インストーラが入れた内容と確認できません)"; continue }
      Remove-Thing (Tilde $v) ([scriptblock]::Create("Remove-Item -LiteralPath '$($v -replace "'", "''")'"))
    }
    { $_ -in 'task', 'task-sh' } {  # only while it is the installer's
      if (-not (Mine $v) -or -not (Test-Path -LiteralPath $v) -or -not ([IO.File]::ReadAllText($v)).Contains($Marker)) { continue }
      Remove-Thing (Tilde $v) ([scriptblock]::Create("Remove-Item -LiteralPath '$($v -replace "'", "''")'"))
    }
    { $_ -in 'user-path', 'kiro-cli-path', 'git-path' } {
      if (-not (Test-OnUserPath $v)) { continue }
      Remove-Thing "ユーザーの PATH の $(Tilde $v)" ([scriptblock]::Create("Remove-UserPath '$($v -replace "'", "''")'"))
    }
    { $_ -in 'task-hub', 'kiro-cli', 'git' } {  # folders this script made
      $mark = @{ 'task-hub' = '.git'; 'kiro-cli' = 'kiro-cli.exe'; 'git' = 'cmd\git.exe' }[$k]
      if (-not (Mine $v) -or -not (Test-Path -LiteralPath (Join-Path $v $mark))) { continue }
      $what = @{ 'task-hub' = 'task-hub の clone'; 'kiro-cli' = 'kiro-cli'; 'git' = 'git(MinGit)' }[$k]
      Remove-Thing "$(Tilde $v)($what)" ([scriptblock]::Create("Remove-Item -LiteralPath '$($v -replace "'", "''")' -Recurse -Force"))
    }
    'uv-python' {  # a version, where uv keeps its Pythons
      $uv = if ($installed.uv -and (Test-Path -LiteralPath $installed.uv)) { $installed.uv } else {
        Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 | ForEach-Object { $_.Source } }
      if (-not $uv) { continue }
      Remove-Thing "uv で入れた Python $v" ([scriptblock]::Create(
        "`$ErrorActionPreference = 'Continue'; `$o = & '$($uv -replace "'", "''")' python uninstall '$v' 2>&1; " +
        "if (`$LASTEXITCODE) { throw ((`$o | Select-Object -Last 1) -join '') }"))
    }
    default {  # files: config.ini, gh.exe, uv.exe
      if (-not (Mine $v) -or -not [IO.File]::Exists($v)) { continue }
      Remove-Thing (Tilde $v) ([scriptblock]::Create("Remove-Item -LiteralPath '$($v -replace "'", "''")'"))
    }
  }
}
if ($script:n -eq 0) { Write-Host '(もう何も残っていません)' }
if ($runs) { Write-Host "作業中のタスクがあります($($runs -join '、'))。消すのは、作業が終わってからにしてください。" }
Show-Kept

if (-not $Yes) {
  if ($script:n -gt 0) { Write-Host "次にすること: 消してよければ、$Again を実行してください" }
  else { Write-Host '次にすること: 何もありません' }
  exit 0
}
if ($script:failed -gt 0) {  # the manifest stays: run it again
  Write-Host "次にすること: 消せなかったもの(使っているプログラムを閉じて)を確かめて、もう一度 $Again を実行してください"
  exit 1
}
foreach ($f in $Manifest, (Join-Path $State 'gh-login.ps1'), (Join-Path $State 'kiro-login.ps1')) {
  Remove-Item -LiteralPath $f -ErrorAction SilentlyContinue
}
Write-Host '次にすること: Kiro を再起動してください(/task と /chief が外れます)'
