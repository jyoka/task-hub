# Operations and troubleshooting

Start with `task`. It checks running tasks and PRs, starts approved tasks when a slot is
free, and shows every open task and how many need you.

## Watching a run

- **herdr**: each run has a workspace in the sidebar named "task <id>: <title>". Open it to
  watch the agent's output live. When the run ends, the pane stays open with the final status
  line. `task done <id>` (or merging the PR) closes it.
- **Without herdr**: `task log <id>` shows the last 40 lines, and `task log <id> --full` shows everything.
- What the agent was told: `~/.local/share/task-hub/prompts/<id>.md`.

## Where things live

| What | Where |
|---|---|
| Task files | `<hub>/tasks/` (committed to the hub's git history on every change) |
| Config | `~/.config/task-hub/config.ini` |
| Repo clones | `~/.local/share/task-hub/repos/<owner>/<name>` |
| Worktrees | `~/.local/share/task-hub/worktrees/<id>` |
| Prompts | `~/.local/share/task-hub/prompts/<id>.md` |
| Logs | `~/.local/state/task-hub/logs/<id>.log` |

## A task is `blocked`

`task show <id>` shows `reason`, and the report says more. Common reasons:

| Reason | What to do |
|---|---|
| the agent's own line (from `## Blocked`) | give it what it asks for: edit the Goal in the task file, or fix the environment |
| `agent exited without a report (exit N)` | read `task log <id>`. Usually the agent crashed, is not logged in, or ran out of budget |
| `agent wrote a report but changed no files` | the agent thought there was nothing to do. Clarify the Goal |
| `run stopped unexpectedly` | the `task _run` process died (for example you closed its herdr pane, or the Mac restarted) |
| `could not start: ...` | cloning or worktree setup failed: check `gh auth status` and the `repo` name |
| `PR was closed without merging` | re-run it, or close the task with `task done <id>` |

Then `task start <id>`. The re-run continues on the same branch and PR, and the agent is told why
the last run stopped.

## `queue: N approved task(s) waiting, all 3 slots busy`

Normal. They start on the next `task` after a running task finishes.

## `github_errors[...]`

`gh` could not read a repo's PRs (not logged in, no access, repo renamed). Those tasks keep
their status. Run `gh auth status`.

## Stop a running task

Stop the agent in its herdr workspace (Ctrl-C). The runner still finishes: it pushes whatever
was changed and marks the task blocked. Or close the pane. The next `task` then marks it
`run stopped unexpectedly`.

## Cancel a task

`task done <id>`. This closes its herdr workspace and removes its worktree. The branch and any PR
stay on GitHub. Close the PR there if you want.

## Change the parallel limit

`MAX_PARALLEL` at the top of `bin/task`.

## Disk cleanup

Worktrees are removed when tasks are done. Clones in `~/.local/share/task-hub/repos/` are kept
to make the next run faster, and can be deleted at any time.
