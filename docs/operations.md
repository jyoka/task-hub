# Operations and troubleshooting

Start with `task`. It shows the counts, every open task, and how many need you.

## A task is stuck in `in_progress`

The cloud run died, or it is still running. Check the session on
<https://claude.ai/code/routines> (open the routine, then its runs).

- Still running: wait.
- Dead: `task ready <id>` re-queues it and starts a new run if a slot is free.
  The old branch may still exist in the project repo. The new run starts a fresh branch.

## `task ready` printed `dispatch: skipped`

The routine URL or token is not configured. See step 4 of [routine-setup.md](routine-setup.md).
The task is still `ready`, so the hourly run will pick it up if the routine exists.

## `error: could not start the routine for task N`

The API call failed. The task was put back to `ready`, so no slot is lost. Common causes:

- `401`: the token is wrong or was revoked. Generate a new one and update `~/.config/task-hub/routine.env`
- daily routine cap reached: check <https://claude.ai/code/routines>. Try again later,
  or turn on usage credits

Retry with `task dispatch`.

## `error: the task was changed by someone else at the same time`

Two writers changed the same task file at once (usually two runners claiming the same task).
The other change won. Your version was saved in `.rejected/<file>`, which is not committed.
Run `task show <id>` to see the current state. Copy anything you need from `.rejected/`,
then delete it.

## `error: could not sync the hub with its remote`

The hub clone has a git problem (unfinished rebase, local edits that conflict).
Run `git -C "$HOME/AIprogramming PJ/task-hub" status`, fix it, and retry.

## A task is `blocked`

`task show <id>` shows `reason` and the agent's notes in the Report. Give the agent what it needs
(edit the Goal, add the repo to the routine, add credentials to the routine's environment),
then `task ready <id>`.

## The routine opened a PR but the task never reached `review`

The run could not push to the hub's `main`. Check:

- `main` in `jyoka/task-hub` is not protected
- the Claude GitHub App has access to `jyoka/task-hub`
- `jyoka/task-hub` is in the routine's Repositories

Then write the report by hand if needed, and run `task review <id> --pr <url>` locally.

## The routine stopped running

If GitHub access expires, routines skip runs for up to 72 hours and then turn off.
Reconnect GitHub on claude.ai and switch the routine back on.

## Cancel a task

- Not started (`draft` / `ready`): delete the file and commit, or leave it as `draft`.
- Running: stop the session on claude.ai, then `task ready <id>` to re-queue it, or
  delete the file and commit to drop it.

## Change the parallel limit

`MAX_PARALLEL` at the top of `bin/task`. It is enforced wherever `task claim` or `task dispatch` runs.
