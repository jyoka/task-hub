# task-hub

A file-based task board that runs your coding agents for you, whichever agent you use:
Claude Code, Codex, Pi, Kiro, or anything else with a non-interactive mode.

You register tasks when you choose to. You approve them with `task start`. At most 3 run at
the same time, each in its own herdr workspace on its own branch. When an agent finishes,
task-hub pushes the branch and opens a PR with the agent's report and a list of exactly what
you need to review.

```
you:    /task in a chat          ->  tasks/0012-fix-login.md           draft
you:    task start               ->  pick the task, an agent starts    in_progress
        (herdr sidebar shows a new workspace "task 12: Fix login" with the agent working)
agent:  edits files, runs tests, writes its report
task:   commits, pushes task/12, opens the PR                          review
you:    review + merge the PR    ->  next `task` marks it              done
```

Nothing runs in the cloud and nothing depends on one vendor. The board is plain markdown on
your machine, the agents run on your machine, and GitHub only sees the branch and the PR.

## Daily use

| You want to | Run |
|---|---|
| See what needs you (also starts waiting tasks) | `task` |
| Turn the current chat into a task | `/task` in your agent (optionally `/task repo is jyoka/app, use codex`) |
| Create a task from the terminal | `task new --title "..." --repo owner/name --goal "..." [--agent codex]` |
| Approve a task so an agent works on it | `task start` (pick from a list) or `task start 12` |
| Use a different agent for this task | `task start --agent kiro` |
| Watch a run | its workspace in the herdr sidebar, or `task log 12` |
| Read the report and what to review | `task show 12` |
| Accept finished work | merge the PR; the next `task` marks it done |
| Re-run a blocked task | `task start` (continues on the same branch and PR) |
| Close or cancel a task | `task done 12` |

A normal chat never becomes a task. Only `/task` or `task new` creates one, and only
`task start` lets an agent work on it.

## Status lifecycle

| Status | Meaning | Needs you? |
|---|---|---|
| `draft` | registered, not approved | yes: `task start` when you want it done |
| `ready` | approved, waiting because 3 are already running | no: starts on a later `task` |
| `in_progress` | an agent is working on it | no |
| `review` | PR open and ready | yes: review, then merge |
| `blocked` | the agent needs something (reason shown), or the run failed | yes: fix it, then `task start` |
| `done` | PR merged, or closed by hand | no |

## Layout

```
bin/task              the CLI (Python 3 standard library; uses git, gh, and herdr if running)
worker/PROMPT.md      the instructions every agent gets at the start of a run
skills/task/SKILL.md  the /task skill (linked into Claude, Codex/Pi, and Kiro skill folders)
tests/test_task.py    tests: python3 -m unittest -v
docs/                 setup, agents, design, task format, operations, lessons
```

Your tasks are not in this repo. They live in `~/.local/share/task-hub/board/tasks/`, a private
folder with its own local git history that is never pushed, so this repo can be shared safely.

## Docs

- [docs/setup.md](docs/setup.md): install on a Mac (including a work Mac that only has Kiro)
- [docs/agents.md](docs/agents.md): how each agent is run, safety, adding another agent
- [docs/task-format.md](docs/task-format.md): the task file, the agent's report file, the PR
- [docs/operations.md](docs/operations.md): watching runs, troubleshooting, cleanup
- [docs/design.md](docs/design.md): why it is built this way, what else we looked at
- [docs/lessons.md](docs/lessons.md): what building and testing it taught us, and what is still unproven
