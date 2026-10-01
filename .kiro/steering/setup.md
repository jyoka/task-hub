---
inclusion: auto
name: task-hub-setup
description: Setting up task-hub on this Mac with kiro/install.sh. Use only when the user asks in chat to set up task-hub (「セットアップして」), to go on with that setup (「続けて」「セットアップを続けて」), to keep task watch running (「常駐も入れて」), to diagnose it (「診断して」), or to uninstall it (「アンインストールして」).
---

# Setting up task-hub: run the installer, say what it says

This is for a person in a Kiro chat who opened this repository to set up task-hub (docs/kiro-quickstart.md).
It does not apply when you run a task-hub task (as its worker, reviewer, or replanner) or do any other work in this
repository: then ignore this file and never run the scripts below. (Kiro CLI loads every steering file here, whatever
its `inclusion`.)

## What to run

Run from the root of this repository, in the foreground, and wait until it ends. It can take several minutes
(downloads), and it never asks anything on the terminal.

| The user says | Run |
|---|---|
| 「セットアップして」, 「続けて」, 「もう一度」 (after the setup stopped) | `sh kiro/install.sh` |
| 「常駐も入れて」 (keep `task watch` running) | `sh kiro/install.sh --with-launchd` |
| 「診断して」, 「どこまでできた?」 | `sh kiro/doctor.sh` (changes nothing) |
| 「アンインストールして」 | `sh kiro/uninstall.sh` (only lists). Run `sh kiro/uninstall.sh --yes` only after the user says yes to that list |

Every script ends with one line `次にすること: …`. When the installer says to run it with an option or a variable
(`--start-launchd`, `HTTPS_PROXY=http://ホスト:ポート`), do that only after the user says yes or gives the value.

## What to say

- Reply in Japanese, in 2 or 3 short lines: what got done (or where it stopped), then the `次にすること` line as it is.
  Do not paste the whole output; keep a URL, a one-time code (like `ABCD-1234`), or a 情シス request text exactly.
- When it stopped for a login (GitHub in the browser, or kiro-cli in a Terminal window that it opened), tell the user
  to finish it there and then say 「続けて」.
- When it ends with "Kiro を再起動", tell the user to restart Kiro (menu Kiro → Quit Kiro, then open it again) and
  to try `/task` in a new chat.

## What not to do

- Do not do any stage yourself, skip one, or install anything another way. No `sudo`, no Homebrew, no pkg installer,
  no `curl … | sh`, no `xcode-select --install`, no `pip install`. The installer uses no admin rights on purpose
  (the Mac is managed by IT).
- Do not work around a stop: no checksum or signature bypass, no `GH_TOKEN`, no editing what the installer manages
  (`~/.local`, `~/.kiro`, `~/.config/task-hub`, Kiro's settings.json, `~/Library/LaunchAgents`). Run it again, or
  tell the user what it asks for.
- Do not change files in this repository for the setup.
- If a script stops with something you cannot pass on (an error it does not explain), show its last 2 lines and
  suggest `sh kiro/doctor.sh`; do not guess a fix.
