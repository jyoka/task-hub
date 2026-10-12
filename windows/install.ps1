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
  4. kiro-cli: the one on PATH or the official installer's (put on the user PATH), else the official MSI unpacked
     with msiexec /a (no admin rights) into ~\.local\lib\kiro-cli.
  5. Logins, gh's (with the project scope, and git using it) and kiro-cli's: when one is missing it opens a PowerShell
     window for it, and stops; run this again once it is done.
  6. task-hub: clones it to ~\.local\lib\task-hub, on the newest kiro-v<number> tag if any (later runs switch to a
     newer one; a clone someone made on a branch is only pulled), writes ~\.local\bin\task.cmd, which runs bin\task
     with that Python, and `task` for Git Bash, and puts ~\.local\bin on the user PATH.
  With -Watch it also starts `task watch` at every logon (Task Scheduler; the Startup folder when that is refused)
  and starts it now. -Uninstall removes what it recorded (windows\uninstall.ps1 -Yes); the board, logins and data stay.
  Downloads are checked against the release's SHA-256. Safe to run again.
  For tests: TASK_INSTALL_GITHUB replaces https://github.com, TASK_INSTALL_GITHUB_API https://api.github.com,
  TASK_INSTALL_KIRO_CLI https://prod.download.cli.kiro.dev, TASK_INSTALL_MSIEXEC msiexec.exe,
  TASK_INSTALL_PROGRAM_FILES $env:ProgramFiles, and TASK_INSTALL_OPEN_WINDOW is run with a login's script instead of
  opening a window. TASK_INSTALL_USER_ENV / TASK_INSTALL_MACHINE_ENV name keys under HKCU to use as the user's and
  the machine's environment (PATH), so a test changes no real PATH.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch
#>
param(
  [switch]$Watch,
  [switch]$Uninstall,
  [string]$From = "",  # where to clone from; default: the origin of the clone this script is in
  [string]$Ref = ""  # for developers: the version (branch or tag) to put in ~\.local\lib\task-hub, this run only
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Windows PowerShell 5.1's progress bar makes downloads many times slower
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false  # Japanese, whatever the console's code page
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$TaskName = 'task-hub watch'
$Root = $env:USERPROFILE
$Lib = Join-Path $Root '.local\lib\task-hub'
$GitDir = Join-Path $Root '.local\lib\git'  # MinGit, when there was no git
$KiroDir = Join-Path $Root '.local\lib\kiro-cli'  # kiro-cli, when there was none
$KiroHome = Join-Path $Root '.kiro'  # what Kiro reads: skills, steering
$BinDir = Join-Path $Root '.local\bin'
$State = Join-Path $Root '.local\state\task-hub'
$Manifest = Join-Path $State 'install-manifest.json'
$Shim = Join-Path $BinDir 'task.cmd'
$ShShim = Join-Path $BinDir 'task'  # for Git Bash, which Claude Code's Bash tool uses on Windows: it runs no .cmd
# empty when the profile has no Startup folder (GetFolderPath does not make it)
$Startup = [IO.Path]::Combine([Environment]::GetFolderPath('Startup', 'Create'), 'task-hub watch.lnk')
$GitHub = if ($env:TASK_INSTALL_GITHUB) { $env:TASK_INSTALL_GITHUB.TrimEnd('/') } else { 'https://github.com' }
$GitHubApi = if ($env:TASK_INSTALL_GITHUB_API) { $env:TASK_INSTALL_GITHUB_API.TrimEnd('/') } else { 'https://api.github.com' }
$KiroDownload = if ($env:TASK_INSTALL_KIRO_CLI) { $env:TASK_INSTALL_KIRO_CLI.TrimEnd('/') } else { 'https://prod.download.cli.kiro.dev' }
$Msiexec = if ($env:TASK_INSTALL_MSIEXEC) { $env:TASK_INSTALL_MSIEXEC } else { 'msiexec.exe' }
$ProgramFiles = if ($env:TASK_INSTALL_PROGRAM_FILES) { $env:TASK_INSTALL_PROGRAM_FILES } else { $env:ProgramFiles }
$Marker = 'task-hub: made by windows/install.ps1'
$NetHelp = 'ネットワーク(VPN、プロキシ)を確かめて、もう一度実行してください'
$label = '準備'
$changed = $false
$Todo = ''  # what is left to do by hand, said on the last line
$Restart = $false  # stage 9 changed what Kiro reads when it starts

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
    $script:Out = @($null | & $exe @a 2>&1 | ForEach-Object { "$_" })
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
  # .NET, not Get-FileHash or Expand-Archive: they live in modules, and 5.1 may not load them when PSModulePath has
  # PowerShell 7's folders (seen on GitHub Actions)
  $sha = [Security.Cryptography.SHA256]::Create()
  $s = [IO.File]::OpenRead($file)
  try { $got = -join ($sha.ComputeHash($s) | ForEach-Object { $_.ToString('x2') }) } finally { $s.Dispose(); $sha.Dispose() }
  if (-not $want -or $got -ne $want.ToLowerInvariant()) {
    Die "$(Split-Path -Leaf $file) のチェックサムが合いません(一覧: $want、実際: $got)。入れていません" `
      '時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください'
  }
}

function Expand-To($zip, $dir) {
  if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
  try { Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory($zip, $dir) }
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

function Install-KiroCli {
  # The official script runs the MSI with msiexec /i, into Program Files: admin rights. msiexec /a only unpacks it
  # (an "administrative install"), which needs none; kiro-cli is one program, and runs from wherever it is.
  Write-Host "$($script:label): Kiro CLI を取っています(約 300 MB。公式の手順ではありません: 公式は管理者権限の要る Program Files に入れるため)…"
  $list = Join-Path $script:Work 'kiro-manifest.json'
  Fetch "$KiroDownload/stable/latest/manifest.json" $list
  try {
    $pkg = @(([IO.File]::ReadAllText($list) | ConvertFrom-Json).packages |
      Where-Object { $_.os -eq 'windows' -and $_.kind -eq 'msi' -and $_.architecture -eq 'x86_64' })[0]
  } catch { $pkg = $null }
  if (-not $pkg) {
    Die 'Kiro CLI の一覧(manifest.json)に Windows 用の MSI がありません' `
      '時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください'
  }
  $msi = Join-Path $script:Work 'kiro-cli.msi'
  Fetch "$KiroDownload/stable/$($pkg.download)" $msi
  Confirm-Sum $msi "$($pkg.sha256)"
  $unpacked = Join-Path $script:Work 'kiro-cli'
  $p = Start-Process $Msiexec -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$unpacked`"" -Wait -PassThru -WindowStyle Hidden
  $exe = Get-ChildItem -LiteralPath $unpacked -Recurse -Filter 'kiro-cli.exe' -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($p.ExitCode -ne 0 -or -not $exe) {
    Die "Kiro CLI の MSI を展開できませんでした(msiexec の終了コード $($p.ExitCode))。入れていません" `
      '時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください'
  }
  if ((Test-Path $KiroDir) -and $script:M.installed.'kiro-cli' -ne $KiroDir) {
    Die "$(Tilde $KiroDir) がすでにあります(このインストーラが入れたものではありません)" `
      'そのフォルダーを別の場所に移してから、もう一度実行してください'
  }
  New-Item -ItemType Directory -Force $KiroDir | Out-Null
  $dst = Join-Path $KiroDir 'kiro-cli.exe'
  try {
    Copy-Item -Force -LiteralPath $exe.FullName "$dst.tmp"
    Move-Item -Force "$dst.tmp" $dst
  } catch {
    Die "$(Tilde $dst) に置けませんでした" 'ユーザーフォルダーの空き容量と権限を確かめて、もう一度実行してください'
  }
  Set-Record 'kiro-cli' $KiroDir
  if (-not (Runs $dst @('--version'))) {
    Die '入れた kiro-cli が動きません' '情シスに、ユーザーフォルダーの下に置いた実行ファイルを止めていないか確かめてください'
  }
  return $dst
}

function Stage-KiroCli {
  $script:label = '4. kiro-cli'
  $found = Find-App kiro-cli
  if ($found -and (Runs $found @('--version'))) {
    $script:Kiro = $found
    Ok 済み (Tilde $found)
    return
  }
  # not on PATH: where the official installer puts it, or where an earlier run of this script did, else get it
  $found, $result = $null, 'PATH に足しました'
  foreach ($k in (Join-Path $ProgramFiles 'Kiro-Cli\kiro-cli.exe'), (Join-Path $KiroDir 'kiro-cli.exe')) {
    if ((Test-Path -LiteralPath $k) -and (Runs $k @('--version'))) { $found = $k; break }
  }
  if (-not $found) { $found, $result = (Install-KiroCli), '入れました' }
  $dir = Split-Path $found
  if (Add-UserPath $dir) { Set-Record 'kiro-cli-path' $dir }
  $env:Path = "$dir;$env:Path"
  $script:Kiro = $found
  $script:changed = $true
  Ok $result (Tilde $found)
}

function Get-GhUser {  # the login and the scopes of gh's token, in $script:GhUser and $script:GhScopes
  $script:GhUser, $script:GhScopes = '', ''
  if (-not (Runs $script:Gh @('api', '-i', 'user'))) { return $false }
  foreach ($line in $script:Out) {
    if ($line -match '^x-oauth-scopes:\s*(.*)$') { $script:GhScopes = $Matches[1].Trim() }
    if ($line -match '^\{"login":"([^"]+)"') { $script:GhUser = $Matches[1] }  # the body starts with it
  }
  return [bool]$script:GhUser
}

function Test-GitUsesGh {  # gh is git's credential helper for GitHub (gh auth setup-git)
  Runs git @('config', '--global', '--get-all', 'credential.https://github.com.helper') | Out-Null
  return [bool]($script:Out | Where-Object { $_ -match 'auth git-credential' })
}

function Open-LoginWindow($name, [string[]]$command) {
  # A login asks its questions in a window of its own: Kiro's chat cannot answer them. The window gets this
  # process's environment (the proxy included); the script removes itself when it starts.
  $file = Join-Path $State $name
  $quoted = ($command | ForEach-Object { "'" + ($_ -replace "'", "''") + "'" }) -join ' '
  $body = "# $Marker. Runs in its own window, where the login can ask its questions.`r`n" +
    "Remove-Item -LiteralPath `$PSCommandPath -ErrorAction SilentlyContinue`r`n" +
    "& $quoted`r`n" +
    "Write-Host ''`r`n" +
    "Write-Host '終わったら、この窓を閉じて、もう一度 windows\install.ps1 を実行してください(Kiro のチャットなら「続けて」)'`r`n" +
    "Read-Host 'Enter で閉じます' | Out-Null`r`n"
  try {
    [IO.File]::WriteAllText($file, $body, (New-Object Text.UTF8Encoding $true))
    if ($env:TASK_INSTALL_OPEN_WINDOW) { & $env:TASK_INSTALL_OPEN_WINDOW $file }
    else { Start-Process powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$file`"" }
  } catch {
    Die "ログインの窓を開けませんでした($($_.Exception.Message))" `
      "エクスプローラーで $(Tilde $file) を右クリックして「PowerShell で実行」で進め、終わったらもう一度実行してください"
  }
}

function Stage-GhLogin {
  $script:label = '5. GitHub のログイン'
  if ((Get-GhUser) -and (", $($script:GhScopes)," -match ', project,')) {
    Remove-Item -LiteralPath (Join-Path $State 'gh-login.ps1') -ErrorAction SilentlyContinue
    # git (task-hub's clones and pushes) uses the same login; a login in a window does not set that up
    if (Test-GitUsesGh) {
      Ok 済み $script:GhUser
      return
    }
    if (-not (Runs $script:Gh @('auth', 'setup-git', '-h', 'github.com'))) {
      Die "git に GitHub のログインを設定できませんでした($($script:Out | Select-Object -Last 1))" 'もう一度実行してください'
    }
    $script:changed = $true
    Ok 設定しました "$($script:GhUser)、git も gh のログインを使います"
    return
  }
  if ($script:GhUser) {
    $command, $need = @('auth', 'refresh', '-h', 'github.com', '-s', 'project'), 'Projects の権限(project)が要ります'
  } else {
    $command, $need = @('auth', 'login', '--web', '-s', 'project', '-h', 'github.com', '-p', 'https'), 'GitHub にログインしていません'
  }
  if ($env:GH_TOKEN -or $env:GITHUB_TOKEN) {  # gh refuses to log in while one is set
    Die "${need}。環境変数 GH_TOKEN(または GITHUB_TOKEN)があるので、gh ではログインできません" `
      'その環境変数を外すか、project の権限があるトークンにしてから、もう一度実行してください'
  }
  Open-LoginWindow 'gh-login.ps1' (@($script:Gh) + $command)
  Die "${need}。開いた窓で、案内に沿ってブラウザで承認してください" '承認が終わったら、もう一度実行してください'
}

function Stage-KiroLogin {
  $script:label = '5. kiro-cli のログイン'
  if (Runs $script:Kiro @('whoami')) {
    Remove-Item -LiteralPath (Join-Path $State 'kiro-login.ps1') -ErrorAction SilentlyContinue
    Ok 済み
    return
  }
  # kiro-cli login first asks how to log in, in a menu that needs a window
  Open-LoginWindow 'kiro-login.ps1' @($script:Kiro, 'login')
  Die 'kiro-cli にログインしていません。開いた窓で、ログインの方法を選んでブラウザで承認してください' `
    'ログインが終わったら、もう一度実行してください'
}

function GitLib {  # git in the clone; $true when it exits 0, what it printed in $script:Out
  return (Runs git (@('-C', $Lib) + $args))
}

function Get-NewestKiroTag($names) {  # of tag names, kiro-v<number>, numbers compared as numbers
  $names | Where-Object { $_ -match '^kiro-v\d+$' } | Sort-Object { [int]$_.Substring(6) } | Select-Object -Last 1
}

function Get-CloneVersion {  # the kiro-v* tag the clone is on, else its branch and commit (or tag, or commit)
  if (GitLib symbolic-ref -q --short HEAD) {
    $b = $script:Out[0]
    GitLib rev-parse --short HEAD | Out-Null
    return "$b $($script:Out[0])"
  }
  GitLib tag --points-at HEAD | Out-Null
  $t = Get-NewestKiroTag $script:Out
  if ($t) { return $t }
  if (GitLib describe --tags --exact-match HEAD) { return $script:Out[0] }
  GitLib rev-parse --short HEAD | Out-Null
  return $script:Out[0]
}

function Switch-To($v) {  # a tag or a branch of origin, already fetched. The version there still works if it fails
  if (GitLib rev-parse -q --verify "refs/tags/$v") {
    $ok = GitLib checkout -q --detach "refs/tags/$v"
  } elseif (GitLib rev-parse -q --verify "refs/remotes/origin/$v") {
    $ok = (GitLib checkout -q $v) -and (GitLib pull --ff-only -q)
  } else {
    Die "$v という版(ブランチかタグ)がありません" '-Ref の名前を確かめて、もう一度実行してください'
  }
  if (-not $ok) {
    Write-Host "$($script:label): $v に切り替えられませんでした($($script:Out | Select-Object -Last 1))。今の版のまま進めます"
  }
}

function Write-Shim($file, $want, $enc, $key) {  # $true when it wrote it
  $now = if (Test-Path -LiteralPath $file) { [IO.File]::ReadAllText($file, $enc) } else { $null }
  $wrote = $now -ne $want
  if ($wrote) {
    try { [IO.File]::WriteAllText($file, $want, $enc) }
    catch { Die "$(Tilde $file) を書けませんでした" 'ユーザーフォルダーの空き容量と権限を確かめて、もう一度実行してください' }
  }
  if ($script:M.installed.$key -ne $file) { Set-Record $key $file }
  return $wrote
}

function Stage-TaskHub {
  $script:label = '6. task-hub 本体'
  $did = @()
  $env:GIT_TERMINAL_PROMPT = '0'  # fail instead of waiting for a password nobody can type
  $stale = { Write-Host "$($script:label): $(Tilde $Lib) を更新できませんでした($($script:Out | Select-Object -Last 1))。今の版のまま進めます" }
  if (Test-Path (Join-Path $Lib '.git')) {
    $before = Get-CloneVersion
    $branch = if (GitLib symbolic-ref -q --short HEAD) { $script:Out[0] } else { '' }
    # The installer's clone (in the manifest, or not on a branch) follows the newest kiro-v*. A clone on a branch
    # that someone made by hand (docs/windows.md's earlier install, a developer's) is only pulled, as before.
    if (-not $Ref -and -not $script:M.installed.'task-hub' -and $branch) {
      if (-not (GitLib pull --ff-only -q)) { & $stale }
    } elseif (-not (GitLib fetch -q --tags)) {
      & $stale  # the version there still works: go on with it
    } elseif ($Ref) {
      Switch-To $Ref
    } else {
      GitLib tag -l 'kiro-v*' | Out-Null
      $newest = Get-NewestKiroTag $script:Out
      $current = ''
      if (-not $branch) {
        GitLib tag --points-at HEAD | Out-Null
        $current = Get-NewestKiroTag $script:Out
      }
      if ($newest -and (-not $current -or [int]$newest.Substring(6) -gt [int]$current.Substring(6))) {
        Switch-To $newest
      } elseif ($branch) {  # no release yet: the branch, as before
        if (-not (GitLib pull --ff-only -q)) { & $stale }
      }
    }
    $after = Get-CloneVersion
    if ($before -ne $after) { $did += "$before → $after" }
  } elseif (Test-Path $Lib) {
    Die "$(Tilde $Lib) がありますが、git の clone ではありません" '中身を確かめて別の場所に移してから、もう一度実行してください'
  } else {
    $url = $From
    if (-not $url -and (Runs git @('-C', (Join-Path $PSScriptRoot '..'), 'remote', 'get-url', 'origin'))) { $url = $script:Out[0] }
    if (-not $url) { $url = 'https://github.com/jyoka/task-hub.git' }
    New-Item -ItemType Directory -Force (Split-Path $Lib) | Out-Null
    $branchArgs = if ($Ref) { @('-b', $Ref) } else { @() }
    if (-not (Runs git (@('clone', '-q') + $branchArgs + @($url, $Lib)))) {
      Die "$url$(if ($Ref) { " の $Ref" }) を clone できませんでした($($script:Out | Select-Object -Last 1))" `
        'GitHub でこのリポジトリを読めるか(-Ref を付けたなら、その版の名前も)確かめて、もう一度実行してください'
    }
    if (-not $Ref) {
      GitLib tag -l 'kiro-v*' | Out-Null
      $newest = Get-NewestKiroTag $script:Out
      if ($newest -and -not (GitLib checkout -q --detach "refs/tags/$newest")) {
        Die "$newest に切り替えられませんでした($($script:Out | Select-Object -Last 1))" 'もう一度実行してください'
      }
    }
    Set-Record 'task-hub' $Lib
    $did += "clone($(Get-CloneVersion))"
  }

  # task.cmd for PowerShell and cmd.exe, and `task` for Git Bash, which Claude Code's Bash tool uses: it runs no .cmd
  New-Item -ItemType Directory -Force $BinDir | Out-Null
  $task = Join-Path $Lib 'bin\task'
  # cmd.exe reads a .cmd in the console's code page, which may not have the letters of the user folder's name (a
  # Japanese name on a Chinese Windows): paths under it are written as %USERPROFILE%, which cmd.exe expands as it runs
  $cmdPath = { param($p) if ($p.StartsWith("$Root\")) { '%USERPROFILE%' + $p.Substring($Root.Length) } else { $p } }
  $posix = { param($p) $p -replace '\\', '/' }
  $oem = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
  $utf8 = New-Object Text.UTF8Encoding $false
  $shims = @(
    @($Shim, $oem, 'task', '^@setlocal\r\n@set PYTHONUTF8=1\r\n@".*" ".*\\bin\\task" %\*\r\n$',
      "@rem $Marker`r`n@setlocal`r`n@set PYTHONUTF8=1`r`n@`"$(& $cmdPath $script:Python)`" `"$(& $cmdPath $task)`" %*`r`n"),
    @($ShShim, $utf8, 'task-sh', '^#!/bin/sh\nPYTHONUTF8=1 exec ".*" ".*/bin/task" "\$@"\n$',
      "#!/bin/sh`n# $Marker`nPYTHONUTF8=1 exec `"$(& $posix $script:Python)`" `"$(& $posix $task)`" `"`$@`"`n"))
  foreach ($s in $shims) {  # what install.ps1 wrote before it marked them is taken over; anything else is someone's
    if (Test-Path -LiteralPath $s[0]) {
      $now = [IO.File]::ReadAllText($s[0], $s[1])
      if (-not $now.Contains($Marker) -and $now -notmatch $s[3]) {
        Die "$(Tilde $s[0]) がすでにあります(このインストーラが作ったものではありません)" 'それを消すか移してから、もう一度実行してください'
      }
    }
  }
  foreach ($s in $shims) {
    if (Write-Shim $s[0] $s[4] $s[1] $s[2]) { $did += Tilde $s[0] }
  }
  if (Add-UserPath $BinDir) {
    Set-Record 'user-path' $BinDir
    $did += 'ユーザーの PATH に ~\.local\bin'
  }
  if (-not (Runs $Shim @('--version'))) {
    Die "$(Tilde $Shim) が動きません($($script:Out | Select-Object -Last 1))" `
      'この表示を task-hub の担当者に知らせてください'
  }
  if ($did) {
    $script:changed = $true
    Ok 入れました ($did -join '、')
  } else {
    Ok 済み "$(Tilde $Lib)($(Get-CloneVersion))、$(Tilde $Shim)"
  }
}

function Invoke-Helper {  # kiro/install-board: the board and config.ini, where GraphQL and INI are easier in Python
  $ErrorActionPreference = 'Continue'
  & $script:Python (Join-Path $PSScriptRoot '..\kiro\install-board') @args 2>&1 | ForEach-Object { Write-Host "$_" }
  $code = $LASTEXITCODE
  $todo = Join-Path $script:Work 'todo'
  if (Test-Path $todo) { $script:Todo = [IO.File]::ReadAllText($todo).Trim() }
  switch ($code) {
    0 { }
    3 { $script:changed = $true }
    1 { exit 1 }  # it said why and what to do next
    default { Die "思わぬエラーで終わりました(終了コード $code)" 'この表示を task-hub の担当者に知らせてください' }
  }
}

function Stage-Board {
  $script:label = '7. ボード'
  Invoke-Helper board $script:label $script:GhUser $script:Work
}

function Stage-Config {
  $script:label = '8. 設定'
  $config = Join-Path $Root '.config\task-hub\config.ini'
  $new = -not (Test-Path $config)
  Invoke-Helper config $script:label $script:Work
  if ($new -and (Test-Path $config)) { Set-Record 'config' $config }
}

function Get-RealPath($p) {  # where a junction (or a link) leads, else the path itself
  $item = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
  if ($item -and $item.LinkType -and $item.Target) { return [IO.Path]::GetFullPath(@($item.Target)[0]).TrimEnd('\') }
  return [IO.Path]::GetFullPath($p).TrimEnd('\')
}

function Get-Sha256($file) {
  # .NET, not Get-FileHash: see Confirm-Sum
  $sha = [Security.Cryptography.SHA256]::Create()
  $s = [IO.File]::OpenRead($file)
  try { return -join ($sha.ComputeHash($s) | ForEach-Object { $_.ToString('x2') }) } finally { $s.Dispose(); $sha.Dispose() }
}

function Set-Sum($key, $value) {  # under "sha256": the copies this script owns, checked before it changes them
  if (-not $script:M.sha256) { $script:M | Add-Member -Force sha256 ([pscustomobject]@{}) }
  $script:M.sha256 | Add-Member -Force $key $value
  Save-Manifest
}

function Stage-Kiro {
  $script:label = '9. Kiro との連携'
  $did, $kept = @(), @()
  # Skills are folders: a junction, which needs no admin rights (a symbolic link does). A link that leads to the
  # clone already (made by hand) is fine; one that leads elsewhere, or a folder of someone's own, is left alone.
  foreach ($s in 'task', 'chief') {
    $target = Join-Path $Lib "skills\$s"
    $link = Join-Path $KiroHome "skills\$s"
    if (Test-Path -LiteralPath $link) {
      if ((Get-RealPath $link) -ne (Get-RealPath $target)) { $kept += Tilde $link }
      continue
    }
    try {
      New-Item -ItemType Directory -Force (Split-Path $link) | Out-Null
      New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    } catch {
      Die "$(Tilde $link) を作れませんでした($($_.Exception.Message))" 'ユーザーフォルダーの空き容量と権限を確かめて、もう一度実行してください'
    }
    Set-Record "kiro-skill-$s" $link
    $did += "$(Tilde $link)(ジャンクション)"
  }
  # Steering is a file: a copy (a link to a file needs admin rights), made again when the clone's changes. Only a
  # copy this script made, and nobody changed since (its SHA-256), is replaced.
  $src = Join-Path $Lib 'kiro\steering\task-hub.md'
  $dst = Join-Path $KiroHome 'steering\task-hub.md'
  $want = Get-Sha256 $src
  $how = $null
  if (-not (Test-Path -LiteralPath $dst)) {
    $how = 'コピー'
  } elseif ((Get-Sha256 $dst) -ne $want) {
    if ($script:M.installed.'kiro-steering' -ne $dst -or (Get-Sha256 $dst) -ne $script:M.sha256.'kiro-steering') {
      Die "$(Tilde $dst) は、このインストーラが入れた内容と確認できないので書き換えていません" `
        '中身を確かめて別の場所に移してから、もう一度実行してください'
    }
    $how = 'コピーし直し'  # task-hub was updated
  }
  if ($how) {
    try {
      New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
      Copy-Item -Force -LiteralPath $src "$dst.tmp"
      Move-Item -Force "$dst.tmp" $dst
    } catch {
      Die "$(Tilde $dst) に置けませんでした" 'ユーザーフォルダーの空き容量と権限を確かめて、もう一度実行してください'
    }
    Set-Record 'kiro-steering' $dst
    Set-Sum 'kiro-steering' $want
    $did += "$(Tilde $dst)($how)"
  }
  $note = if ($kept) { "。$($kept -join '、') は別のものを指しているので、そのままにしました" } else { '' }
  if ($did) {
    $script:changed = $true
    $script:Restart = $true
    Ok 入れました "$($did -join '、')。Kiro を再起動すると読み込まれます$note"
  } else {
    Ok 済み "スキル、steering$note"
  }
}

function Stage-Watch {
  $script:label = '10. 常駐'
  if (-not $Watch) {
    Ok 飛ばしました '任意です。Ready のカードを自動で始めるときは -Watch を付けて実行します'
    return
  }
  # `task watch` at every logon, restarted when it ends. Started again here, so a new version of task-hub is used
  Stop-Watch
  $script = Join-Path $Lib 'windows\task-watch.ps1'
  $arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Python `"$($script:Python)`""
  $registered, $refused = $false, ''
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
    $refused = $_.Exception.Message.Trim()
    try {
      $shell = New-Object -ComObject WScript.Shell
      $link = $shell.CreateShortcut($Startup)
      $link.TargetPath = 'powershell.exe'
      $link.Arguments = $arguments
      $link.WindowStyle = 7  # minimized: -WindowStyle Hidden hides it once PowerShell starts
      $link.Save()
      Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden
    } catch {
      Die "常駐を登録できませんでした(タスク スケジューラ: $refused、スタートアップ フォルダー: $($_.Exception.Message.Trim()))" `
        'この表示を task-hub の担当者に知らせてください'
    }
  }
  $log = Tilde (Join-Path $State 'watch.log')
  $script:changed = $true
  if ($registered) {  # outside the try: a failing start must not also add the Startup shortcut (two watches)
    Start-ScheduledTask -TaskName $TaskName
    Set-Record 'watch' "scheduled-task:$TaskName"
    Ok 始めました "タスク スケジューラの「$TaskName」。サインインのたびに始まります。ログは $log"
  } else {
    Set-Record 'watch' $Startup
    Ok 始めました "タスク スケジューラに断られたので($refused)、スタートアップ フォルダーに置きました。ログは $log"
  }
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

if ($Uninstall) {  # what windows\uninstall.ps1 -Yes does: removes what this script recorded, and only that
  & (Join-Path $PSScriptRoot 'uninstall.ps1') -Yes
  exit $LASTEXITCODE
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
Stage-KiroCli
Stage-GhLogin
Stage-KiroLogin
Stage-TaskHub
Stage-Board
Stage-Config
Stage-Kiro
Stage-Watch
Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue

# 12. the diagnosis: the list only; the one next step is said below
& (Join-Path $PSScriptRoot 'doctor.ps1') -InInstall
$doctorOk = $LASTEXITCODE -eq 0
if ($changed) { Write-Host 'ここまで終わりました。' } else { Write-Host 'すべて済みです。変えたものはありません。' }
if ($Todo) {
  Write-Host "次にすること: $Todo"
} elseif (-not $doctorOk) {
  Write-Host '次にすること: 診断の × の行の → のとおりにしてください'
} elseif ($Restart) {
  Write-Host '次にすること: Kiro を再起動し(開いているチャットには、少なくともウィンドウの再読み込みが要ります)、新しいチャットで /task を試してください'
} else {
  Write-Host '次にすること: Kiro の新しいチャットで /task を試してください'
}
