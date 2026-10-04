<#
.SYNOPSIS
  Keep `task watch` running, with its output in ~\.local\state\task-hub\watch.log (docs/windows.md).
  Started at logon by install.ps1 -Watch. When the watch ends (a crash, a bad config), it starts again a minute later.
#>
param([Parameter(Mandatory = $true)][string]$Python)
$task = Join-Path $PSScriptRoot '..\bin\task'
$state = Join-Path $env:USERPROFILE '.local\state\task-hub'
$log = Join-Path $state 'watch.log'
New-Item -ItemType Directory -Force $state | Out-Null
$env:PYTHONUTF8 = '1'
# task prints UTF-8: read it as UTF-8, and write the log as UTF-8 without a BOM
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$utf8 = New-Object System.Text.UTF8Encoding $false
while ($true) {
  [IO.File]::AppendAllText($log, "== task-watch.ps1: starting task watch $(Get-Date -Format s)`r`n", $utf8)
  & $Python $task watch 2>&1 | ForEach-Object { [IO.File]::AppendAllText($log, "$_`r`n", $utf8) }
  [IO.File]::AppendAllText($log, "== task-watch.ps1: task watch exited $LASTEXITCODE, again in 60s`r`n", $utf8)
  Start-Sleep -Seconds 60
}
