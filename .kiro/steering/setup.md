---
inclusion: auto
name: task-hub-setup
description: Setting up task-hub on this Mac (kiro/install.sh) or Windows PC (windows\install.ps1). Use only when the user asks in chat to set up task-hub (「セットアップして」), to go on with that setup (「続けて」「セットアップを続けて」), to keep task watch running (「常駐も入れて」), to diagnose it (「診断して」), or to uninstall it (「アンインストールして」).
---

# Setting up task-hub: run the installer, say what it says

This is for a person in a Kiro chat who opened this repository to set up task-hub (docs/kiro-quickstart.md on a Mac,
docs/windows-quickstart.md on Windows). It does not apply when you run a task-hub task (as its worker, reviewer, or
replanner) or do any other work in this repository: then ignore this file and never run the scripts below. (Kiro CLI
loads every steering file here, whatever its `inclusion`.)

## What to run

Run from the root of this repository, in the foreground, and wait until it ends. It can take several minutes
(downloads; on Windows, Kiro CLI is about 300 MB), and it never asks anything on the terminal. On Windows the
commands run in PowerShell; use them as written (the backslashes, and `-ExecutionPolicy Bypass`).

| The user says | macOS | Windows |
|---|---|---|
| 「セットアップして」, 「続けて」, 「もう一度」 (after the setup stopped) | `sh kiro/install.sh` | `powershell -ExecutionPolicy Bypass -File windows\install.ps1` |
| 「常駐も入れて」 (keep `task watch` running) | `sh kiro/install.sh --with-launchd` | `powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Watch` (only after the user says yes: it starts Ready cards from then on) |
| 「診断して」, 「どこまでできた?」 | `sh kiro/doctor.sh` (changes nothing) | `powershell -ExecutionPolicy Bypass -File windows\doctor.ps1` (changes nothing) |
| 「アンインストールして」 | `sh kiro/uninstall.sh` (only lists). Run `sh kiro/uninstall.sh --yes` only after the user says yes to that list | `powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1` (only lists). Run it with `-Yes` only after the user says yes to that list |

Every installer and diagnosis ends with one line `次にすること: …`. When the macOS installer says to run it with an
option or a variable (`--start-launchd`, `HTTPS_PROXY=http://ホスト:ポート`), do that only after the user says yes or
gives the value; on Windows a proxy goes in the same way, `$env:HTTPS_PROXY='http://ホスト:ポート'; ` before the command.

## What to say

- Reply in Japanese, in 2 or 3 short lines: what got done (or where it stopped), then the `次にすること` line as it is.
  Do not paste the whole output; keep a URL, a one-time code (like `ABCD-1234`), or a 情シス request text exactly.
- When it stopped for a login (GitHub or kiro-cli, in a window that it opened: Terminal on macOS, PowerShell on
  Windows), tell the user to finish it there and then say 「続けて」. On Windows the window may open behind Kiro: it is
  on the taskbar.
- When it ends with "Kiro を再起動", tell the user to restart Kiro (macOS: menu Kiro → Quit Kiro; Windows: menu File →
  Exit, or close the window) and open it again, then to try `/task` in a new chat.

## What not to do

- Do not do any stage yourself, skip one, or install anything another way. The installers use no admin rights on
  purpose (the PC is managed by IT). macOS: no `sudo`, no Homebrew, no pkg installer, no `curl … | sh`, no
  `xcode-select --install`, no `pip install`. Windows: no `winget`, no MSI or setup program (the installer only unpacks
  Kiro CLI's MSI itself), no `Start-Process -Verb RunAs`, no `irm … | iex`, no `pip install`.
- Do not work around a stop: no checksum or signature bypass, no `GH_TOKEN`, no editing what the installer manages
  (macOS: `~/.local`, `~/.kiro`, `~/.config/task-hub`, Kiro's settings.json, `~/Library/LaunchAgents`; Windows:
  `~\.local`, `~\.kiro`, `~\.config\task-hub`, Kiro's settings.json, the user PATH, Task Scheduler, the Startup
  folder). Run it again, or tell the user what it asks for.
- Do not change files in this repository for the setup.
- If a script stops with something you cannot pass on (an error it does not explain), show its last 2 lines and
  suggest 「診断して」; do not guess a fix.
