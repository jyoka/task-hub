# The Pi Durable runner (experiment)

A task-hub agent built on [Pi Durable](https://www.npmjs.com/package/@earendil-works/pi-durable): when its run is
cut short (a crash, kill -9, a restart), task-hub starts it again once, and it goes on from where it stopped instead of
from the prompt. It is "B" in the design note
[docs/architecture/designs/durable-runs.md](../docs/architecture/designs/durable-runs.md), to be compared with A (the
agent CLI's own saved conversation) and C (a new session) before one is kept.

**It is an experiment.** `@earendil-works/pi-durable` is experimental, and its README says "The API changes without
notice between releases". Every dependency is pinned to an exact version (`package.json` and `package-lock.json`):
upgrade on purpose, and run `npm test` when you do. `task update` does not install or build it.

## Install

Node 22.19 or later (Pi Durable's `engines`), in the task-hub clone that runs your tasks (`~/.local/lib/task-hub` by
default):

```sh
cd ~/.local/lib/task-hub/durable
npm ci --ignore-scripts   # the pinned versions, about 160 MB in node_modules
npm run build             # dist/*.js from src/*.ts
```

Then add it to `~/.config/task-hub/config.ini`, with the same command for the first start and for a resume. The runner
itself tells the two apart (by its SQLite file), so task-hub never treats it by name:

```ini
[agents]
durable = node /Users/me/.local/lib/task-hub/durable/dist/cli.js --session {session} {prompt}

[resume]
durable = node /Users/me/.local/lib/task-hub/durable/dist/cli.js --session {session} {prompt}
```

Give a card the agent with `task new ... --agent durable`, or make it the default with `[runner] agent = durable`.
See [docs/agents.md](../docs/agents.md) for `{session}` and `[resume]`.

## Sign-in

It uses pi's own login, read only: the `openai-codex` login (ChatGPT Plus or Pro) that the pi CLI keeps in its
`auth.json`. Log in with pi first (`pi`, then `/login`).

- It reads `$PI_CODING_AGENT_DIR/auth.json`, else `~/.pi/agent/auth.json`; `--auth <file>` names another one.
- It never writes, copies, or prints the login. pi-ai refreshes a token in its last 5 minutes by writing it back, which
  this runner refuses: it then ends with code 1 and says why (`cannot sign in to openai-codex ...`). Running `pi` once
  refreshes the login, and the next run picks it up.
- Before it starts, it checks the login (`getAuth`): none, or one that cannot be used, ends the run at once with code 1.
- With `[sandbox] mode = user` the agent's user cannot read your home folder, so it cannot read pi's login there. Not
  tried.

Why read only, and what else was considered: the design note's "B の認証の spike" and its result.

## What it does

`node dist/cli.js --session <id> [options] <prompt>`, in the worktree (task-hub starts agents there):

| Option | Default | |
|---|---|---|
| `--session` | (required) | task-hub's `{session}`. Names the files in `.task-durable/` |
| `--model` | `openai-codex/gpt-6-luna` | `<provider>/<model>`; only `openai-codex` is set up |
| `--thinking` | `medium` | pi's own default, given explicitly so that A and B think alike |
| `--auth` | `$PI_CODING_AGENT_DIR/auth.json` or `~/.pi/agent/auth.json` | pi's login (above) |
| `--restart-limit` | `5` | Pi Durable's `restartLimit`: how often one step may be cut short in a row before it is parked |

- **Its files** are in the worktree's `.task-durable/`, which it gives a `.gitignore` of `*`, so task-hub never commits
  them; they go when the worktree is cleaned up. `<session>.sqlite` holds the conversation and the tool calls under way,
  `<session>.lock` its owner's pid, `<session>.groups/` the process groups of its commands while they run, and `<session>.usage.json`
  what the session used (`harness.usage()`, for the comparison).
- **The first start** sends the prompt as the input `task-hub:first`, with the tools `read`, `write`, `edit` and `bash`
  in the worktree, and waits for the answer.
- **A start with the same session** finds that input in the SQLite file and goes on (`harness.resume()`), without
  sending the prompt again (task-hub's resume prompt, with `# Resumed`, is not used). A `bash` call that was cut short
  is not run again: the model gets it as interrupted, with the output so far. The commands the cut-short run left
  running are stopped first: Pi Durable runs each in a process group of its own, which killing the agent's group does
  not reach (`scripts/group-shell` notes each with its leader's start time). A group is stopped only while that
  leader still runs, so a file left by a command Pi Durable killed itself (a timeout, or the runner closing on
  SIGTERM) never stops a group whose id has since gone to another process.
- When the answer came but there is no `.task-report.md`, it asks for the report once. When a resumed run's answer
  failed (a model error), it asks once to go on.
- **One process per session.** `<session>.lock` is made with O_EXCL; while its owner lives, a second start ends with
  code 2. A dead owner's lock (kill -9) is taken over.
- **Its output** is a line per tool call (`· bash: npm test`), the first line of what the model says before its tool
  calls, and the final answer in full, which task-hub writes to the task's log as they come.
- SIGTERM, SIGHUP, and SIGINT close the session (not counted as a cut-short step), stop its command, and end the run by
  the same signal.

| Exit code | |
|---|---|
| 0 | Answered |
| 1 | Failed: the model did not answer, the login cannot be used, or the arguments are wrong |
| 2 | The session is in use by another live process |
| 3 | Parked (`restart_limit`): it wrote a `## Blocked` report, so the card goes to Blocked |

## Test

```sh
npm test   # builds, then the runner with pi-ai's faux provider in place of the model
```

It kills the runner (kill -9) in the middle of a tool call, starts it again, and checks it goes on to the report; and
checks the lock, the `restart_limit` report, SIGTERM, and the login (with fake values in the test's own folder, never
pi's real login). `test/faux-agent.ts` is the runner with that faux model, which answers from the transcript alone, so
a second process goes on the same way. `tests/test_task.py`'s `test_durable_runner_*` run it as `[agents] durable` and
`[resume] durable` under task-hub with the fake GitHub, kill it as K1 and K2 of the design note, and check it reaches
In review; they are skipped until this folder is installed and built.

Not tried: Windows (`scripts/group-shell` is POSIX), `[sandbox] mode = user`, and a long run against the real model.
