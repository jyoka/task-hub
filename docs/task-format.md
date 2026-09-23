# Task file format

Each task is one markdown file: `tasks/NNNN-slug.md`, for example `tasks/0012-fix-login.md`.
Only the `task` CLI on your Mac writes these files. You can edit the Goal text by hand
before approving the task. Change status only through the CLI.

## Example

```markdown
---
id: 12
title: Fix login redirect
repo: jyoka/app
theme: auth
status: review
created: 2026-09-23
updated: 2026-09-23
branch: claude/task-12
started: 2026-09-23T02:14:05Z
session: https://claude.ai/code/session_01H...
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

## Frontmatter fields

| Field | Set by | Meaning |
|---|---|---|
| `id` | CLI | Number, unique in the hub, never reused |
| `title` | you | Short imperative summary |
| `repo` | you | GitHub `owner/name` where the work happens. It must be added to the routine |
| `theme` | you | Optional grouping, for example `auth` or `docs` |
| `status` | CLI | See below |
| `created` / `updated` | CLI | Dates |
| `branch` | CLI | `claude/task-<id>`, fixed at the first run and reused by re-runs |
| `started` | CLI | UTC time of the latest run start. PR activity older than this is ignored |
| `session` | CLI | URL of the latest cloud session, for watching or taking over the run |
| `pr` | CLI (from GitHub) | The agent's pull request |
| `reason` | CLI (from GitHub) | Why the task is blocked: the first line of the PR's `## Blocked` section |

## Sections

- **Goal**: written by you, or by `/task` from the chat. It is sent to the agent as its whole
  brief, because the agent never sees your chat. Headings inside it are kept at `###` level.
- **Report** and **Please review**: copied from the agent's PR description by `task` / `task sync`.

## What the agent's PR must look like

The routine prompt ([routine/PROMPT.md](../routine/PROMPT.md)) tells the agent to use these headings:

```
## Blocked            <- only when stuck; the PR is then a draft
<one line: what the agent needs from you>

## Report
<what changed, how it was verified, what was not done>

## Please review
<exact files, decisions, risks to check>
```

| PR state | Task becomes |
|---|---|
| no PR yet | stays `in_progress` |
| open, ready for review | `review` |
| open, draft | `blocked` (reason from `## Blocked`) |
| closed without merge | `blocked` ("PR was closed without merging") |
| merged | `done` |

## Statuses

| Status | Meaning | Needs you? |
|---|---|---|
| `draft` | Registered, not approved | Yes: approve with `task ready` or edit the Goal |
| `ready` | Approved, waiting for a free slot | No |
| `in_progress` | A cloud run is working on it (max 3 at once) | No |
| `review` | PR is open and ready | Yes: review, then merge |
| `blocked` | The agent needs something (see `reason` and the PR) | Yes: fix it, then `task ready` |
| `done` | PR merged, or closed by hand | No |
