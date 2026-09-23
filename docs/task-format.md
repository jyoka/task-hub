# Task file format

Each task is one markdown file: `tasks/NNNN-slug.md`, for example `tasks/0012-fix-login.md`.
The CLI writes these files. You can edit the Goal text by hand. Change status only through
the CLI, because the CLI also syncs with GitHub and enforces the rules.

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
pr: https://github.com/jyoka/app/pull/41
reason:
claim: 9f3a1c2e
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
| `pr` | agent | Pull request URL, set by `task review` |
| `reason` | agent | Why the task is blocked, set by `task block`. Cleared on `task ready` |
| `claim` | CLI | Random id of the current claim. Stops two runners from both owning the task |

## Sections

- **Goal**: written by you, or by `/task` from the chat. It is the agent's whole brief,
  because the agent never sees your chat.
- **Report**: written by the agent. What changed, how it was verified, what was not done.
- **Please review**: written by the agent. The exact files, decisions, and risks you must check.

`task review` refuses to move a task to review while either agent section still has placeholder text.

## Statuses

| Status | Meaning | Needs you? |
|---|---|---|
| `draft` | Registered, not approved | Yes: approve with `task ready` or edit the Goal |
| `ready` | Approved, waiting for a free slot | No |
| `in_progress` | A cloud agent owns it (max 3 at once) | No |
| `review` | Agent finished, PR open | Yes: review, then `task done` |
| `blocked` | Agent needs something from you (see `reason`) | Yes: fix it, then `task ready` |
| `done` | Accepted | No |
