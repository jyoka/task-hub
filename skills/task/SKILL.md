---
name: task
description: Register the current conversation as a Backlog task (a GitHub Issue on the user's task-hub Project board). Use ONLY when the user explicitly invokes this skill (for example /task) or explicitly asks to register or save this as a task. Never use it on your own initiative.
argument-hint: "[optional notes: target repo, agent, scope, what to leave out]"
disable-model-invocation: true
---

The user asked to turn this conversation into a task on their task-hub board.
Only register what the user asked for. Never start or approve the task: that is the user's job.

1. From the conversation (and the notes the user passed, if any), work out:
   - **title**: short imperative, under 60 characters
   - **repo**: the GitHub `owner/name` the work happens in. Infer it from the current directory
     (`git remote get-url origin`) or the conversation. If it is still unclear, ask the user; do not guess.
   - **agent** (optional): only if the user named one (for example claude, codex, pi, kiro).
     Otherwise leave it out and the machine's default agent is used.
   - **goal**: what the agent that runs the task needs, without this chat. Write it as markdown
     (use `###` for any headings) with:
     - what to build or fix, and why
     - context from the chat: relevant files, decisions already made, constraints, things ruled out
     - acceptance criteria as a checklist the agent can verify

   The agent that runs the task sees only this text and the repo, so include every fact from
   the chat that matters. Leave out secrets, tokens, and personal data.

2. Write the goal to a temporary file and run:

   ```
   task new --title "<title>" --repo <owner/name> [--agent <agent>] --goal-file <tmpfile>
   ```

   If `task` is not on PATH, use `"$HOME/AIprogramming PJ/task-hub/bin/task"`.

3. Reply with the task id, its Issue URL, and one line: "Move the card to Ready (or run `task start`) when you want an agent to pick it up."
