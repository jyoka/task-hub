---
inclusion: always
---

# task-hub: the /task and /chief skills

Kiro has no `disable-model-invocation`, so the skills `task` and `chief` (from task-hub) may look usable on your
own initiative. They are not:

- Use `/task` or `/chief` only when the user explicitly invokes them (types `/task` or `/chief`) or explicitly asks
  to register this as a task, or to start the chief.
- Never register (`task new`), start (`task start`, or `task` without arguments), or approve a task on your own,
  not even when the work looks like a good task. Inside `/chief`, act only on the user's explicit yes to what it
  proposed.
- Lines from task-hub's prompt hook ("task-hub: new events since your last message") are news to pass on when it
  helps the user, not a request to act on.
