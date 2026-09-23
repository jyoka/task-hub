# task-hub

A file-based task board for Claude Code agents running in the cloud.

You register tasks when you choose to. Cloud agents work only on the tasks you approved,
at most 3 at a time. Each agent works on its own branch in the project repo and opens a PR
whose description holds its report and the exact things you need to review.

**Only your Mac writes the task board.** Cloud agents never touch it. They receive the
task brief when their run starts, and they answer with a PR. `task` reads those PRs from
GitHub and updates the board.

```
you:    /task in a chat      ->  tasks/0012-fix-login.md            status: draft
you:    task ready 12        ->  cloud run starts with the brief    status: in_progress
cloud:  works on branch claude/task-12 in the project repo, opens a PR with Report + Please review
you:    task                 ->  PR found, report copied in         status: review
you:    review + merge PR    ->  task notices the merge             status: done
```

## Daily use

| You want to | Run |
|---|---|
| See what needs you (also syncs with GitHub and starts waiting tasks) | `task` |
| Turn the current chat into a task | `/task` in Claude Code (optionally `/task repo is jyoka/app`) |
| Create a task from the terminal | `task new --title "..." --repo owner/name --goal "..."` |
| Read a task, its report, and what to review | `task show <id>` |
| Let an agent work on it | `task ready <id>` |
| Accept finished work | merge the PR; the next `task` marks it done |
| Re-run a blocked or stuck task | `task ready <id>` (continues on the same branch and PR) |
| Close or cancel a task by hand | `task done <id>` |
| List by status, without GitHub calls | `task list --status review` |

A normal chat never becomes a task. Only `/task` or `task new` creates one.

## Status lifecycle

| From -> To | Triggered by |
|---|---|
| (new) -> draft | you: `/task` or `task new` |
| draft -> ready | you only: `task ready <id>` |
| ready -> in_progress | `task` / `task ready` starts a cloud run while fewer than 3 are running |
| in_progress -> review | the agent opened a PR that is ready for review |
| in_progress -> blocked | the agent opened a **draft** PR with a `## Blocked` reason, or the PR was closed |
| blocked / stuck -> in_progress | you: `task ready <id>` |
| review -> done | the PR was merged (or you: `task done <id>`) |

## Layout

```
bin/task              the CLI (Python 3, standard library only; uses `gh` to read PRs)
tasks/NNNN-slug.md    one file per task (local only, committed to this repo's git history)
skills/task/SKILL.md  the /task skill (linked into ~/.claude/skills/task)
routine/PROMPT.md     the instructions the cloud routine runs
tests/test_task.py    tests: python3 -m unittest -v
docs/                 design, task format, routine setup, operations
```

## Setup

1. Put the CLI and the skill on this Mac:
   ```
   ln -s "$HOME/AIprogramming PJ/task-hub/bin/task" ~/.local/bin/task
   ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.claude/skills/task
   ```
2. `gh` must be logged in (`gh auth status`): `task` uses it to read PRs.
3. Cloud agents: follow [docs/routine-setup.md](docs/routine-setup.md).

Until the routine is set up, everything works locally, and `task ready` says the routine is not configured.

## Docs

- [docs/design.md](docs/design.md): why it is built this way, what else we looked at, known limits
- [docs/task-format.md](docs/task-format.md): the task file format, the PR format, status meanings
- [docs/routine-setup.md](docs/routine-setup.md): cloud routine setup, step by step
- [docs/operations.md](docs/operations.md): troubleshooting and recovery
