<#
.SYNOPSIS
  Waits for Slack triage's key (Ctrl+Alt+S by default) and starts slack-triage when it is pressed
  (docs/slack-triage.md). Started at logon by windows/install.ps1 (stage 11); the Mac's slack-triage/hotkey/main.swift.

.DESCRIPTION
  The key is Windows' RegisterHotKey (no admin rights, no keyboard hook): a key another program has taken already
  fails, and that is said in the status file (~\.local\state\task-hub\slack-triage-hotkey.status): "ok <key>",
  "conflict <key>", "off" or "error <why>". It reads the key and whether it is on from
  ~\.config\task-hub\slack-triage.json, and looks at that file again every second: `slack-triage key` takes the new
  key, `slack-triage off` ends this program, with no restart by hand.
  -Python: the Python that runs slack-triage (pythonw.exe next to it is used when there is one: no console window).
  -Main: slack-triage/app/main.py.

.EXAMPLE
  powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File slack-triage-hotkey.ps1 -Python <python.exe> -Main <main.py>
#>
param(
  [Parameter(Mandatory = $true)][string]$Python,
  [Parameter(Mandatory = $true)][string]$Main
)
$ErrorActionPreference = 'Stop'
$state = Join-Path $env:USERPROFILE '.local\state\task-hub'
$status = Join-Path $state 'slack-triage-hotkey.status'
$config = Join-Path $env:USERPROFILE '.config\task-hub\slack-triage.json'
$utf8 = New-Object System.Text.UTF8Encoding $false
New-Item -ItemType Directory -Force $state | Out-Null

function Write-Status($text) { [IO.File]::WriteAllText($status, "$text`n", $utf8) }

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SlackTriageHotkey {
    [StructLayout(LayoutKind.Sequential)]
    struct MSG { public IntPtr hwnd; public uint message; public IntPtr wParam; public IntPtr lParam; public uint time; public int x; public int y; }
    [DllImport("user32.dll", SetLastError = true)] static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
    [DllImport("user32.dll")] static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")] static extern bool PeekMessage(out MSG msg, IntPtr hWnd, uint min, uint max, uint remove);
    [DllImport("user32.dll")] static extern uint MsgWaitForMultipleObjects(uint n, IntPtr[] handles, bool all, uint ms, uint mask);
    const int Id = 0x5354;  // "ST"
    const uint WM_HOTKEY = 0x0312;
    // 0 when registered, else the Windows error (1409: another program has the key)
    public static int Register(uint mods, uint vk) {
        return RegisterHotKey(IntPtr.Zero, Id, mods | 0x4000 /* MOD_NOREPEAT */, vk) ? 0 : Marshal.GetLastWin32Error();
    }
    public static void Unregister() { UnregisterHotKey(IntPtr.Zero, Id); }
    // true when the key was pressed within ms; the WM_HOTKEY comes to this thread's queue (no window)
    public static bool Wait(uint ms) {
        MsgWaitForMultipleObjects(0, new IntPtr[0], false, ms, 0x0080 /* QS_HOTKEY */);
        MSG msg;
        bool pressed = false;
        while (PeekMessage(out msg, IntPtr.Zero, WM_HOTKEY, WM_HOTKEY, 1 /* PM_REMOVE */)) {
            if ((int)msg.wParam == Id) pressed = true;
        }
        return pressed;
    }
}
'@

function Read-Key {  # @{ on; mods; vk; label } from the config, with the defaults of slack-triage (cli.py)
  $c = $null
  try { $c = [IO.File]::ReadAllText($config) | ConvertFrom-Json } catch { }
  $key = if ($c -and $c.hotkey_key -match '^[A-Za-z]$') { "$($c.hotkey_key)".ToUpper() } else { 'S' }
  $names = if ($c -and $c.hotkey_mods) { "$($c.hotkey_mods)".ToLower() -split ',' | ForEach-Object { $_.Trim() } } else { 'ctrl', 'opt' }
  $mods, $label = 0, @()
  foreach ($m in @(@(@('ctrl', 'control'), 2, 'Ctrl'), @(@('opt', 'option', 'alt'), 1, 'Alt'), @(@('shift'), 4, 'Shift'),
                   @(@('cmd', 'command', 'win'), 8, 'Win'))) {
    if ($names | Where-Object { $m[0] -contains $_ }) { $mods = $mods -bor $m[1]; $label += $m[2] }
  }
  if ($mods -eq 0) { $mods, $label = 3, @('Ctrl', 'Alt') }
  return @{ on = -not ($c -and $c.enabled -eq $false); mods = [uint32]$mods; vk = [uint32][char]$key
            label = (($label + $key) -join '+') }
}

# pythonw.exe: no console window flashes when the key is pressed
$run = Join-Path (Split-Path $Python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $run)) { $run = $Python }
$env:PYTHONUTF8 = '1'

$stamp = $null
$registered = $null
try {
  while ($true) {
    $now = if (Test-Path -LiteralPath $config) { (Get-Item -LiteralPath $config).LastWriteTimeUtc } else { [DateTime]::MinValue }
    if ($now -ne $stamp) {  # the first time, and after slack-triage key / off / setup
      $stamp = $now
      $k = Read-Key
      if (-not $k.on) { Write-Status 'off'; break }
      if ($k.label -ne $registered) {
        if ($registered) { [SlackTriageHotkey]::Unregister() }
        $err = [SlackTriageHotkey]::Register($k.mods, $k.vk)
        if ($err -eq 1409) { Write-Status "conflict $($k.label)"; $registered = $null; Start-Sleep -Seconds 1; continue }
        if ($err -ne 0) { Write-Status "error RegisterHotKey $err"; $registered = $null; Start-Sleep -Seconds 1; continue }
        $registered = $k.label
        Write-Status "ok $($k.label)"
      }
    }
    if ($registered -and [SlackTriageHotkey]::Wait(1000)) {
      try { Start-Process -FilePath $run -ArgumentList "`"$Main`"" -WindowStyle Hidden } catch { Write-Status "error $($_.Exception.Message)" }
    } elseif (-not $registered) {
      Start-Sleep -Seconds 1
    }
  }
} finally {
  [SlackTriageHotkey]::Unregister()
}
