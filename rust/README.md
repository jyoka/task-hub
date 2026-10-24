# task-rs (experiment)

A local-first Rust copy of three `task` commands, for comparing speed and memory with `bin/task`. It is not part
of task-hub and is not installed by `task update`.

| Command | What it does |
|---|---|
| `task-rs list` | The open cards from the local board, the same lines as `task list`. Never calls GitHub |
| `task-rs list --watch` | The same, redrawn every 60 seconds from the local board, like `task list --watch` |
| `task-rs fetch` | Copies the open cards from GitHub to the local board, once. Reads only |
| `task-rs list --fetch` | `fetch`, then `list`. If the fetch fails, it shows the local board |
| `task-rs events [--only "In review,Blocked"]` | The last 20 events, like `task events` |
| `task-rs tui` | A live terminal view: the board, the selected card's details, and the events. Enter, `d` and `l` read a task's Issue, diff or log full screen. `g` opens Lazygit in a task's worktree |

The local board is `~/.local/state/task-hub/board-cache.json`, the file `bin/task` also reads and writes. So:

- `task-rs list` shows it at any age, and prints its age on stderr.
- GitHub is read only when you ask: `task-rs fetch` or `list --fetch`, and in the TUI `f` or opening an Issue (for its
  comments). All of them only read. (`sync`, the 0.1 name, still works.)
- Nothing syncs to GitHub, and nothing needs to: the local board is only a copy. Change the board on GitHub or with
  `task new`, `task start` and `task done`.
- `task list` (when its copy is old) and `task` also refresh it, and a running `task watch` refreshes it every minute.
- `task-rs` never moves cards or changes anything on GitHub.

## The TUI

`task-rs tui` (ratatui) has two screens:

- **The board**, for choosing a task: the cards with what needs you first, the selected card's details, and the
  newest events.
- **The reader**, for reading one task: its Issue (the Goal and the comments), its diff, or its agent's log, over the
  whole terminal.
  Only a one-line header (the view, the task, where you are) and the keys at the bottom stay.

Both redraw when the local files change. The board is read only. `g` hands the terminal to Lazygit, which is not
read only (see below).

### Keys on the board

| Key | What it does |
|---|---|
| ↑ ↓ (or j k) | Move between cards |
| Enter | Read the Issue: its Goal from the local copy, then its comments from GitHub |
| d | Read the diff: all the task changed in its worktree since its base branch, committed or not (while the worktree exists) |
| l | Read the run's log |
| PgUp, PgDn (or Space) | Scroll the details |
| b | Open the PR in the browser (the Issue when there is no PR) |
| o | `task open <id>`: the worktree in your IDE (`[ide] open` in config.ini) |
| g | Lazygit in the task's worktree, in this terminal. It asks first; `g` or Enter opens it. Quit Lazygit to come back |
| f | Fetch from GitHub (reads only) |
| q | Quit |

In a terminal narrower than 110 columns, the details go under the board. In a short one, the events take fewer rows.

At the bottom of the board, a small pixel art and a line to cheer you on, a different one each day (it changes at
local midnight). It shows only in the rows the cards leave free, so it never takes a card's row.

### Keys in the reader

The reader stays on the task you opened it on. No key in it selects another card.

| Key | What it does |
|---|---|
| ↑ ↓ (or j k), mouse wheel | Scroll one row (the wheel: three) |
| PgUp, PgDn (or Space) | Scroll one screen |
| Home, End | The beginning, the end |
| ← → | Scroll the diff sideways. Its lines are not wrapped or cut: the header shows the column |
| Enter, d, l | Switch to the Issue, the diff, the log. Each keeps its place while the reader is open |
| n, p | On the Issue: the next, the previous heading: a comment's, or a section's in an open comment. A comment's rule or a section's heading goes to the top, and the heading gets the cursor |
| Enter, o | On the Issue, with the cursor on a comment's or a section's heading: open or close that comment or section. With no heading on screen, Enter does nothing and `o` is `task open` as on the board |
| a | On the Issue: open all the sections of the open comments, or close them all when all are open. The heading under the cursor stays where it is on screen |
| g | Lazygit in this task's worktree, as on the board. Quitting it brings back the same view at the same place |
| b, o, f | As on the board, for this task (`o` on a heading opens or closes it instead). On the Issue, `f` also reads its comments again |
| Esc | Back to the board, on the same card |
| q | Quit task-rs, as on the board |

The Issue and the log wrap long lines, and every row of a long line can be scrolled to. The header shows the rows on
screen and how many there are. The Issue is at most 100 columns wide, so that its lines stay easy to read in a wide
terminal. task-rs wraps them itself: Japanese text fills each row and wraps between any two of its characters, words
of letters and digits wrap at spaces (only a word wider than a row, a long path say, is cut), and no row starts with
`、`, `。` or a closing bracket. The rows after the first of a list item start under its text, not under its mark.

The Issue's Markdown is drawn for reading: headings (`#` to `####`, and a line that is all `**bold**`) in bold after
a colored `■` instead of their `#` (`▸` or `▾` for a comment's sections, below; a `#` heading is also underlined),
with a blank row above, lists with even indents (`•`, `1.`, `☐` and `☑` for `- [ ]` and `- [x]`), `**bold**` in
bold, code blocks in a frame (`┌─`, `│`, `└─`), and tables with their columns lined up. `` `code` `` (paths,
commands) is dimmed, not colored: quieter than the text around it, so that the headings are what stands out. A table
wider than the Issue has its widest columns cut (`…`); a table with too many columns wraps.

The reader turns on the terminal's mouse reports so that the wheel scrolls. To select text with the mouse there, hold
Option (Terminal, iTerm2) or Shift (most other terminals). The board leaves the mouse to the terminal.

### Live updates in the reader

The reader reads its task again when the local files change, as the board does. It calls GitHub only for the Issue's
comments (below). Your place stays where it is: a reload does not move it.

- **The log** opens at its end and follows new output while you are at the bottom (the header says `following`).
  Scroll up and it stops following (`paused, End follows`): new output is added below without moving what you read.
  Go back to the bottom (End, or scroll down) and it follows again. It shows the log's last 1 MB, and up to 4 MB
  while you read older output. If the log grows past that, or is cut or replaced, the reader goes to its end.
- **The diff** is made again from the worktree on each reload (at least every 15 seconds). Git reads a copy of the
  worktree's index, so task-rs does not write the index or take its lock while an agent works there.
- **The Issue** is its Goal from the local copy of the board (`f` fetches a newer one), then its comments: task-hub's
  reports and replans, and people's comments. See below.
- When the terminal changes size, the reader keeps the line that was at the top, or stays at the end.
- If the task leaves the board (Done), the reader says `no longer on the local board` and keeps its last copy. It
  never shows another task instead. Esc goes back to the board, on a card that is still there. A missing worktree or
  log is said in the reader.

### The Issue's comments

The comments are not on the local board: `board-cache.json` is shared with `bin/task`, which reads the board every
minute, and comments would make that read heavier. task-rs reads them itself, from GitHub, with one call that only
reads (the newest 100):

- when the reader shows the Issue for the first time (Enter on the board, or Enter in the reader), and
- when you press `f` on the Issue.

Reloads and other keys do not read them again. The read runs in the background: the reader stays usable, and the
comments appear when it is done.

They come under the Goal, oldest first. Each starts with a rule and a heading with its kind, who wrote it and when,
in local time: `Report · jyoka · 2026-10-10 14:30` for a report task-hub wrote (and its Blocked part),
`Replan · …` for the replanner's answer, and `Comment · alice · 2026-10-09 13:09` for a person's comment. A line under
`Comments (n)` says when they were read.

An open comment does not repeat its own heading: a `## Report` it starts with is left out under
`▾ Report · …`. Only the newest Report is open (`▾`). The other comments, older Reports included, are closed (`▸`): one line with
their heading and the start of their text. The cursor (the heading drawn reversed) is on the first heading on screen,
or on the comment `n` or `p` went to. Enter or `o` opens or closes it, and the comments you opened or closed stay so
while the reader is open, across reloads and `f`.

An open comment's sections (from a heading to the next heading of the same level or above) are closed too: it shows
its first section, the text before its first heading (a Report's summary) or, with none, its first heading's section
with the sections inside it, and then only the headings of the others, one under the other, with `▸`. `n` and `p`
stop at those headings as well, and Enter or `o` opens (`▾`) or closes one where it is. A closed section hides the
sections inside it. `a` opens all the sections of the open comments at once, and when all are open, closes them all.
Sections you opened or closed stay so, as comments do. An open comment's long lines wrap and scroll as the Goal does,
and the header counts their rows too.

task-rs keeps the comments it read in its own file, `~/.local/state/task-hub/task-rs/comments-<owner>_<repo>-<number>.json`.
When GitHub cannot be reached (offline, `gh` not logged in, an error), the reader shows that copy with the reason and
when it was read: `could not read the comments: <reason>; the copy read at 13:05`. With no copy, it shows the Goal
and `could not read the comments: <reason>`.

## Lazygit in a task's worktree (g)

`g` lends this terminal to [Lazygit](https://github.com/jesseduffield/lazygit) in the worktree that task-hub recorded
for the selected task (`runs/<id>.json`, read again when you press `g` and again when you confirm). It is for looking
at what an agent did: its commits, files and diffs. When you quit Lazygit, task-rs comes back, reloaded, on the same
card: the board, or the reader in the same view at the same place when you pressed `g` there. If the card is gone
(Done), the board selects another card, and the reader says the task is no longer on the board.

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

Started inside [herdr](https://herdr.dev) but not on a terminal (by an agent such as Claude Code or Kiro),
`task-rs tui` opens a herdr pane to the right of the one it was started from and runs there. This includes output on a
terminal with no keys to read: stdin is not a terminal and there is no `/dev/tty`. Typed in a pane, it runs in that
pane. `TASK_HERDR=0` turns the new pane off. With no terminal and no herdr, it stops with an error.

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
