---
name: task
description: Register the current conversation as a draft task on the task-hub board, for a cloud agent to work on after the user approves it.
argument-hint: "[optional notes: target repo, scope, what to leave out]"
disable-model-invocation: true
---

The user typed `/task` to turn this conversation into a task on their task-hub board.
Only register what the user asked for. Never mark the task ready: approving it is the user's job.

1. From the conversation (and the notes passed after `/task`, if any), work out:
   - **title**: short imperative, under 60 characters
   - **repo**: the GitHub `owner/name` the work happens in. Infer it from the current directory
     (`git remote get-url origin`) or the conversation. If it is still unclear, ask the user; do not guess.
   - **theme** (optional): a one-word area such as `auth` or `docs`
   - **goal**: what the cloud agent needs to do the work without this chat. Write it as markdown (use `###` for any headings) with:
     - what to build or fix, and why
     - context from the chat: relevant files, decisions already made, constraints, things ruled out
     - acceptance criteria as a checklist the agent can verify

   The cloud agent sees only this text and the repo, so include every fact from the chat that matters.
   Leave out secrets, tokens, and personal data.

2. Write the goal to a temporary file and run:

   ```
   task new --title "<title>" --repo <owner/name> [--theme <theme>] --goal-file <tmpfile>
   ```

   If `task` is not on PATH, use `"$HOME/AIprogramming PJ/task-hub/bin/task"`.

3. Reply with the task id, its file path, and one line: "Run `task ready <id>` when you want an agent to pick it up."
