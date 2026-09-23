# Operations and troubleshooting

Start with `task`. It syncs with GitHub, starts waiting tasks if slots are free, and shows
every open task and how many need you.

## A task is stuck in `in_progress`

No PR has appeared yet. Open the `session` link from `task show <id>`.

- Still running: wait.
- Finished or failed without a PR (for example the repo is not added to the routine):
  fix the cause, then `task ready <id>`. The re-run uses the same branch.

## `dispatch: skipped, routine not configured`

The routine URL or token is missing. See step 3 of [routine-setup.md](routine-setup.md).
The task stays `ready` and starts on the next `task` once configured.

## `error: could not start the routine for task N`

The API call failed. The task stays `ready`, so no slot is lost. Common causes:

- `401`: the token is wrong or was revoked. Generate a new one and update `~/.config/task-hub/routine.env`
- daily routine cap reached: check <https://claude.ai/code/routines>. Try again later,
  or turn on usage credits

Retry with `task sync`.

## `github_errors[...]` in the output

`gh` could not read a repo's PRs (not logged in, no access, repo renamed). Those tasks keep
their status. Run `gh auth status`, and check that the task's `repo` is correct.

## A task is `blocked`

`task show <id>` shows `reason`, and the PR (a draft) has the details. Give the agent what
it needs: edit the Goal in the task file, add the repo to the routine, or add credentials to
the routine's environment. Then `task ready <id>`. The re-run continues on the same branch and PR.

If the PR was closed without merging, the task is blocked with that reason. Re-run it
with `task ready <id>`, or close it with `task done <id>`.

## Cancel a task

- Not started (`draft` / `ready`): `task done <id>`.
- Running: stop the session on claude.ai, close the PR if one exists, then `task done <id>`.

## Change the parallel limit

`MAX_PARALLEL` at the top of `bin/task`.

## Back up the board

The board is a local git repo and every change is committed. To keep an off-machine copy,
push it to a private repo yourself. Cloud agents never need it.
