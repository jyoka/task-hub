# task-rs (experiment)

A local-first Rust copy of three `task` commands, for comparing speed and memory with `bin/task`. It is not part
of task-hub and is not installed by `task update`.

| Command | What it does |
|---|---|
| `task-rs list` | The open cards from the local board, the same lines as `task list`. Never calls GitHub |
| `task-rs list --watch` | The same, redrawn every 60 seconds from the local board, like `task list --watch` |
| `task-rs fetch` | Copies the open cards from GitHub to the local board, once. Reads only. The only GitHub call |
| `task-rs list --fetch` | `fetch`, then `list`. If the fetch fails, it shows the local board |
| `task-rs events [--only "In review,Blocked"]` | The last 20 events, like `task events` |
| `task-rs tui` | A live terminal view: the board, the selected card's details or log, and the events. `g` opens Lazygit in a task's worktree |

The local board is `~/.local/state/task-hub/board-cache.json`, the file `bin/task` also reads and writes. So:

- `task-rs list` shows it at any age, and prints its age on stderr.
- GitHub is read only when you ask: `task-rs fetch` or `list --fetch`. Both only read. (`sync`, the 0.1 name, still works.)
- Nothing syncs to GitHub, and nothing needs to: the local board is only a copy. Change the board on GitHub or with
  `task new`, `task start` and `task done`.
- `task list` (when its copy is old) and `task` also refresh it, and a running `task watch` refreshes it every minute.
- `task-rs` never moves cards or changes anything on GitHub.

## The TUI

`task-rs tui` (ratatui) shows the board with what needs you first, the selected card's details, Issue, diff or log,
and the newest events. It redraws when the local files change. The board is read only. `g` hands the terminal to
Lazygit, which is not read only (see below).

| Key | What it does |
|---|---|
| ↑ ↓ | Move between cards |
| Enter | The Issue (its Goal) in the right pane, from the local copy |
| d | The diff: what the agent changed in its worktree since its base branch (while the worktree exists) |
| l | The run's log |
| PgUp, PgDn (or Space) | Scroll the right pane. Esc, or the same key again, goes back to the details |
| b | Open the PR in the browser (the Issue when there is no PR) |
| o | `task open <id>`: the worktree in your IDE (`[ide] open` in config.ini) |
| g | Lazygit in the task's worktree, in this terminal. It asks first; `g` or Enter opens it. Quit Lazygit to come back |
| f | Fetch from GitHub (reads only) |
| q | Quit |

In a pane narrower than 110 columns, the details go under the board.

## Lazygit in a task's worktree (g)

`g` lends this terminal to [Lazygit](https://github.com/jesseduffield/lazygit) in the worktree that task-hub recorded
for the selected task (`runs/<id>.json`, read again when you press `g` and again when you confirm). It is for looking
at what an agent did: its commits, files and diffs. When you quit Lazygit, the board comes back, reloaded, on the same
card. If the card is gone (Done), another card is selected.

Before Lazygit opens, a box shows the task, repository, branch and worktree, and asks you to confirm. Press `g` or
Enter to open Lazygit. Any other key cancels.

Lazygit is not read only. It can stage, commit, reset, check out, rebase and push, including to GitHub. task-rs
itself still changes nothing: opening and quitting Lazygit does not change the task's status, start or stop an
agent, fetch or push, write run files, or keep or delete the worktree.

**While an agent is running.** You can open Lazygit, and the box warns you that an agent is running. Only look.
Staging, committing, reset, checkout and rebase change the same worktree and index the agent is working in, and can
interfere with its run. The warning does not stop anything, and it cannot remove the chance that you and the
agent change Git at the same time.

**Committed changes.** Lazygit's Files panel shows uncommitted changes only. An agent that has committed can look
clean there. Use `d` in task-rs for everything the task changed since its base branch, committed or not. In
Lazygit, look at the Commits panel.

**When the worktree goes away.** `task watch` removes a task's worktree when the task is Done, even while Lazygit is
open in it. Quit Lazygit and look at the PR instead (`b`). task-rs never opens another checkout instead: when the
worktree is missing, is not a Git worktree, or is a main checkout or inside one, `g` only says so in the status line.

If Lazygit is not on your PATH or cannot start, the status line says so in yellow. If Lazygit exits with an error,
its message stays on the screen until you press Enter. The board takes the terminal back either way: raw mode, its
screen, and the terminal mode from before Lazygit.

### Install Lazygit (optional)

task-rs does not install Lazygit or change its configuration. To use `g`:

```sh
brew install lazygit
```

### Show diffs with delta in Lazygit (optional)

[delta](https://github.com/dandavison/delta) draws diffs with syntax highlighting. Lazygit runs it. It is not
another program for task-rs. If you want it, add this to Lazygit's own config file yourself: `config.yml` in the
folder `lazygit --print-config-dir` prints (on a Mac, usually `~/Library/Application Support/lazygit`).

```sh
brew install git-delta
```

```yaml
git:
  diffRenderers:
    - command: delta --{{colorScheme}} --paging=never
```

This is Lazygit 0.64 or newer (`lazygit --version`). Lazygit 0.56 to 0.63 use `git: pagers: [{pager: delta --dark
--paging=never}]`, and 0.55 and older use `git: paging: {colorArg: always, pager: delta --dark --paging=never}`. If your config already has `diffRenderers`, add the line to that list rather than
replacing it: `|` in Lazygit cycles through them. Settings you already have, such as `[core] pager` in your Git
config, are not changed. The example follows Lazygit's
[Custom_DiffRenderers.md](https://github.com/jesseduffield/lazygit/blob/master/docs/Custom_DiffRenderers.md).

## Install the binary (no Rust needed)

The binary is on a GitHub pre-release with a `task-rs-v*` tag, for Apple Silicon Macs. `task update` never
installs it: it follows only `v1.2.3` tags, so other task-hub users do not get task-rs.

```sh
uname -m    # must print arm64
gh release download task-rs-v0.2.0 -R jyoka/task-hub -p 'task-rs-aarch64-apple-darwin' \
  -O ~/.local/bin/task-rs --clobber
chmod +x ~/.local/bin/task-rs
task-rs fetch && task-rs tui
```

To update, run the same `gh release download` with the newer tag. If macOS refuses to open it, run
`xattr -d com.apple.quarantine ~/.local/bin/task-rs` once.

task-rs needs task-hub's config (`~/.config/task-hub/config.ini`) and `gh` logged in on that Mac.

## Build from source

```sh
brew install rust                  # once (or rustup)
cd rust && cargo build --release   # about 10 seconds
./target/release/task-rs list
```

## Compare

```sh
python3 rust/bench.py                      # 12, 100 and 1000 fake cards, 20 runs each
python3 rust/bench.py --cards 50 --runs 5
```

`bench.py` builds a throwaway HOME with fake cards. It checks that both versions print the same lines, then
measures time and peak memory. It never reads or writes your real board or state.

How task-rs fits with task-hub, the personal board and team boards: [docs/architecture/designs/local-board.md](../docs/architecture/designs/local-board.md).
