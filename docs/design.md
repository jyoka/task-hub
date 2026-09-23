# Design

## Problem

Agent coding sessions are chat-shaped. The goal is to make them task-shaped, like Jira:

1. Register a task when you decide to (a plain question to the AI must not create one).
2. See all tasks with their status.
3. A free agent picks up the next approved task by itself.
4. When done, the agent reports the result and says exactly which parts need your review.

Constraints chosen by the user:

- Tasks are local files.
- Agents run in the cloud, so work continues with the laptop closed.
- Agents only take tasks the user marked `ready`. Agents never create or split tasks.
- Tasks can target several repositories.
- At most 3 tasks run in parallel, enforced by code, so the user can keep track.
- Cloud agents must not push to a shared branch. Branch handling must stay simple.

## What we looked at (2026-09) and why not

| Option | What it is | Why not on its own |
|---|---|---|
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Kanban board, a worktree per card, review column | You assign cards by hand. The company shut down in April 2026 (now community maintained, local only) |
| [Beads](https://github.com/steveyegge/beads) | Git-backed issue tracker for agents, `bd ready` | Task store only: no cloud runner, no parallel limit, Dolt database instead of plain files |
| Backlog.md, Task Master | Markdown task files / PRD-to-task breakdown | Planning only, nothing runs the tasks |
| [OpenAI Symphony](https://openai.com/index/open-source-codex-orchestration-symphony/) | Polls Linear, runs a Codex agent per issue | Built for Codex + Linear, not local files + Claude Code |
| [Claude Code Projects](https://code.claude.com/docs/en/claude-projects) | One conversation starts parallel cloud threads, Overview pane | Task state lives on claude.ai, not in files. Starts work right away instead of waiting for `ready`. A thread limit is only an instruction, not enforced |
| GitHub Actions + claude-code-action | Claude Code on a cron in CI | Works, but routines do the same with no CI setup |

## Decisions

1. **Only the Mac writes the board.** Task files live only in this local repo, and only
   the `task` CLI changes them. Cloud agents never read or write the board. This removed
   all shared-branch writes, race handling, and locking from an earlier version (0.1),
   where agents claimed tasks and pushed status changes to the hub's `main`.
2. **One task = one branch = one PR.** The CLI names the branch `claude/task-<id>`
   (routines push to `claude/*` branches by default). A re-run of a blocked task continues
   on the same branch and PR, so there is never more than one branch per task.
3. **The brief travels in the trigger.** `task ready` calls the routine's API trigger with the
   task id, repo, branch, and Goal as the `text` payload. The routine prompt explicitly accepts
   this payload as its assignment (routines treat fire text as untrusted unless the prompt opts in).
   Only the token holder (your Mac) can send it.
4. **Results travel in the PR.** The agent writes `## Report` and `## Please review` in the PR
   description, and uses a draft PR with a `## Blocked` line when it needs you. `task` reads
   the PRs with `gh` and copies those sections into the task file.
5. **`task` is the scheduler.** Every `task` / `task sync` / `task ready` first reads PRs, then
   starts runs for ready tasks while fewer than 3 are `in_progress`. The limit is enforced
   in code before a run starts. There is no hourly backup run: when a slot frees up while you
   are away, the next waiting task starts the next time you run `task`. This is deliberate:
   new work starts when you are around to keep track of it.
6. **Stale PR activity is ignored.** Each run records its start time. PR changes older than that
   (the old draft PR of a re-queued task) do not move the task.
7. **Registering is explicit.** The `/task` skill has `disable-model-invocation: true`,
   so Claude cannot start it by itself during a normal chat.

Verified in the [routines docs](https://code.claude.com/docs/en/routines): one routine can have
several repositories (fixed in its settings, cloned every run); it pushes to `claude/*` branches and
opens PRs as you; the API trigger starts a run immediately and returns the session URL; there is a
daily cap on runs per account.

## CLI shape

`bin/task` follows the AXI conventions for agent-facing CLIs: compact TOON output,
a home view (`task` with no arguments) that shows live state, explicit empty states,
errors on stdout with a `help:` line, unknown flags rejected, and repeated
state changes treated as no-ops. It uses only the Python 3 standard library plus `gh`.

## Known limits

- **Repos are fixed in the routine.** A task for a repo not added to the routine produces no PR.
  The run's session shows why. Add the repo, then `task ready <id>`.
- **Waiting tasks start only when you run `task`.** See decision 5. A cron job on the Mac could
  run `task sync` if this ever matters.
- **A run that dies stays `in_progress`.** `task` shows it, the session link shows what happened,
  and `task ready <id>` re-runs it on the same branch.
- **Daily run cap.** Each start (including re-runs) costs one routine run.
- **Unverified until the first real run:** that the cloud session can open a PR and switch it
  between draft and ready. [routine-setup.md](routine-setup.md) step 5 checks this.
