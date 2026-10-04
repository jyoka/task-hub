<#
.SYNOPSIS
  Install task-hub on Windows, and optionally keep `task watch` running (docs/windows.md).

.DESCRIPTION
  1. Checks git, gh and Python 3.10+ (installs nothing: on a company PC, ask IT or use winget).
  2. Clones task-hub to ~\.local\lib\task-hub, or pulls it when it is already there.
  3. Writes ~\.local\bin\task.cmd, which runs bin\task with that Python, and puts ~\.local\bin on the user PATH.
  With -Watch it also starts `task watch` at every logon (Task Scheduler; the Startup folder when that is refused)
  and starts it now. -Uninstall stops and removes the watch and task.cmd; the clone, config and data stay.
  Safe to run again.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch
#>
param(
  [switch]$Watch,
  [switch]$Uninstall,
  [string]$From = ""  # where to clone from; default: the origin of the clone this script is in
)
$ErrorActionPreference = 'Stop'
$TaskName = 'task-hub watch'
$Root = $env:USERPROFILE
$Lib = Join-Path $Root '.local\lib\task-hub'
$BinDir = Join-Path $Root '.local\bin'
$Shim = Join-Path $BinDir 'task.cmd'
$ShShim = Join-Path $BinDir 'task'  # for Git Bash, which Claude Code's Bash tool uses on Windows: it runs no .cmd
$Startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'task-hub watch.lnk'

function Say($text) { Write-Host "task-hub: $text" }
function Stop-Here($text, $help) { Write-Host "error: $text"; if ($help) { Write-Host "help: $help" }; exit 1 }

function Find-Python {
  # the py launcher first: `python` may be the Microsoft Store stub, which runs nothing and says so on stderr
  $ErrorActionPreference = 'Continue'  # Windows PowerShell 5.1 would stop at that stderr line
  $was = [Console]::OutputEncoding
  [Console]::OutputEncoding = [Text.Encoding]::UTF8  # the path as Python prints it with -X utf8, whatever the locale
  try {
    foreach ($c in @(@('py', '-3'), @('python'))) {
      if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
      $args_ = @($c | Select-Object -Skip 1) + @('-X', 'utf8', '-c',
        'import sys; print(sys.executable); print(sys.version_info >= (3, 10))')
      $lines = @(& $c[0] @args_ 2>$null)
      if ($LASTEXITCODE -eq 0 -and $lines.Count -ge 2 -and $lines[1] -eq 'True') { return $lines[0] }
    }
    return $null
  } finally {
    [Console]::OutputEncoding = $was
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

if ($Uninstall) {
  Stop-Watch
  foreach ($f in $Shim, $ShShim) { if (Test-Path $f) { Remove-Item $f; Say "removed $f" } }
  Say "left in place: $Lib, ~\.config\task-hub, ~\.local\state\task-hub, ~\.local\share\task-hub"
  exit 0
}

# 1. what task-hub needs
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Stop-Here 'git is not installed' 'winget install --id Git.Git -e   (or ask IT for Git for Windows)'
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Stop-Here 'gh (GitHub CLI) is not installed' 'winget install --id GitHub.cli -e   then: gh auth login; gh auth refresh -s project'
}
$Python = Find-Python
if (-not $Python) {
  Stop-Here 'Python 3.10 or later is not installed' 'winget install --id Python.Python.3.12 -e   (or ask IT)'
}
Say "python: $Python"

# 2. the clone task-hub runs from (never the one you develop in: switching branches there would change running code)
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

# 3. `task` on PATH
New-Item -ItemType Directory -Force $BinDir | Out-Null
$task = Join-Path $Lib 'bin\task'
# in the console's code page, which cmd.exe reads a .cmd in (a user folder may have Japanese in its name)
$oem = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
[IO.File]::WriteAllText($Shim, "@setlocal`r`n@set PYTHONUTF8=1`r`n@`"$Python`" `"$task`" %*`r`n", $oem)
$posix = { param($p) $p -replace '\\', '/' }
[IO.File]::WriteAllText($ShShim, "#!/bin/sh`nPYTHONUTF8=1 exec `"$(& $posix $Python)`" `"$(& $posix $task)`" `"`$@`"`n",
  (New-Object Text.UTF8Encoding $false))
# the user Path as stored, so entries such as %USERPROFILE%\x stay variables (REG_EXPAND_SZ)
$envKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
$userPath = $envKey.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
if (-not (($userPath -split ';') -contains $BinDir)) {
  $envKey.SetValue('Path', ((@($BinDir, $userPath) | Where-Object { $_ }) -join ';'), 'ExpandString')
  [Environment]::SetEnvironmentVariable('TASK_HUB_PATH_CHANGED', $null, 'User')  # tells Explorer, for new terminals
  Say "added $BinDir to your PATH (new terminals see it)"
}
$envKey.Close()
$env:Path = "$BinDir;$env:Path"
& $Shim --version
if ($LASTEXITCODE -ne 0) { Stop-Here "$Shim does not run" "run it by hand to see why: & `"$Shim`" --version" }

if (-not $Watch) {
  Say 'done. Next: docs/windows.md (config, then `task list`). To start Ready cards without a terminal: install.ps1 -Watch'
  exit 0
}

# 4. `task watch` at every logon, restarted when it ends
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
