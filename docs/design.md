# Design

## Problem

Agent coding sessions are chat-shaped. The goal is to make them task-shaped, like Jira:

1. Register a task when you decide to (a plain question to the AI must not create one).
2. See all tasks with their status.
3. A free agent picks up the next approved task by itself.
4. When done, the agent reports the result and says exactly which parts need your review.

Constraints chosen by the user:

- Tasks are local files in a git repo (this one).
- Agents run in the cloud, so work continues with the laptop closed.
- Agents only take tasks the user marked `ready`. Agents never create or split tasks.
- Tasks can target several repositories.
- At most 3 tasks run in parallel, enforced by code, so the user can keep track.

## What we looked at (2026-09) and why not

| Option | What it is | Why not on its own |
|---|---|---|
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Kanban board, a worktree per card, review column | You assign cards by hand. The company shut down in April 2026 (now community maintained, local only) |
| [Beads](https://github.com/steveyegge/beads) | Git-backed issue tracker for agents, `bd ready` | Task store only: no cloud runner, no parallel limit, Dolt database instead of plain files |
| Backlog.md, Task Master | Markdown task files / PRD-to-task breakdown | Planning only, nothing runs the tasks |
| [OpenAI Symphony](https://openai.com/index/open-source-codex-orchestration-symphony/) | Polls Linear, runs a Codex agent per issue | Built for Codex + Linear, not local files + Claude Code |
| [Claude Code Projects](https://code.claude.com/docs/en/claude-projects) | One conversation starts parallel cloud threads, Overview pane | Task state lives on claude.ai, not in files. Starts work right away instead of waiting for `ready`. A thread limit is only an instruction, not enforced |
| GitHub Actions + claude-code-action | Claude Code on a cron in CI | Works, but routines do the same with no CI setup. Kept as the fallback |

## Decisions

1. **Tasks are markdown files in git.** They are readable, editable, and diffable, and there is
   no database. GitHub is the sync point, because cloud agents can only read what is pushed.
2. **Claude Code routines are the runner.** A routine is a saved cloud Claude Code job.
   Verified in the [routines docs](https://code.claude.com/docs/en/routines):
   - one routine can have several repositories (cloned at the start of every run)
   - it pushes to `claude/*` branches and opens PRs as you
   - an API trigger (`POST .../fire`) starts a run immediately, and each run is its own session
   - schedules can be no more frequent than every hour
   - there is a daily cap on runs per account
3. **Dispatch, then fire.** `task ready` claims the task locally (status `in_progress`),
   pushes, and only then calls the routine API with `task <id>`. The limit of 3 is checked
   before any run starts, so it is enforced by code, not by asking the agent nicely.
4. **Hourly backup run.** When a slot frees up, nothing fires by itself. The hourly
   scheduled run calls `task claim` and takes the next ready task. So a waiting task starts
   within about an hour of a slot freeing up. Run `task dispatch` to start it right away.
5. **Git is the lock.** Every write does `pull --rebase`, then commit, then push.
   - Same task claimed twice: each claim writes a unique `claim` id, so the two changes
     conflict and only one push wins. The loser is reset and stops.
   - Different tasks claimed at the same moment (no conflict): after pushing, the claimer
     re-counts, and if there are more than 3 `in_progress` it gives its claim back. In the
     rare case both give back, the task waits for the next dispatch or hourly run
     (safe, only slower).
   - A rejected write never loses text: the file is saved to `.rejected/` first.
6. **The agent must say what to review.** `task review` refuses until the Report and Please
   review sections are filled in. The routine prompt asks for specific files, decisions,
   and risks.
7. **Registering is explicit.** The `/task` skill has `disable-model-invocation: true`,
   so Claude cannot start it by itself during a normal chat.
8. **Fire payload is untrusted.** Routines wrap API `text` as untrusted data. The prompt
   accepts only the exact form `task <number>` and checks that the task is `in_progress`.

## CLI shape

`bin/task` follows the AXI conventions for agent-facing CLIs: compact TOON output,
a home view (`task` with no arguments) that shows live state, explicit empty states,
errors on stdout with a `help:` line, unknown flags rejected, and repeated
state changes treated as no-ops. It uses only the Python 3 standard library, so it runs
unchanged on the Mac and in the cloud.

## Known limits

- **Repos are fixed in the routine.** A task for a repo not added to the routine gets
  blocked with a clear reason. Add the repo in the routine settings, then `task ready <id>`.
- **Daily run cap.** Each task costs one run, and the hourly backup costs up to 24 a day.
  If the cap is tight, schedule the backup every few hours.
- **Pushing to the hub's `main` from the cloud** is allowed by the docs when the branch is not
  protected and the commits are yours. This is the main assumption the first end-to-end run must confirm.
- **A run that dies stays `in_progress`.** You see it with `task`, and re-queue it with `task ready <id>`.
