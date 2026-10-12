<#
.SYNOPSIS
  Checks every stage of windows/install.ps1 and lists what is missing, with what to do next (stage 12).

.DESCRIPTION
  It changes nothing: no file, no login, nothing on GitHub. It judges whether task-hub works, not whether it has the
  installer's form: a manual install (docs/windows.md before the easy setup: a task.cmd with no mark, a clone on a
  branch, kiro-cli or git logged in another way) that works is ○, with a note under it.
  -InInstall: windows/install.ps1 runs it at its end; then only the list, the installer says the one next step.
  Exit status: 0 = everything there, 1 = something missing.
  For tests: the same variables as windows/install.ps1 (TASK_INSTALL_GITHUB, TASK_INSTALL_USER_ENV,
  TASK_INSTALL_MACHINE_ENV, TASK_INSTALL_PROGRAM_FILES).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\doctor.ps1
#>
param([switch]$InInstall)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false  # Japanese, whatever the console's code page
$Root = $env:USERPROFILE
$Lib = Join-Path $Root '.local\lib\task-hub'
$BinDir = Join-Path $Root '.local\bin'
$Shim = Join-Path $BinDir 'task.cmd'
$KiroHome = Join-Path $Root '.kiro'
$Manifest = Join-Path $Root '.local\state\task-hub\install-manifest.json'
$Marker = 'task-hub: made by windows/install.ps1'
$TaskName = 'task-hub watch'
$Startup = [IO.Path]::Combine([Environment]::GetFolderPath('Startup'), 'task-hub watch.lnk')
$GitHub = if ($env:TASK_INSTALL_GITHUB) { $env:TASK_INSTALL_GITHUB.TrimEnd('/') } else { 'https://github.com' }
$ProgramFiles = if ($env:TASK_INSTALL_PROGRAM_FILES) { $env:TASK_INSTALL_PROGRAM_FILES } else { $env:ProgramFiles }
$Install = 'powershell -ExecutionPolicy Bypass -File windows\install.ps1 を実行してください(Kiro のチャットなら「セットアップして」)'
$script:missing = 0
$script:firstStep = ''

function Tilde($p) { if ("$p".StartsWith("$Root\")) { '~' + "$p".Substring($Root.Length) } else { "$p" } }
function Ok($detail) { Write-Host "○ $($script:label): $detail" }
function Note($text) { Write-Host "    ($text)" }
function Ng($what, $next) {
  Write-Host "× $($script:label): $what"
  Write-Host "    → $next"
  $script:missing++
  if (-not $script:firstStep) { $script:firstStep = $next }
}

function Runs($exe, [string[]]$a) {  # as in install.ps1
  $ErrorActionPreference = 'Continue'
  try {
    $script:Out = @($null | & $exe @a 2>&1 | ForEach-Object { "$_" })
    return ($LASTEXITCODE -eq 0)
  } catch {
    $script:Out = @("$_")
    return $false
  }
}

function Find-App($name) {
  Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 |
    ForEach-Object { $_.Source }
}

function Read-EnvPath($which) {  # as in install.ps1, read only
  $hook = if ($which -eq 'User') { $env:TASK_INSTALL_USER_ENV } else { $env:TASK_INSTALL_MACHINE_ENV }
  $k = if ($hook) { [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($hook) }
       elseif ($which -eq 'User') { [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment') }
       else { [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager\Environment') }
  if (-not $k) { return '' }
  try { return [string]$k.GetValue('Path', '') } finally { $k.Close() }
}

function Get-RealPath($p) {
  $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
  if ($item -and $item.LinkType -and $item.Target) { return [IO.Path]::GetFullPath(@($item.Target)[0]).TrimEnd('\') }
  return [IO.Path]::GetFullPath($p).TrimEnd('\')
}

function Get-NewestKiroTag($names) {
  $names | Where-Object { $_ -match '^kiro-v\d+$' } | Sort-Object { [int]$_.Substring(6) } | Select-Object -Last 1
}

function Invoke-Check($what, $before = '') {  # kiro/install-board check: "ok<TAB>detail" or "ng<TAB>detail<TAB>next step"
  if (-not (Runs $script:Python @((Join-Path $PSScriptRoot '..\kiro\install-board'), 'check', $what))) {
    Ng '確かめられませんでした' 'この出力を task-hub の担当者に知らせてください'
    return
  }
  $r = "$($script:Out | Select-Object -Last 1)" -split "`t"
  if ($r[0] -eq 'ok') { Ok "$before$($r[1])" }
  elseif ($r.Count -ge 3) { Ng $r[1] $r[2] }
  else { Ng '確かめられませんでした' 'この出力を task-hub の担当者に知らせてください' }
}

$userPath = Read-EnvPath 'User'
# as the installer sees them: what is on the registry's PATH, though this window may have been opened before
$env:Path = (@($BinDir, (Read-EnvPath 'Machine'), $userPath, $env:Path) | Where-Object { $_ }) -join ';'
$m = $null
if (Test-Path $Manifest) { try { $m = [IO.File]::ReadAllText($Manifest) | ConvertFrom-Json } catch { } }
if ($InInstall) { Write-Host '診断:' } else { Write-Host 'task-hub の診断です(何も変えません)' }

# 1. prerequisites
$script:label = '1. 前提の確認'
if (-not $env:HTTPS_PROXY) {  # as install.ps1: Windows' proxy for GitHub, for gh and git
  try { $p = [Net.WebRequest]::GetSystemWebProxy().GetProxy([Uri]$GitHub) } catch { $p = $null }
  if ($p -and $p.Authority -ne ([Uri]$GitHub).Authority) { $env:HTTPS_PROXY = $p.AbsoluteUri.TrimEnd('/') }
}
$git = Find-App git
$reach = $true
try {
  $r = [Net.WebRequest]::Create($GitHub)
  $r.Method = 'HEAD'
  $r.Timeout = 30000
  $r.GetResponse().Close()
} catch { $reach = $false }
if ("$($ExecutionContext.SessionState.LanguageMode)" -ne 'FullLanguage') {
  Ng "PowerShell の機能が制限されています($($ExecutionContext.SessionState.LanguageMode))" '情シスに相談してください(依頼文はインストーラが出します)'
} elseif (-not ($git -and (Runs $git @('--version')))) {
  $git = $null
  Ng 'git がないか、動きません' $Install
} elseif (-not $reach) {
  Ng "GitHub($GitHub)に届きません" 'ネットワーク(VPN、プロキシ)を確かめてください'
} else {
  Ok "git、GitHub に接続$(if ($env:HTTPS_PROXY) { "、プロキシ $env:HTTPS_PROXY" })"
}

# 2. Python: the one the manifest says task.cmd runs, else one the installer would choose
$script:label = '2. Python'
$script:Python = $null
$test = { param($p) $p -and (Test-Path -LiteralPath $p) -and (Runs $p @('-c', 'import sys; sys.exit(sys.version_info < (3, 10))')) }
if ($m -and (& $test $m.python)) { $script:Python = $m.python }
else {
  foreach ($c in @(@('py', '-3'), @('python'))) {
    if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
    $a = @($c | Select-Object -Skip 1) + @('-X', 'utf8', '-c', 'import sys; print(sys.executable); print(sys.version_info >= (3, 10))')
    if ((Runs $c[0] $a) -and $script:Out.Count -ge 2 -and $script:Out[1] -eq 'True') { $script:Python = $script:Out[0]; break }
  }
}
if ($script:Python) { Ok (Tilde $script:Python) } else { Ng 'Python 3.10 以上がありません' $Install }

# 3. gh
$script:label = '3. gh'
$gh = Find-App gh
if ($gh -and (Runs $gh @('--version'))) { Ok (Tilde $gh) } else { $gh = $null; Ng 'gh がありません' $Install }

# 4. kiro-cli: on PATH (where the installer put it, or the official installer's, once on PATH)
$script:label = '4. kiro-cli'
$kiro = Find-App kiro-cli
if ($kiro -and (Runs $kiro @('--version'))) {
  Ok (Tilde $kiro)
} else {
  $kiro = $null
  $off = Join-Path $ProgramFiles 'Kiro-Cli\kiro-cli.exe'
  if (Test-Path -LiteralPath $off) { Ng "$off はありますが、PATH にありません" $Install }
  else { Ng 'kiro-cli がないか、動きません' $Install }
}

# 5. logins
$script:label = '5. GitHub のログイン'
$ghOk = $false  # logged in with project: the board can be checked
if (-not $gh) {
  Ng 'gh がないので確かめていません' $Install
} elseif (-not (Runs $gh @('api', '-i', 'user'))) {
  Ng 'GitHub にログインしていません' 'powershell -ExecutionPolicy Bypass -File windows\install.ps1 を実行し、開いた窓でブラウザでログインしてください'
} else {
  $scopes, $user = '', ''
  foreach ($line in $script:Out) {
    if ($line -match '^x-oauth-scopes:\s*(.*)$') { $scopes = $Matches[1].Trim() }
    if ($line -match '^\{"login":"([^"]+)"') { $user = $Matches[1] }
  }
  if (", $scopes," -notmatch ', project,') {
    Ng "${user}。Projects の権限(project)がありません" 'powershell -ExecutionPolicy Bypass -File windows\install.ps1 を実行し、開いた窓でブラウザで承認してください'
  } else {
    $ghOk = $true
    # git: gh's login (the installer's), else any login that reaches the board's private repo (Git Credential Manager)
    $usesGh = $git -and (Runs $git @('config', '--global', '--get-all', 'credential.https://github.com.helper')) -and
      ($script:Out | Where-Object { $_ -match 'auth git-credential' })
    $issues = ''
    $config = Join-Path $Root '.config\task-hub\config.ini'
    if (Test-Path $config) {
      $board = $false
      foreach ($line in [IO.File]::ReadAllLines($config)) {
        if ($line -match '^\s*\[(.+)\]') { $board = $Matches[1] -eq 'board' }
        elseif ($board -and $line -match '^\s*issues\s*[=:]\s*([^;#\s]+)') { $issues = $Matches[1] }
      }
    }
    $env:GIT_TERMINAL_PROMPT = '0'
    if ($usesGh) {
      Ok $user
    } elseif ($git -and $issues -and (Runs $git @('ls-remote', '--heads', "$GitHub/$issues.git"))) {
      Ok $user
      Note "手で入れた構成です。git は gh 以外のログインで $issues に届きます"
    } else {
      Ng "${user}。git が gh のログインを使っておらず、$(if ($issues) { $issues } else { 'GitHub の private リポジトリ' }) に届きません" $Install
    }
  }
}
$script:label = '5. kiro-cli のログイン'
if (-not $kiro) { Ng 'kiro-cli がないので確かめていません' $Install }
elseif (Runs $kiro @('whoami')) { Ok 'ログイン済み' }
else { Ng 'kiro-cli にログインしていません' 'powershell -ExecutionPolicy Bypass -File windows\install.ps1 を実行し、開いた窓でログインしてください' }

# 6. task-hub itself
$script:label = '6. task-hub 本体'
$marked = (Test-Path -LiteralPath $Shim) -and ([IO.File]::ReadAllText($Shim)).Contains($Marker)
if (-not (Test-Path (Join-Path $Lib '.git'))) {
  Ng "$(Tilde $Lib) がありません" $Install
} elseif (-not (Test-Path -LiteralPath $Shim)) {
  Ng "$(Tilde $Shim) がありません" $Install
} elseif (-not (Runs $Shim @('--version'))) {
  Ng "$(Tilde $Shim) が動きません($($script:Out | Select-Object -Last 1))" $Install
} elseif (-not (($userPath -split ';') -contains $BinDir)) {
  Ng "$(Tilde $BinDir) がユーザーの PATH にありません" $Install
} else {
  # the version, and whether there is a newer kiro-v* (as install.ps1 decides: its clone, in the manifest or not on a
  # branch, follows the newest kiro-v*; a clone on a branch made by hand is only pulled). ls-remote: no fetch
  $note = ''
  $ver = ''
  if ($git) {
    $g = { Runs $git (@('-C', $Lib) + $args) }
    $branch, $current = '', ''
    if (& $g symbolic-ref -q --short HEAD) {
      $branch = $script:Out[0]
      & $g rev-parse --short HEAD | Out-Null
      $ver = "$branch $($script:Out[0])"
    } else {
      & $g tag --points-at HEAD | Out-Null
      $current = Get-NewestKiroTag $script:Out
      $ver = $current
      if (-not $ver) { & $g rev-parse --short HEAD | Out-Null; $ver = $script:Out[0] }
    }
    if (-not ($m -and $m.installed.'task-hub') -and $branch) {
      $note = "ブランチ $branch の上の clone です。インストーラはタグに切り替えず、pull だけします"
    } elseif (-not (& $g ls-remote --tags origin 'kiro-v*')) {
      $note = '新しい版があるかは確かめられませんでした(origin に届きません)'
    } else {
      $newest = Get-NewestKiroTag ($script:Out | ForEach-Object { ($_ -split 'refs/tags/')[-1] } | Where-Object { $_ -notmatch '\^\{\}$' })
      if ($newest -and $current) {
        if ([int]$newest.Substring(6) -gt [int]$current.Substring(6)) { $note = "新しい版 $newest があります。$Install" }
        else { $ver = "$ver、最新" }
      } elseif ($newest) {
        $note = "配布版 $newest ではない版です。次にインストーラを実行すると $newest に切り替わります"
      }
    }
  }
  Ok "$(Tilde $Lib)$(if ($ver) { "($ver)" })、$(Tilde $Shim)"
  if (-not $marked) { Note "手で入れた構成です。$(Tilde $Shim) はインストーラの印のない、以前の形です(動いています)" }
  if ($note) { Note $note }
}

# 7, 8. the board and config.ini (kiro/install-board check: read-only). The board needs only gh, not git
$script:label = '7. ボード'
if (-not $script:Python) { Ng 'Python がないので確かめていません' $Install }
elseif (-not $ghOk) { Ng 'gh が Projects の権限でログインできていないので確かめていません' $Install }
else { Invoke-Check board }
$script:label = '8. 設定'
if (-not $script:Python) { Ng 'Python がないので確かめていません' $Install } else { Invoke-Check config }

# 9. Kiro: junctions to the clone for skills, a copy the same as the clone's for steering. A folder of someone's own
# (the installer keeps it too) is ○ with a note
$script:label = '9. Kiro との連携'
$lacks, $other, $stale = @(), @(), @()
foreach ($s in 'task', 'chief') {
  $link = Join-Path $KiroHome "skills\$s"
  if (-not (Test-Path -LiteralPath $link)) { $lacks += Tilde $link }
  elseif ((Get-RealPath $link) -ne (Get-RealPath (Join-Path $Lib "skills\$s"))) { $other += Tilde $link }
}
$steering = Join-Path $KiroHome 'steering\task-hub.md'
$src = Join-Path $Lib 'kiro\steering\task-hub.md'
if (-not (Test-Path -LiteralPath $steering)) { $lacks += Tilde $steering }
elseif ((Test-Path -LiteralPath $src) -and
        -not ([IO.File]::ReadAllBytes($steering).Length -eq [IO.File]::ReadAllBytes($src).Length -and
              [IO.File]::ReadAllText($steering) -eq [IO.File]::ReadAllText($src))) { $stale += Tilde $steering }
# the hook and the workflow, as `task _kiro-copy` writes them for this PC (Windows' form of their commands)
$older = $false  # the clone's task-hub is from before Windows had hooks: the installer skips them, so does this
foreach ($c in @(@('kiro-hook', 'hooks\task-hub-events.json'), @('kiro-workflow', 'workflows\task-hub-events.workflow.json'))) {
  $dst = Join-Path $KiroHome $c[1]
  if ($script:Python -and -not (Runs $script:Python @((Join-Path $Lib 'bin\task'), '_kiro-copy', $c[0])) -and
      ($script:Out -match 'unknown command|commands: ')) { $older = $true; continue }
  if (-not [IO.File]::Exists($dst)) { $lacks += Tilde $dst; continue }
  if (-not $script:Python -or -not (Runs $script:Python @((Join-Path $Lib 'bin\task'), '_kiro-copy', $c[0]))) { continue }
  $want = "$($script:Out | Select-Object -Last 1)".Trim()
  $sha = [Security.Cryptography.SHA256]::Create()
  try { $got = -join ($sha.ComputeHash([IO.File]::ReadAllBytes($dst)) | ForEach-Object { $_.ToString('x2') }) } finally { $sha.Dispose() }
  if ($got -ne $want) { $stale += Tilde $dst }
}
if ($lacks) { Ng "$($lacks -join '、') がありません" $Install }
elseif ($stale) { Ng "$($stale -join '、') が task-hub の今の版と違います" $Install }
elseif (-not $script:Python) { Ng 'Python がないので Workflows の設定を確かめていません' $Install }
else {
  Invoke-Check kiro-settings "スキル、steering、$(if (-not $older) { 'フック、ワークフロー、' })"
  if ($other) { Note "$($other -join '、') は別のものを指しています。インストーラもそのままにします" }
  if ($older) { Note 'フックとワークフローは、この版の task-hub では Windows に入れられません(新しい版で入ります)' }
}

# 10. task watch at logon (optional): Task Scheduler, or the Startup folder when that was refused
$script:label = '10. 常駐'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$again = 'powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch を実行してください'
if ($task) {
  if ("$($task.State)" -eq 'Running') { Ok "タスク スケジューラの「$TaskName」、動いています" }
  else { Ng "タスク スケジューラの「$TaskName」はありますが、動いていません($($task.State))" $again }
} elseif ([IO.File]::Exists($Startup)) {
  $loop = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains('task-watch.ps1') }
  if ($loop) { Ok 'スタートアップ フォルダー、動いています' }
  else { Ng 'スタートアップ フォルダーにありますが、動いていません' ('サインインし直すか、' + $again) }
} else {
  Ok '使っていません(任意。使うなら -Watch を付けてインストーラを実行します)'
}

if ($InInstall) { exit ([int]($script:missing -gt 0)) }
if ($script:missing -eq 0) {
  Write-Host 'すべて揃っています。'
  Write-Host '次にすること: Kiro の新しいチャットで /task を試してください'
  exit 0
}
Write-Host "足りないものが $($script:missing) つあります。"
Write-Host "次にすること: $($script:firstStep)"
exit 1
