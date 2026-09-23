# Lessons from building task-hub (2026-09-23)

What one day of building and testing task-hub taught us: about AI agent work efficiency,
about building tools like this, and what is still unproven.

## Timeline in one table

| Version | Idea | Why it changed |
|---|---|---|
| 0.1 | Cloud agents (Claude routines) claim tasks and push status to the board's `main` | Several writers on one branch needed locking and race handling. The user called it chaos and dangerous |
| 0.2 | Only the Mac writes the board. The brief goes in the trigger, results come back in the PR | Still Claude-only. The user also uses Codex and Pi, and the work Mac only allows Kiro |
| 0.3 | Any agent CLI, run locally in a worktree, one herdr workspace per task. The agent only edits files | Current design. Proven with all four agents on a real repo |

Two rewrites in one day were cheap, because the board format and the PR contract survived
each rewrite. But both rewrites came from constraints that one early question would have surfaced.

## AI agent work efficiency

### What worked

- **Give the agent the smallest possible contract.** "Edit files, run tests, write
  `.task-report.md`" was the one change that made four vendors behave the same. All git and
  GitHub work moved into task-hub, and that also got around Codex's sandbox (no network, no writes
  outside the folder). The less the agent has to do besides the task, the less varies between agents.
- **Let code guarantee the output format, not the prompt.** The PR description is built
  by task-hub from the report file, so every PR looks the same no matter which agent wrote it.
- **Ask for "Please review" explicitly.** Every agent produced a specific list (files,
  decisions, risks) instead of "review the PR". This is the part that saves human time.
- **A blocked path makes agents honest.** Given an impossible task (commit a password it
  cannot know), Claude refused to fabricate, explained why, and proposed safer options. It did this
  because the instructions said stuck is a valid outcome. Without that exit, agents tend to invent something.
- **Re-runs with memory.** A re-run gets the earlier report and the reason it stopped, so it
  continues instead of starting over.
- **Cap parallel work at what a human can review (3).** The bottleneck is human review,
  not agent speed. Trivial tasks took 15 to 55 seconds, and reviewing them takes longer than that.

### What wasted effort

- **Constraints discovered late.** Which agents? Which machines? Which terminal tool (herdr,
  not tmux)? Which git host? Each late answer caused a redesign. Ask these before designing.
- **Ambiguous instructions produce noise.** Two agents listed the report file itself under
  "Please review", because nothing said it is never committed. One added sentence fixed it.
  Anything the agent might wonder about should be answered in the instructions.
- **Assuming CLI flags from help text.** `codex exec --full-auto` looked right from a help
  description but does not exist in Codex 0.155. Flags change between versions: run the command
  once before relying on it. Prefer long-standing flags (`-s workspace-write`).

### Speed observed (trivial one-file task, approval to finished PR)

| Agent | Time | Log lines |
|---|---|---|
| Claude Code | 15s | 9 |
| Kiro | 15s | 11 |
| Pi | 40s | 12 |
| Codex | 54s | 274 (very verbose output) |

These numbers are from one trivial task each. They say nothing about quality on real work.

## Building tools like this

- **Unit tests with fakes only prove your own assumptions.** 27 tests passed, and the first real
  run still found 4 bugs: SSH clone refused, a wrong Codex flag, an empty PR rejected by GitHub,
  and noisy review lists. The herdr trial found 3 more: the Enter key swallowed while the shell was
  starting, the pane having a different environment, and the run starting before its task file was saved.
- **Fakes are often more forgiving than the real thing.** The fake GitHub accepted a PR with
  no commits. The real one refused it. When a real run fails, reproduce the failure in a test first,
  then fix it (done for the blocked-without-changes case).
- **Check test isolation before changing anything.** `HERDR_SESSION` did not isolate herdr
  commands, so the first experiment created two workspaces in the user's live session. They were
  removed right away. The fix: a read-only check of which session a command reaches, then the change.
- **Break the code on purpose.** Changing the limit, the blocked detection, or the report handling
  had to make tests fail. One mutation survived because two guards protected the same thing. That
  is fine, but it is worth knowing.
- **Don't depend on the user's personal setup.** SSH keys, git protocol, and shell startup differ
  per machine. HTTPS through `gh`'s own login, set on task-hub's clones only, works everywhere
  `gh` is logged in.
- **One writer per file.** Every race we hit came from two processes writing the same file.
  The fix was always to decide who owns the file, not to add locking.

## Simplicity rules for task-hub

1. No feature without a user need stated in this project. "Might be useful" is not enough.
2. Plain files and existing tools (git, gh, herdr, the agents' own CLIs) before anything new.
3. One way to do each thing.
4. When a real run shows a problem, fix it at the smallest point and add the test that would
   have caught it.

## What we could still prove

Ordered by value. Each is one small experiment, not a feature.

1. **A real task in a real repo.** A multi-file change with real tests. Do the reports and review
   lists still save review time when the work is not trivial?
2. **The work Mac.** Kiro only, company GitHub (possibly SSO), company network rules. Does
   `gh`-based HTTPS cloning work there? Does `kiro-cli` stay logged in for unattended runs?
3. **`/task` in Codex, Pi, and Kiro.** Only tested in Claude Code. Does each agent register a task
   when asked, and never on its own?
4. **Blocked, then unblocked.** Edit the Goal with the missing decision, re-run, and check that the
   agent finishes on the same branch and PR with a real agent (tested only with the fake agent).
5. **Two tasks touching the same files.** Their PRs will conflict. Is "merge one, re-run the other"
   good enough?
6. **Long runs and a sleeping Mac.** Close the lid during a run: does the run resume or show up
   correctly as stopped?
7. **Codex with tests that need the network**, under the default sandbox.
