---
name: task
description: Register the current conversation as a Backlog task (a GitHub Issue on the user's task-hub Project board). Use ONLY when the user explicitly invokes this skill (for example /task) or explicitly asks to register or save this as a task. Never use it on your own initiative.
argument-hint: "[optional notes: target repo, agent, scope, what to leave out]"
---

The user asked to turn this conversation into a task on their task-hub board.
Only register what the user asked for. Never start or approve the task: that is the user's job.

## How big a task is

One task is one concern the user can review, merge, and revert on its own: a pull request they can
review in 10 to 15 minutes (a few hundred changed lines, not counting generated files).

- Split work of different kinds (a feature, a bug fix, tooling or lint setup, docs), or work on different
  files that the user might want to merge or revert separately.
- Keep together work that touches the same file or function (separate tasks would conflict), or whose
  parts mean nothing alone.
- When a task needs another task's code, output, or decision, register the other one first and pass
  `--blocked-by <its id>`: task-hub starts it only after that one is done (merged, or closed with
  `task done`), so it builds on the result. Link only for that. Two tasks that merely touch the same area
  are not a dependency: keep them in one task, or leave them unlinked and accept a possible merge conflict.
- Give tasks split from one piece of work a shared title prefix with a count, for example
  "PR #23 follow-up (1/3): save experience from voice", so they stay together on the board.

If the conversation holds several such concerns, do not fold them into one task. Show the user the split
(titles and one line each) and ask which to register; register each as its own task.

## Registering

1. From the conversation (and the notes the user passed, if any), work out:
   - **title**: short imperative, under 60 characters
   - **repo**: the GitHub `owner/name` the work happens in. Infer it from the current directory
     (`git remote get-url origin`) or the conversation. If it is still unclear, ask the user; do not guess.
   - **base** (optional): the branch the work builds on, when it is not the default branch. If the
     conversation happened on a feature branch (`git branch --show-current`) and the task continues it,
     use that branch. It must be on GitHub (`git ls-remote --heads origin <branch>` prints a line);
     if it is not, tell the user to push it first.
   - **agent** (optional): only if the user named one (for example claude, codex, pi, kiro).
     Otherwise leave it out and the machine's default agent is used.
   - **blocked by** (optional): the ids of registered tasks this one needs first (see above).
   - **research** (optional): when the user wants an investigation, comparison, or answer rather than a
     change to the code, add `--research`. The agent's report is then the result (no pull request needed).
   - **goal**: what the agent that runs the task needs, without this chat. Write it as markdown
     (use `###` for any headings) with:
     - what to build or fix, and why
     - context from the chat: relevant files, decisions already made, constraints, things ruled out
     - acceptance criteria as a checklist the agent can verify
     - a `### Ready conditions` heading, when something must hold before the work can start: the tasks
       it needs, each with one line on what it uses from them (the same ones you pass to `--blocked-by`),
       and anything outside the board (a decision made, a key in `.env`, a service running). The agent
       checks them first and stops as Blocked if one does not hold

   The agent that runs the task sees only this text and the repo, so include every fact from
   the chat that matters. Leave out secrets, tokens, and personal data.

2. Write the goal to a temporary file and run:

   ```
   task new --title "<title>" --repo <owner/name> [--base <branch>] [--agent <agent>] [--research] [--blocked-by <id>,<id>] --goal-file <tmpfile>
   ```

   If `task` is not on PATH, use `~/.local/lib/task-hub/bin/task`.

3. Reply with the task id, its Issue URL, and one line: "Move the card to Ready (or run `task start`) when you want an agent to pick it up."
