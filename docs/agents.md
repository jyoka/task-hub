# Agents

task-hub runs any agent CLI that can take a prompt and work without anyone typing.
It starts the agent in the task's worktree with one argument, the prompt (the instructions
in [worker/PROMPT.md](../worker/PROMPT.md) followed by the task), and waits for it to exit.

The agent's only job is to edit files, run tests, and write `.task-report.md`. task-hub
does all git and GitHub work afterwards. This is what makes every agent behave the same way,
including agents whose sandbox cannot use the network or write outside the folder.

## Built-in agents

| Name | Command task-hub runs | Notes |
|---|---|---|
| `claude` | `claude -p --dangerously-skip-permissions {prompt}` | Claude Code print mode, no permission prompts |
| `codex` | `codex exec -s workspace-write {prompt}` | Codex runs in its workspace-write sandbox: it can edit the worktree and run commands, with no network by default |
| `pi` | `pi -p {prompt}` | Pi print mode |
| `kiro` | `kiro-cli chat --no-interactive --trust-all-tools {prompt}` | Kiro CLI, all tools trusted. Log in first (`kiro-cli whoami`) |

`{prompt}` is replaced by the prompt as a single argument, so no shell quoting is involved.

## Choosing the agent

1. `task start --agent <name>` for this task (it is saved on the task)
2. otherwise `task new --agent <name>`, if given when the task was registered
3. otherwise `[runner] agent` in `~/.config/task-hub/config.ini`
4. otherwise `claude`

## Changing or adding an agent

Put the command under `[agents]` in `~/.config/task-hub/config.ini`. It overrides the built-in
command with the same name, or adds a new one:

```ini
[agents]
; stricter Claude: allow only edits and test commands
claude = claude -p --allowedTools Edit,Write,Bash(npm test:*) {prompt}
; a new agent
aider = aider --yes-always --message {prompt}
```

Rules for a command to work:

- it must run to completion without asking questions (stdin is closed)
- it must work in the current directory, which is the task's worktree
- it must be able to write `.task-report.md` there. This is the only way task-hub learns the
  result: no report means the task is marked blocked

## Safety

Except for Codex, the built-in commands run **without approval prompts**. The agent can run
any command as you, in the worktree and beyond. What limits it:

- it works in a separate worktree (`~/.local/share/task-hub/worktrees/<id>`), never your own checkout
- only you approve tasks (`task start`), and at most 3 run at once
- it never pushes: task-hub pushes only the task's own branch, and changes reach your default
  branch only when you merge the PR

If that is too much trust for a machine (for example a work Mac), tighten the command in
the config: an allowlist of tools for Claude, `--trust-tools=...` for Kiro, or a stricter
sandbox for Codex.
