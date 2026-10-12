<#
.SYNOPSIS
  Install task-hub on Windows, and optionally keep `task watch` running (docs/windows.md).

.DESCRIPTION
  Stages, numbered as kiro/install.sh's (docs/architecture/designs/windows-easy-setup.md). Never needs admin rights:
  what it installs goes under the user folder, and is recorded in ~\.local\state\task-hub\install-manifest.json.
  1. Checks Windows, PowerShell's language mode, the proxy and that GitHub answers. Re-reads PATH from the registry,
     so a tool installed after this window opened is found. Without git, puts MinGit in ~\.local\lib\git.
  2. Python 3.10+: the one an earlier run chose, else py -3 or python, else uv's Python 3.12 (uv in ~\.local\bin).
  3. gh: the one on PATH, else the release zip into ~\.local\bin.
  Then clones task-hub to ~\.local\lib\task-hub (or pulls it), writes ~\.local\bin\task.cmd, which runs bin\task with
  that Python, and puts ~\.local\bin on the user PATH.
  With -Watch it also starts `task watch` at every logon (Task Scheduler; the Startup folder when that is refused)
  and starts it now. -Uninstall stops and removes the watch and task.cmd; the clone, config and data stay.
  Downloads are checked against the release's SHA-256. Safe to run again.
  For tests: TASK_INSTALL_GITHUB replaces https://github.com, TASK_INSTALL_GITHUB_API https://api.github.com, and
  TASK_INSTALL_USER_ENV / TASK_INSTALL_MACHINE_ENV name keys under HKCU to use as the user's and the machine's
  environment (PATH), so a test changes no real PATH.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch
#>
param(
  [switch]$Watch,
  [switch]$Uninstall,
  [string]$From = ""  # where to clone from; default: the origin of the clone this script is in
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Windows PowerShell 5.1's progress bar makes downloads many times slower
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false  # Japanese, whatever the console's code page
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$TaskName = 'task-hub watch'
$Root = $env:USERPROFILE
$Lib = Join-Path $Root '.local\lib\task-hub'
$GitDir = Join-Path $Root '.local\lib\git'  # MinGit, when there was no git
$BinDir = Join-Path $Root '.local\bin'
$State = Join-Path $Root '.local\state\task-hub'
$Manifest = Join-Path $State 'install-manifest.json'
$Shim = Join-Path $BinDir 'task.cmd'
$ShShim = Join-Path $BinDir 'task'  # for Git Bash, which Claude Code's Bash tool uses on Windows: it runs no .cmd
# empty when the profile has no Startup folder (GetFolderPath does not make it)
$Startup = [IO.Path]::Combine([Environment]::GetFolderPath('Startup', 'Create'), 'task-hub watch.lnk')
$GitHub = if ($env:TASK_INSTALL_GITHUB) { $env:TASK_INSTALL_GITHUB.TrimEnd('/') } else { 'https://github.com' }
$GitHubApi = if ($env:TASK_INSTALL_GITHUB_API) { $env:TASK_INSTALL_GITHUB_API.TrimEnd('/') } else { 'https://api.github.com' }
$NetHelp = 'ネットワーク(VPN、プロキシ)を確かめて、もう一度実行してください'
$label = '準備'
$changed = $false

function Say($text) { Write-Host "task-hub: $text" }
function Stop-Here($text, $help) { Write-Host "error: $text"; if ($help) { Write-Host "help: $help" }; exit 1 }
function Ok($result, $detail) { Write-Host "$($script:label): $result$(if ($detail) { "($detail)" })" }
function Die($what, $next) {  # what went wrong, and the one thing to do next
  Write-Host "$($script:label): 止まりました。$what"
  Write-Host "次にすること: $next"
  exit 1
}
function Tilde($p) { if ("$p".StartsWith("$Root\")) { '~' + "$p".Substring($Root.Length) } else { "$p" } }

function Runs($exe, [string[]]$a) {  # whether it runs and exits 0; what it printed (stdout, then stderr) in $script:Out
  $ErrorActionPreference = 'Continue'  # Windows PowerShell 5.1 would stop at a line on stderr
  try {
    $script:Out = @(& $exe @a 2>&1 | ForEach-Object { "$_" })
    return ($LASTEXITCODE -eq 0)
  } catch {
    $script:Out = @("$_")
    return $false
  }
}

function Find-App($name) {  # the program on PATH, as a full path, or $null
  Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 |
    ForEach-Object { $_.Source }
}

# --- the user's and the machine's environment (PATH) ---

function Open-Env($which, [bool]$write) {
  $hook = if ($which -eq 'User') { $env:TASK_INSTALL_USER_ENV } else { $env:TASK_INSTALL_MACHINE_ENV }
  if ($hook) { return [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($hook) }
  if ($which -eq 'User') { return [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment') }
  return [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager\Environment')
}

function Read-EnvPath($which) {  # expanded, as a new process gets it
  $k = Open-Env $which $false
  if (-not $k) { return '' }
  try { return [string]$k.GetValue('Path', '') } finally { $k.Close() }
}

function Update-ProcessPath {
  # ~\.local\bin, then the registry's PATH (what a new window gets), then this process's: Kiro may have been started
  # before git or Python was installed, and its PATH stays as it was
  $seen = @{}
  $parts = foreach ($p in @($BinDir) + ((Read-EnvPath 'Machine') -split ';') + ((Read-EnvPath 'User') -split ';') +
                         ($env:Path -split ';')) {
    $k = "$p".TrimEnd('\').ToLowerInvariant()
    if ($k -and -not $seen.ContainsKey($k)) { $seen[$k] = $true; $p }
  }
  $env:Path = $parts -join ';'
}

function Add-UserPath($dir) {  # puts $dir first on the user PATH; $true when it was not there
  $k = Open-Env 'User' $true
  try {
    # as stored, so entries such as %USERPROFILE%\x stay variables (REG_EXPAND_SZ)
    $now = $k.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    if (($now -split ';') -contains $dir) { return $false }
    $k.SetValue('Path', ((@($dir, $now) | Where-Object { $_ }) -join ';'), 'ExpandString')
  } finally { $k.Close() }
  if (-not $env:TASK_INSTALL_USER_ENV) {
    [Environment]::SetEnvironmentVariable('TASK_HUB_PATH_CHANGED', $null, 'User')  # tells Explorer, for new windows
  }
  return $true
}

# --- the manifest: what this script put there, for windows/uninstall.ps1 ---

function Read-Manifest {
  if (Test-Path $Manifest) {
    try { return [IO.File]::ReadAllText($Manifest) | ConvertFrom-Json } catch { }
  }
  return [pscustomobject]@{ version = 1 }
}

function Save-Manifest {
  New-Item -ItemType Directory -Force $State | Out-Null
  try {
    [IO.File]::WriteAllText("$Manifest.tmp", ($script:M | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
    Move-Item -Force "$Manifest.tmp" $Manifest
  } catch {
    Die "$(Tilde $Manifest) を書けませんでした" 'ユーザーフォルダーの空き容量と権限を確かめて、もう一度実行してください'
  }
}

function Set-Record($key, $value) {  # under "installed"; only what this script put there
  if (-not $script:M.installed) { $script:M | Add-Member -Force installed ([pscustomobject]@{}) }
  $script:M.installed | Add-Member -Force $key $value
  Save-Manifest
}

# --- downloads ---

function Fetch($url, $file) {
  try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $file -TimeoutSec 900 }
  catch { Die "ダウンロードできませんでした: $url" $NetHelp }
}

function Get-LatestTag($repo) {  # where releases/latest redirects to (no API calls), as kiro/install.sh does
  $url = ''
  try {
    $r = [Net.WebRequest]::Create("$GitHub/$repo/releases/latest")
    $r.Method = 'HEAD'
    $r.Timeout = 60000
    $resp = $r.GetResponse()
    $url = $resp.ResponseUri.AbsoluteUri
    $resp.Close()
  } catch [Net.WebException] {
    if ($_.Exception.Response) { $url = $_.Exception.Response.ResponseUri.AbsoluteUri }
  } catch { }
  if ($url -match '/releases/tag/([^/?#]+)$') { return [Uri]::UnescapeDataString($Matches[1]) }
  Die "$repo の最新の版を調べられませんでした" $NetHelp
}

function Get-ListedSum($list, $name) {  # from "<sha256>  <name>" lines
  foreach ($line in [IO.File]::ReadAllLines($list)) {
    $f = $line.Trim() -split '\s+', 2
    if ($f.Count -eq 2 -and $f[1].TrimStart('*') -eq $name) { return $f[0] }
  }
  return ''
}

function Confirm-Sum($file, $want) {  # stops unless the file's SHA-256 is $want
  $got = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant()
  if (-not $want -or $got -ne $want.ToLowerInvariant()) {
    Die "$(Split-Path -Leaf $file) のチェックサムが合いません(一覧: $want、実際: $got)。入れていません" `
      '時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください'
  }
}

function Expand-To($zip, $dir) {
  if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
  try { Expand-Archive -LiteralPath $zip -DestinationPath $dir -Force }
  catch { Die "$(Split-Path -Leaf $zip) を展開できませんでした" 'もう一度実行してください' }
}

function Install-Bin($src, $name) {  # $src -> ~\.local\bin\$name, replaced in one step
  New-Item -ItemType Directory -Force $BinDir | Out-Null
  $dst = Join-Path $BinDir $name
  try {
    Copy-Item -Force -LiteralPath $src "$dst.tmp"
    Move-Item -Force "$dst.tmp" $dst
  } catch {
    Die "$(Tilde $dst) に置けませんでした" 'ユーザーフォルダーの空き容量と権限を確かめて、もう一度実行してください'
  }
  return $dst
}

# --- stages ---

function Install-MinGit {  # git for Windows' own build for programs: a zip, no installer, no admin rights
  Write-Host "$($script:label): git(MinGit)を取っています…"
  $tag = Get-LatestTag 'git-for-windows/git'  # v2.56.0.windows.2 has MinGit-2.56.0.2-*.zip; .windows.1 has 2.56.0
  if ($tag -notmatch '^v(\d+\.\d+\.\d+)\.windows\.(\d+)$') {
    Die "Git for Windows の版の名前を読めませんでした($tag)" 'この表示を task-hub の担当者に知らせてください'
  }
  $ver = if ($Matches[2] -eq '1') { $Matches[1] } else { "$($Matches[1]).$($Matches[2])" }
  $asset = "MinGit-$ver-$(if ($script:Arch -eq 'arm64') { 'arm64' } else { '64-bit' }).zip"
  # no checksum file: the release lists each file's SHA-256 (as "digest", and in its notes)
  $want = ''
  try {
    $rel = Invoke-RestMethod -UseBasicParsing -Uri "$GitHubApi/repos/git-for-windows/git/releases/tags/$tag" -TimeoutSec 60
  } catch {
    Die "Git for Windows $tag のチェックサムを調べられませんでした" $NetHelp
  }
  $a = @($rel.assets | Where-Object { $_.name -eq $asset })[0]
  if ($a -and "$($a.digest)" -match '^sha256:([0-9a-f]{64})$') { $want = $Matches[1] }
  elseif ("$($rel.body)" -match ('(?m)^' + [regex]::Escape($asset) + '\s*\|\s*([0-9a-f]{64})')) { $want = $Matches[1] }
  $zip = Join-Path $script:Work $asset
  Fetch "$GitHub/git-for-windows/git/releases/download/$tag/$asset" $zip
  Confirm-Sum $zip $want
  if ((Test-Path $GitDir) -and $script:M.installed.git -ne $GitDir) {
    Die "$(Tilde $GitDir) がすでにあります(このインストーラが入れたものではありません)" `
      'そのフォルダーを別の場所に移してから、もう一度実行してください'
  }
  Expand-To $zip "$GitDir.tmp"
  if (Test-Path $GitDir) { Remove-Item -Recurse -Force $GitDir }
  Move-Item "$GitDir.tmp" $GitDir
  Set-Record 'git' $GitDir
  $cmd = Join-Path $GitDir 'cmd'
  if (Add-UserPath $cmd) { Set-Record 'git-path' $cmd }
  $env:Path = "$cmd;$env:Path"
  if (-not (Runs (Join-Path $cmd 'git.exe') @('--version'))) {
    Die '入れた git が動きません' '情シスに、ユーザーフォルダーの下に置いた実行ファイルを止めていないか確かめてください'
  }
  $script:changed = $true
  return $ver
}

function Stage-Prereq {
  $script:label = '1. 前提の確認'
  $mode = $ExecutionContext.SessionState.LanguageMode
  $cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
  if ("$mode" -ne 'FullLanguage') {
    Write-Host "$($script:label): 止まりました。この PC の PowerShell は機能が制限されています($mode)。"
    Write-Host '情シスへの依頼文:'
    Write-Host '  task-hub(業務ツール)を使うため、この PC の PowerShell で、スクリプトから .NET を使えるようにしてください'
    Write-Host "  (今は $mode です)。CPU $cpu、ユーザー $env:USERNAME"
    Write-Host '次にすること: 上の依頼文を情シスに送り、使えるようになったらもう一度実行してください'
    exit 1
  }
  switch ($cpu) {
    'AMD64' { $script:Arch = 'x64' }
    'ARM64' { $script:Arch = 'arm64' }
    default { Die "この CPU($cpu)には対応していません" 'docs/windows.md の手順で手作業で入れてください' }
  }
  $build = [Environment]::OSVersion.Version.Build
  $os = if ($build -ge 22000) { 'Windows 11' } else { "Windows 10(build $build。確かめているのは Windows 11 です)" }
  # gh, git and uv read HTTPS_PROXY, not Windows' settings: copy it from there (a PAC file included)
  $proxy = ''
  if (-not $env:HTTPS_PROXY) {
    try { $p = [Net.WebRequest]::GetSystemWebProxy().GetProxy([Uri]$GitHub) } catch { $p = $null }
    if ($p -and $p.Authority -ne ([Uri]$GitHub).Authority) { $env:HTTPS_PROXY = $proxy = $p.AbsoluteUri.TrimEnd('/') }
  }
  try {
    $r = [Net.WebRequest]::Create($GitHub)
    $r.Method = 'HEAD'
    $r.Timeout = 30000
    $r.GetResponse().Close()
  } catch {
    Die "GitHub($GitHub)に届きません$(if ($proxy) { "(プロキシ $proxy)" })" $NetHelp
  }
  $git = Find-App git
  if ($git -and (Runs $git @('--version'))) {
    $result, $gitNote = '済み', 'git'
  } else {
    $result, $gitNote = '入れました', "git $(Install-MinGit)(MinGit、$(Tilde $GitDir))"
  }
  Ok $result "$os $($script:Arch)、$gitNote、GitHub に接続$(if ($proxy) { "、プロキシ $proxy" })"
}

function Test-Python($p) {  # it runs, and is 3.10 or later
  if (-not $p -or -not (Test-Path -LiteralPath $p)) { return $false }
  return (Runs $p @('-c', 'import sys; sys.exit(sys.version_info < (3, 10))'))
}

function Find-Python {
  # the py launcher first: `python` may be the Microsoft Store stub, which runs nothing and says so on stderr
  foreach ($c in @(@('py', '-3'), @('python'))) {
    if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
    $args_ = @($c | Select-Object -Skip 1) + @('-X', 'utf8', '-c',
      'import sys; print(sys.executable); print(sys.version_info >= (3, 10))')
    if ((Runs $c[0] $args_) -and $script:Out.Count -ge 2 -and $script:Out[1] -eq 'True') { return $script:Out[0] }
  }
  return $null
}

function Stage-Python {
  $script:label = '2. Python'
  # the one an earlier run chose, if it still works: task.cmd keeps running the same Python
  if (Test-Python $script:M.python) {
    $script:Python = $script:M.python
    Ok 済み (Tilde $script:Python)
    return
  }
  $p = Find-Python
  if ($p) {
    $script:Python = $p
    $script:M | Add-Member -Force python $p
    Save-Manifest
    Ok 済み "$(Tilde $p) を使います"
    return
  }
  # none: uv (a single program) fetches Python into the user folder
  $uv = Find-App uv
  if (-not $uv) {
    Write-Host "$($script:label): uv を取っています…"
    $triple = if ($script:Arch -eq 'arm64') { 'aarch64-pc-windows-msvc' } else { 'x86_64-pc-windows-msvc' }
    $tag = Get-LatestTag 'astral-sh/uv'
    $asset = "uv-$triple.zip"
    $zip = Join-Path $script:Work $asset
    Fetch "$GitHub/astral-sh/uv/releases/download/$tag/$asset" $zip
    Fetch "$GitHub/astral-sh/uv/releases/download/$tag/$asset.sha256" "$zip.sha256"
    Confirm-Sum $zip (Get-ListedSum "$zip.sha256" $asset)
    Expand-To $zip (Join-Path $script:Work 'uv')
    $uv = Install-Bin (Join-Path $script:Work 'uv\uv.exe') 'uv.exe'
    Set-Record 'uv' $uv
  }
  Write-Host "$($script:label): uv で Python 3.12 を取っています…"
  # trust Windows' certificate store (a company's SSL inspection), not only uv's own list; the name changed in uv 0.9
  $env:UV_NATIVE_TLS = '1'
  $env:UV_SYSTEM_CERTS = '1'
  if (-not (Runs $uv @('python', 'install', '3.12'))) {
    Die "uv で Python を入れられませんでした($($script:Out | Select-Object -Last 1))" `
      'ネットワーク(releases.astral.sh に届くか)を確かめて、もう一度実行してください'
  }
  Set-Record 'uv-python' '3.12'
  $p = if (Runs $uv @('python', 'find', '--managed-python', '3.12')) {
    @($script:Out | Where-Object { $_ -match '\.exe$' })[0]
  }
  if (-not (Test-Python $p)) {
    Die "uv で入れた Python が見つからないか、動きません($p)" 'もう一度実行してください。続くときは task-hub の担当者に知らせてください'
  }
  $script:Python = $p
  $script:M | Add-Member -Force python $p
  Save-Manifest
  $script:changed = $true
  Ok 入れました "uv で Python 3.12、$(Tilde $p)"
}

function Stage-Gh {
  $script:label = '3. gh'
  $gh = Find-App gh
  if ($gh -and (Runs $gh @('--version'))) {
    $script:Gh = $gh
    Ok 済み (Tilde $gh)
    return
  }
  Write-Host "$($script:label): GitHub CLI を取っています…"
  $tag = Get-LatestTag 'cli/cli'
  $ver = $tag.TrimStart('v')
  $asset = "gh_${ver}_windows_$(if ($script:Arch -eq 'arm64') { 'arm64' } else { 'amd64' }).zip"
  $sums = "gh_${ver}_checksums.txt"
  $zip = Join-Path $script:Work $asset
  Fetch "$GitHub/cli/cli/releases/download/$tag/$asset" $zip
  Fetch "$GitHub/cli/cli/releases/download/$tag/$sums" (Join-Path $script:Work $sums)
  Confirm-Sum $zip (Get-ListedSum (Join-Path $script:Work $sums) $asset)
  Expand-To $zip (Join-Path $script:Work 'gh')
  $script:Gh = Install-Bin (Join-Path $script:Work 'gh\bin\gh.exe') 'gh.exe'
  Set-Record 'gh' $script:Gh
  if (-not (Runs $script:Gh @('--version'))) {
    Die '入れた gh が動きません' '情シスに、ユーザーフォルダーの下に置いた実行ファイルを止めていないか確かめてください'
  }
  $script:changed = $true
  Ok 入れました "gh $ver、$(Tilde $script:Gh)"
}

function Stop-Watch {
  # the loop (task-watch.ps1) and the `task watch` it started, and nothing else: a run goes on, and so does an agent
  # whose prompt happens to name task-watch.ps1. Not Stop-ScheduledTask, which can end every process the task started
  $loop = "-File `"$(Join-Path $Lib 'windows\task-watch.ps1')`""
  Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($loop) } |
    ForEach-Object {
      $id = $_.ProcessId
      Get-CimInstance Win32_Process -Filter "ParentProcessId = $id" |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
      Say "stopped task watch (process $id)"
    }
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Say "removed the scheduled task '$TaskName'"
  }
  if (Test-Path $Startup) { Remove-Item $Startup; Say "removed $Startup" }
}

if ($Uninstall) {
  Stop-Watch
  foreach ($f in $Shim, $ShShim) { if (Test-Path $f) { Remove-Item $f; Say "removed $f" } }
  Say "left in place: $Lib, ~\.config\task-hub, ~\.local\state\task-hub, ~\.local\share\task-hub"
  exit 0
}

# --- main ---

Write-Host 'task-hub をセットアップします(管理者権限は使いません)'
New-Item -ItemType Directory -Force $State | Out-Null
# what an earlier run left when it stopped, then a work folder for this one
Get-ChildItem $State -Directory -Filter 'install.*' -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$Work = Join-Path $State "install.$PID"
New-Item -ItemType Directory -Force $Work | Out-Null
$M = Read-Manifest
Update-ProcessPath

Stage-Prereq
Stage-Python
Stage-Gh
Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue

# the clone task-hub runs from (never the one you develop in: switching branches there would change running code)
if (Test-Path (Join-Path $Lib '.git')) {
  git -C $Lib pull -q --ff-only
  if ($LASTEXITCODE -ne 0) { Stop-Here "could not update $Lib" "run: git -C `"$Lib`" status" }
  Say "updated $Lib"
} else {
  if (-not $From) { $From = (git -C (Join-Path $PSScriptRoot '..') remote get-url origin) }
  if (-not $From) { Stop-Here 'no clone URL' 'pass -From <url of task-hub>' }
  New-Item -ItemType Directory -Force (Split-Path $Lib) | Out-Null
  git clone -q $From $Lib
  if ($LASTEXITCODE -ne 0) { Stop-Here "could not clone $From" 'check that gh auth login was done and you can open the repository' }
  Say "cloned $From to $Lib"
}

# `task` on PATH
New-Item -ItemType Directory -Force $BinDir | Out-Null
$task = Join-Path $Lib 'bin\task'
# cmd.exe reads a .cmd in the console's code page, which may not have the letters of the user folder's name (a
# Japanese name on a Chinese Windows): paths under it are written as %USERPROFILE%, which cmd.exe expands as it runs
$cmdPath = { param($p) if ($p.StartsWith("$Root\")) { '%USERPROFILE%' + $p.Substring($Root.Length) } else { $p } }
$oem = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
[IO.File]::WriteAllText($Shim,
  "@setlocal`r`n@set PYTHONUTF8=1`r`n@`"$(& $cmdPath $Python)`" `"$(& $cmdPath $task)`" %*`r`n", $oem)
$posix = { param($p) $p -replace '\\', '/' }
[IO.File]::WriteAllText($ShShim, "#!/bin/sh`nPYTHONUTF8=1 exec `"$(& $posix $Python)`" `"$(& $posix $task)`" `"`$@`"`n",
  (New-Object Text.UTF8Encoding $false))
if (Add-UserPath $BinDir) {
  Set-Record 'user-path' $BinDir
  Say "added $BinDir to your PATH (new terminals see it)"
}
$env:Path = "$BinDir;$env:Path"
& $Shim --version
if ($LASTEXITCODE -ne 0) { Stop-Here "$Shim does not run" "run it by hand to see why: & `"$Shim`" --version" }

if (-not $Watch) {
  Say 'done. Next: docs/windows.md (config, then `task list`). To start Ready cards without a terminal: install.ps1 -Watch'
  exit 0
}

# `task watch` at every logon, restarted when it ends
Stop-Watch
$script = Join-Path $Lib 'windows\task-watch.ps1'
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Python `"$Python`""
$registered = $false
try {
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
  # no time limit, on battery too, and started again if it ever stops
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'task-hub: start Ready cards (docs/windows.md)' | Out-Null
  $registered = $true
} catch {
  # some company PCs refuse new scheduled tasks; the Startup folder needs no permission
  Say "Task Scheduler refused ($($_.Exception.Message.Trim())); using the Startup folder instead"
  $shell = New-Object -ComObject WScript.Shell
  $link = $shell.CreateShortcut($Startup)
  $link.TargetPath = 'powershell.exe'
  $link.Arguments = $arguments
  $link.WindowStyle = 7  # minimized: -WindowStyle Hidden hides it once PowerShell starts
  $link.Save()
  Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden
  Say "added $Startup and started it"
}
if ($registered) {  # outside the try: a failing start must not also add the Startup shortcut (two watches)
  Start-ScheduledTask -TaskName $TaskName
  Say "registered and started the scheduled task '$TaskName'"
}
Say "log: $(Join-Path $Root '.local\state\task-hub\watch.log')"
