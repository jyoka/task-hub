# Issue tracker: task-hub board

Instructions for agents and skills that create issues for work the user wants done on their task-hub board
(for example `to-prd` and `to-issues` from the Matt Pocock skills). The board's issues repository is
`[board] issues` in `~/.config/task-hub/config.ini` (for example `jyoka/tasks`); the code lives in other
repositories. If `task` is not on PATH, use `~/.local/lib/task-hub/bin/task`.

Every task goes through `task new`, never `gh issue create` plus `gh project item-add`: `task new` puts the card
on the board, sets its Target repo, links what it waits for, and notes the herdr workspace for its tab.

## When a skill says "publish to the issue tracker"

- **A PRD or other parent issue** (not work for an agent): `gh issue create -R <issues repo> --title "..." --body-file <file>`.
  Do not add it to the Project and do not use `task new`: it is not a task, and no agent should run it.
- **A slice of work** (one issue per slice): write its body to a file, then

  ```
  task new --title "<title>" --repo <owner/name of the code> [--research] [--blocked-by <id>,<id>] --goal-file <file>
  ```

  - `--repo` is the repository the code change goes to, not the issues repository.
  - Publish blockers first, and pass the ids of the slices this one needs as `--blocked-by`. task-hub starts
    a slice only after those are done (merged, or closed with `task done`); a dependency written only in the
    body is not enough to start it.
  - Keep the skill's body template (Parent, What to build, Acceptance criteria). Put the "Blocked by" list
    under a `### Ready conditions` heading instead, with one line on what the slice uses from each, and add
    anything else that must hold before it starts (a decision made, a key in `.env`). The agent checks these first.
  - `--research` when what the slice delivers is findings or a decision rather than a code change.
  - Triage labels do not apply: a new task lands in Backlog, which means "waiting for the user's approval".
    For a slice that needs a human (HITL), say so in the title and in Ready conditions.
  - Do not run `task start`. Starting is the user's decision (or `/chief`'s, after the user says yes).

## When a skill says "fetch the relevant ticket"

`task show <id> --full` (a task), or `gh issue view <number> -R <issues repo> --comments` (a PRD).

## Other operations

- **List**: `task list`
- **Comment**: `gh issue comment <number> -R <issues repo> --body-file <file>`
- **Close**: `task done <id>` for a task; `gh issue close <number> -R <issues repo>` for a PRD
