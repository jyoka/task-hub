# task-hub

A file-based task board for Claude Code agents running in the cloud.

You register tasks when you choose to. Cloud agents pick up only the tasks you approved,
at most 3 at a time. When an agent finishes, it opens a PR, writes a report, and lists
exactly what you need to review.

```
you:    /task in a chat          ->  tasks/0012-fix-login.md   status: draft
you:    task ready 12            ->  status: ready, cloud run starts (if a slot is free)
cloud:  routine run              ->  status: in_progress, branch + PR in the target repo
cloud:  report written           ->  status: review  (Report + Please review filled in)
you:    review the PR            ->  task done 12
```

## Daily use

| You want to | Run |
|---|---|
| See what needs you | `task` |
| Turn the current chat into a task | `/task` in Claude Code (optionally `/task repo is jyoka/app`) |
| Create a task from the terminal | `task new --title "..." --repo owner/name --goal "..."` |
| Read a task and its report | `task show <id>` |
| Let an agent work on it | `task ready <id>` |
| Accept finished work | `task done <id>` (after reviewing the PR) |
| Re-run a blocked or stuck task | `task ready <id>` |
| List by status | `task list --status review` |

A normal chat never becomes a task. Only `/task` or `task new` creates one.

## Status lifecycle

| From -> To | Who | How |
|---|---|---|
| (new) -> draft | you | `/task` or `task new` |
| draft -> ready | you only | `task ready <id>` (also starts cloud runs) |
| ready -> in_progress | dispatcher / routine | `task dispatch`, `task claim` (never more than 3) |
| in_progress -> review | agent | `task review <id> --pr <url>` (refused until the report is written) |
| in_progress -> blocked | agent | `task block <id> --reason "..."` |
| blocked / stuck -> ready | you | `task ready <id>` |
| review -> done | you | `task done <id>` |

## Layout

```
bin/task              the CLI (Python 3, standard library only)
tasks/NNNN-slug.md    one file per task
skills/task/SKILL.md  the /task skill (linked into ~/.claude/skills/task)
routine/PROMPT.md     the prompt the cloud routine runs
tests/test_task.py    tests: python3 -m unittest -v
docs/                 design, task format, routine setup, operations
```

## Setup

1. Put the CLI and the skill on this Mac:
   ```
   ln -s "$HOME/AIprogramming PJ/task-hub/bin/task" ~/.local/bin/task
   ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.claude/skills/task
   ```
2. Cloud agents: follow [docs/routine-setup.md](docs/routine-setup.md).

Until the routine is set up, everything works locally, and `task ready` says the dispatch was skipped.

## Docs

- [docs/design.md](docs/design.md): why it is built this way, what else we looked at, known limits
- [docs/task-format.md](docs/task-format.md): the task file format and status meanings
- [docs/routine-setup.md](docs/routine-setup.md): GitHub + cloud routine setup, step by step
- [docs/operations.md](docs/operations.md): troubleshooting and recovery
