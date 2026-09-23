# Task file, report file, and PR format

## Task file

Each task is one markdown file in the board folder, `~/.local/share/task-hub/board/tasks/`
(or `$TASK_HUB_DIR/tasks/`), for example `tasks/0012-fix-login.md`. The board is private: it has
its own local git history, separate from the task-hub repo, and is never pushed.
Only the `task` CLI writes these files. You can edit the Goal text by hand, for example
before starting a task or before re-running a blocked one. Change status only through the CLI.

```markdown
---
id: 12
title: Fix login redirect
repo: jyoka/app
theme: auth
agent: codex
status: review
created: 2026-09-23
updated: 2026-09-23
branch: task/12
started: 2026-09-23T02:14:05Z
pid:
workspace: w6
worktree: /Users/jyoka/.local/share/task-hub/worktrees/12
log: /Users/jyoka/.local/state/task-hub/logs/12.log
pr: https://github.com/jyoka/app/pull/41
reason:
---
## Goal

After login, users land on / instead of the page they came from.
Keep the `next` query parameter through the OAuth round trip.

- [ ] Redirects to `next` after login
- [ ] Rejects external `next` URLs
- [ ] Tests cover both

## Report

Stored `next` in the session before the OAuth redirect and read it back in the callback.
Added 3 tests; `pytest` passes.

## Please review

- `src/auth/callback.py:40`: the allowlist check for `next` (only same-origin paths)
- I kept the old `/home` fallback when `next` is missing. Confirm that is wanted.
```

| Field | Set by | Meaning |
|---|---|---|
| `id` | CLI | Number, unique on this board, never reused |
| `title` | you | Short imperative summary. Also the PR title |
| `repo` | you | GitHub `owner/name` where the work happens |
| `theme` | you | Optional grouping |
| `agent` | you | Agent for this task. Empty = the machine's default ([agents.md](agents.md)) |
| `status` | CLI | See the README |
| `created` / `updated` | CLI | Dates |
| `branch` | CLI | `task/<id>`, reused by re-runs |
| `started` | CLI | UTC time the latest run was launched |
| `pid` | CLI | Process of the running `task _run`, used to notice runs that died |
| `workspace` | CLI | The herdr workspace task-hub created for the run (empty without herdr) |
| `worktree` | CLI | Where the agent works. Removed when the task is done |
| `log` | CLI | The run's full output (`task log <id>`) |
| `pr` | CLI | The PR task-hub opened |
| `reason` | CLI | Why the task is blocked |

Sections: **Goal** is written by you or by `/task` and is the agent's whole brief.
**Report** and **Please review** are copied from the agent's report file when a run ends.

## The agent's report file

At the end of every run, the agent writes `.task-report.md` in the worktree root
([worker/PROMPT.md](../worker/PROMPT.md) tells it how). task-hub reads it, deletes it,
and never commits it.

```markdown
## Blocked                 <- only when stuck; everything else still gets written

Need the Stripe test key.

## Report

What changed, how it was verified, what was not done.

## Please review

Exact files, decisions, and risks to check.
```

## What happens when the run ends

| Agent result | task-hub does | Task becomes |
|---|---|---|
| report, files changed | commit, push `task/<id>`, PR ready for review | `review` |
| report with `## Blocked` | commit and push what exists, **draft** PR with the reason | `blocked` |
| no report, files changed | push, draft PR ("agent exited without a report") | `blocked` |
| no report, nothing changed (crash) | nothing pushed, no PR | `blocked` |
| report, nothing changed | nothing pushed, no PR | `blocked` |

A re-run (`task start` on a blocked task) continues on the same branch and updates the same
PR. The agent is told the earlier report and why it was blocked. The exact prompt of the latest
run is kept at `~/.local/share/task-hub/prompts/<id>.md`.

## The PR

- branch `task/<id>`, base = the repo's default branch, title = task title
- description: `## Blocked` (if any), `## Report`, `## Please review`, and a footer with the task id and agent
- merged on GitHub: the next `task` marks the task `done` and removes its worktree and herdr workspace
- closed without merging while in review: the task becomes `blocked`
