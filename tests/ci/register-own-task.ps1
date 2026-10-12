<#
.SYNOPSIS
  GitHub Actions (windows.yml), as the standard user of as-standard-user.ps1: registers a task at this user's logon
  the way windows/install.ps1 does for task watch and Slack triage (Interactive, Limited), then removes it. A
  standard user may do that for themselves; this proves it on the runner, where the job itself is an administrator.
#>
$ErrorActionPreference = 'Stop'
$name = 'task-hub ci own logon task'
$me = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -Command exit'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal | Out-Null
$t = Get-ScheduledTask -TaskName $name
Unregister-ScheduledTask -TaskName $name -Confirm:$false
Write-Host "registered and removed '$name' for $me (state $($t.State))"
