# Design

## Problem

Agent coding sessions are chat-shaped. The goal is to make them task-shaped, like Jira:

1. Register a task when you decide to (a plain question to an agent must not create one).
2. See all tasks with their status.
3. A free agent picks up the next approved task by itself.
4. When done, the agent reports the result and says exactly which parts need your review.

Constraints from the user:

- Tasks are local files.
- Agents only take tasks the user approved. Agents never create or split tasks.
- Tasks can target several repositories.
- At most 3 tasks run in parallel, enforced by code.
- **Not tied to one vendor**: the user works with Claude Code, Codex, and Pi, and the work Mac
  only allows Kiro. The same tool must work on both machines.
- Simple branch handling. No agent pushes to a shared branch.
- The user works in herdr, so runs should show up there.
- Separate boards per machine. Stopping when the machine sleeps is acceptable.

## What we looked at (2026-09) and why not

| Option | What it is | Why not on its own |
|---|---|---|
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Kanban board, a worktree per card, review column | You assign cards by hand. The company shut down in April 2026 (now community maintained) |
| [Beads](https://github.com/steveyegge/beads) | Git-backed issue tracker for agents, `bd ready` | Task store only: no runner, no parallel limit |
| Backlog.md, Task Master | Markdown task files / PRD-to-task breakdown | Planning only, nothing runs the tasks |
| [OpenAI Symphony](https://openai.com/index/open-source-codex-orchestration-symphony/) | Polls Linear, runs a Codex agent per issue | Codex + Linear only |
| [Claude Code Projects](https://code.claude.com/docs/en/claude-projects) / [routines](https://code.claude.com/docs/en/routines) | Cloud sessions on claude.ai | Claude only, state on claude.ai. task-hub 0.1 and 0.2 used routines. Dropped in 0.3 for vendor neutrality |
| GitHub Actions + an agent CLI | Agents in CI | Needs API keys as repo secrets, and may not be allowed at work |

## Decisions

1. **The board is local markdown, and only `task` writes it.** No agent reads or writes the board.
   The board lives in a private folder (`~/.local/share/task-hub/board`) with its own local git
   history, never pushed, so the tool repo can be public. (0.1 let agents write the board
   through a shared branch, which needed locking and race handling. That was removed in 0.2.)
2. **Agents run locally, started by `task`.** `task start` approves a task. `task` and `task start`
   launch approved tasks while fewer than 3 are running. A queued task starts the
   next time you run `task`, so new work starts when you are around to keep track of it.
3. **The agent only edits files. task-hub does all git and GitHub work.** Agents differ in
   sandboxing (Codex's sandbox cannot use the network or write outside the folder, so it could
   not even commit in a worktree). So the agent's contract is the same for every agent: edit
   files, run tests, write `.task-report.md`. task-hub then commits, pushes, and opens or updates
   the PR. The PR format is therefore guaranteed by code, not by prompt.
4. **An agent is just a command template.** `{prompt}` is passed as one argument. Built-ins cover
   claude, codex, pi, and kiro, and the config can override them or add more. Nothing
   vendor-specific lives in the code path.
5. **One task = one branch (`task/<id>`) = one worktree = one PR.** A re-run of a blocked task
   continues on the same branch and updates the same PR. It gets the earlier report and the reason
   in its prompt.
6. **herdr is the viewer, not a dependency.** When herdr is running, a run gets its own workspace
   (created with `herdr workspace create` on a worktree task-hub made itself. `herdr worktree create`
   was not used because it also opens a second workspace for the parent repo). Without herdr, the
   run is a background process with a log. task-hub only closes workspaces it created.
7. **Dead runs are detected.** `task _run` records its pid. If that process is gone while the
   task is still `in_progress`, the next `task` marks it blocked with a pointer to the log.
8. **Registering is explicit.** The `/task` skill tells every agent to run only on an explicit
   request. Claude Code additionally enforces it with `disable-model-invocation: true`.

## CLI shape

`bin/task` follows the AXI conventions for agent-facing CLIs: compact TOON output, a home view
(`task` with no arguments) with live state, explicit empty states, errors on stdout with a
`help:` line, unknown flags rejected, repeated state changes treated as no-ops, and no prompts
when stdin is not a terminal (`task start` without an id then lists candidates and asks for an id).
It uses only the Python 3 standard library, plus git, gh, and optionally herdr and fzf.

## Known limits

- Runs pause when the machine sleeps, and a queued task starts only on the next `task`.
- The built-in agent commands (except Codex) skip approval prompts. See [agents.md](agents.md#safety).
- Test commands that need the network can fail under Codex's default sandbox. Adjust its command.
- One board per machine. Moving a task between machines means copying its file by hand.
