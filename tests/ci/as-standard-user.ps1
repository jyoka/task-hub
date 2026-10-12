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
# Task Scheduler runs a task with a user's password as a batch logon: Windows Server (the runner) gives that right to
# no standard user, and the task then never starts. Give it to this user only
$sid = (Get-LocalUser -Name $name).SID.Value
$inf = Join-Path $env:TEMP 'task-hub-rights.inf'
secedit /export /cfg $inf /areas USER_RIGHTS /quiet | Out-Null
$rights = [IO.File]::ReadAllLines($inf)
$line = $rights | Where-Object { $_ -like 'SeBatchLogonRight*' }
if (-not $line) { $rights += "SeBatchLogonRight = *$sid" }
elseif ($line -notlike "*$sid*") { $rights = $rights | ForEach-Object { if ($_ -eq $line) { "$_,*$sid" } else { $_ } } }
[IO.File]::WriteAllLines($inf, $rights, [Text.Encoding]::Unicode)
secedit /configure /db (Join-Path $env:TEMP 'task-hub-rights.sdb') /cfg $inf /areas USER_RIGHTS /quiet | Out-Null
if ($LASTEXITCODE -ne 0) { throw "secedit could not give $name the right to log on as a batch job ($LASTEXITCODE)" }
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
# the command, in the checkout, with this job's PATH (Python from setup-python) and its output in the log. Session 0 has no
# desktop: what needs one (a hotkey: RegisterHotKey fails with 1459) is skipped, by TASK_TEST_NO_DESKTOP
[IO.File]::WriteAllText($script, "@echo off`r`nset PATH=$env:Path`r`nset TASK_TEST_NO_DESKTOP=1`r`ncd /d `"$repo`"`r`n$Command > `"$log`" 2>&1`r`nexit /b %ERRORLEVEL%`r`n",
  [Text.Encoding]::Default)

$taskName = 'task-hub ci as standard user'
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/d /c `"$script`""
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes $Minutes) -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Settings $settings -User "$env:COMPUTERNAME\$name" `
  -Password $password -RunLevel Limited | Out-Null
Start-ScheduledTask -TaskName $taskName
# until it has run and ended: Task Scheduler says 267011 (0x41303, "has not run yet") until it starts, then 267009
# (0x41301, "running")
$started = (Get-Date).AddMinutes(2)  # a task that has not started by then never will: say why now, not in 25 minutes
$end = (Get-Date).AddMinutes($Minutes + 1)
do {
  Start-Sleep -Seconds 5
  $code = (Get-ScheduledTaskInfo -TaskName $taskName).LastTaskResult
  $state = (Get-ScheduledTask -TaskName $taskName).State
  if ($code -eq 267011 -and $state -ne 'Running' -and (Get-Date) -gt $started) { break }
} while (($state -eq 'Running' -or $code -in 267009, 267011) -and (Get-Date) -lt $end)
if ($code -eq 267011) {
  Write-Host "== the task never started as $name (state $state). Task Scheduler's last events:"
  Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' -MaxEvents 10 -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host "   $($_.TimeCreated) $($_.Id) $($_.Message -replace '\s+', ' ')" }
  $code = 1
} elseif ($code -eq 267009) {
  Write-Host "== the task did not end in $Minutes minutes"
  $code = 1
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
if (Test-Path $log) { Get-Content $log -Encoding Default }
Write-Host "== ran as the standard user $name (not an administrator): exit $code"
exit $code
