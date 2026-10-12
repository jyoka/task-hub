<#
.SYNOPSIS
  GitHub Actions (windows.yml): runs a command as a standard user, made here, with no admin rights, and fails when it
  does (docs/architecture/designs/windows-easy-setup.md, "管理者でないユーザーの通し").

.DESCRIPTION
  The runner is an administrator, which hides anything that would need admin rights (a UAC prompt on a person's PC).
  This makes a local standard user (Users only) and runs the command as that user through Task Scheduler (a task
  with the user's password: its own profile, HKCU and %TEMP%, in session 0, so no desktop). Prints the command's
  output, and exits with its exit code.
  Only for a throwaway CI machine: it makes a user, and lets that user read the checkout.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tests\ci\as-standard-user.ps1 -Command 'python -m unittest tests.test_windows.SetupTest -v'
#>
param([Parameter(Mandatory = $true)][string]$Command, [int]$Minutes = 25)
$ErrorActionPreference = 'Stop'
$name = 'taskhubtester'
$password = 'Th-' + [guid]::NewGuid().ToString('N') + '-9z'  # never printed
$secure = ConvertTo-SecureString $password -AsPlainText -Force
if (-not (Get-LocalUser -Name $name -ErrorAction SilentlyContinue)) {
  New-LocalUser -Name $name -Password $secure -PasswordNeverExpires -AccountNeverExpires | Out-Null
} else {
  Set-LocalUser -Name $name -Password $secure
}
if (Get-LocalGroupMember -Group Administrators -Member $name -ErrorAction SilentlyContinue) {
  throw "$name is an administrator: the run would prove nothing"
}
# the checkout: readable by the user, and git trusts a repository another user owns
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
icacls $repo /grant "${name}:(OI)(CI)RX" /T /Q | Out-Null
git config --system --add safe.directory '*'

$work = Join-Path $env:PUBLIC 'task-hub-ci'
New-Item -ItemType Directory -Force $work | Out-Null
icacls $work /grant "${name}:(OI)(CI)M" /Q | Out-Null
$log = Join-Path $work 'output.log'
$script = Join-Path $work 'run.cmd'
Remove-Item $log -ErrorAction SilentlyContinue
# the command, in the checkout, with this job's PATH (Python from setup-python) and its output in the log
[IO.File]::WriteAllText($script, "@echo off`r`nset PATH=$env:Path`r`ncd /d `"$repo`"`r`n$Command > `"$log`" 2>&1`r`nexit /b %ERRORLEVEL%`r`n",
  [Text.Encoding]::Default)

$taskName = 'task-hub ci as standard user'
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/d /c `"$script`""
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes $Minutes) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Settings $settings -User "$env:COMPUTERNAME\$name" `
  -Password $password -RunLevel Limited | Out-Null
Start-ScheduledTask -TaskName $taskName
$end = (Get-Date).AddMinutes($Minutes + 1)
do {
  Start-Sleep -Seconds 5
  $info = Get-ScheduledTaskInfo -TaskName $taskName
  $state = (Get-ScheduledTask -TaskName $taskName).State
} while ($state -eq 'Running' -and (Get-Date) -lt $end)
$code = $info.LastTaskResult
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
if (Test-Path $log) { Get-Content $log -Encoding Default }
Write-Host "== ran as the standard user $name (not an administrator): exit $code"
exit $code
