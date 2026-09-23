# Setup

Each machine gets its own board. Work tasks stay on the work Mac and personal tasks stay on
the personal Mac. Setup is the same on both.

## Requirements

- macOS with Python 3.10+ (`python3 --version`) and git
- `gh`, logged in to GitHub: `gh auth status`. task-hub uses it to clone repos, open PRs,
  and see when a PR is merged
- At least one agent CLI, logged in: `claude`, `codex`, `pi`, or `kiro-cli`. See [agents.md](agents.md)
- Optional: herdr, running. Each run then gets its own workspace in the herdr sidebar.
  Without herdr, runs happen in the background and you follow them with `task log <id>`
- Optional: `fzf`, for the arrow-key pick-list in `task start` (otherwise a numbered menu)

## Install

```
git clone https://github.com/jyoka/task-hub.git "$HOME/AIprogramming PJ/task-hub"
ln -s "$HOME/AIprogramming PJ/task-hub/bin/task" ~/.local/bin/task       # ~/.local/bin must be on PATH
task --version
```

The board (your tasks) is created on first use at `~/.local/share/task-hub/board`, outside this
repo, so every machine has its own private board. To keep it somewhere else, set `TASK_HUB_DIR`.

## Install the /task skill

The same skill folder works for every agent. Link it where each agent looks for skills:

```
ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.claude/skills/task    # Claude Code
ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.agents/skills/task    # Codex, Pi
ln -s ../../.agents/skills/task ~/.kiro/skills/task                          # Kiro
```

## Choose this machine's default agent

Create `~/.config/task-hub/config.ini` (optional; without it the default agent is `claude`):

```ini
[runner]
agent = kiro
```

For example, on the work Mac, which only has Kiro:

```
mkdir -p ~/.config/task-hub
printf '[runner]\nagent = kiro\n' > ~/.config/task-hub/config.ini
kiro-cli whoami          # must be logged in; runs cannot log in by themselves
```

[agents.md](agents.md) shows how to change an agent's command or add another agent.

## First run

Use a throwaway repo first:

```
gh repo create <you>/task-sandbox --private --add-readme
task new --title "Add hello.txt" --repo <you>/task-sandbox \
  --goal "Add hello.txt at the repo root containing 'hello'. Acceptance: the file exists."
task start
```

A herdr workspace named "task 1: Add hello.txt" appears, and the agent works in it. When it
ends, run `task`: the task should be in `review`, with a PR on branch `task/1` whose description
has Report and Please review. Merge it, run `task` again, and the task becomes `done`.
