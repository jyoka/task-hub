# task-rs (experiment)

A local-first Rust copy of three `task` commands, for comparing speed and memory with `bin/task`. It is not part
of task-hub and is not installed by `task update`.

| Command | What it does |
|---|---|
| `task-rs list` | The open cards from the local board, the same lines as `task list`. Never calls GitHub |
| `task-rs list --watch` | The same, redrawn every 60 seconds from the local board, like `task list --watch` |
| `task-rs sync` | Reads the open cards from GitHub into the local board, once. The only GitHub call |
| `task-rs list --sync` | `sync`, then `list`. If the sync fails, it shows the local board |
| `task-rs events [--only "In review,Blocked"]` | The last 20 events, like `task events` |
| `task-rs tui` | A live terminal view: the board, the selected card's details or log, and the events |

The local board is `~/.local/state/task-hub/board-cache.json`, the file `bin/task` also reads and writes. So:

- `task-rs list` shows it at any age, and prints its age on stderr.
- GitHub is read only when you ask: `task-rs sync` or `list --sync`. Both only read.
- `task list` (when its copy is old) and `task` also refresh it, and a running `task watch` refreshes it every minute.
- `task-rs` never moves cards or changes anything on GitHub.

## The TUI

`task-rs tui` (ratatui) shows the board with what needs you first, the selected card's details and last digest,
and the newest events. It redraws when the local files change. It is read only.

| Key | What it does |
|---|---|
| ↑ ↓ (or j k), g G | Move, first, last |
| Enter (or p) | Open the PR in the browser (the Issue when there is no PR) |
| i | Open the Issue |
| l | Switch the right pane between details and the run's log |
| o | `task open <id>`: the worktree in your IDE |
| s | Sync from GitHub (reads only) |
| r | Read the local files again |
| q, Esc | Quit |

In a pane narrower than 110 columns, the details go under the board.

## Install the binary (no Rust needed)

The binary is on a GitHub pre-release with a `task-rs-v*` tag, for Apple Silicon Macs. `task update` never
installs it: it follows only `v1.2.3` tags, so other task-hub users do not get task-rs.

```sh
uname -m    # must print arm64
gh release download task-rs-v0.1.0 -R jyoka/task-hub -p 'task-rs-aarch64-apple-darwin' \
  -O ~/.local/bin/task-rs --clobber
chmod +x ~/.local/bin/task-rs
task-rs sync && task-rs tui
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
