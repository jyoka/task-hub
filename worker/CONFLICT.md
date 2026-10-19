# task-hub conflict fix instructions

`task` sends everything below the line to the agent when the merge queue (or `[merge] prefix`) finds that a
task's PR conflicts with its base branch, followed by the task (with its Goal) and the conflicted files.
The agent runs in the task's worktree, on the PR's own branch, in the middle of a real merge of the base
branch; task-hub makes the merge commit, pushes it, and checks it.

---

You resolve the merge conflicts of one task-hub PR. Nobody will answer questions during the run, so do not
ask any.

The current directory is a git worktree on the PR's branch. task-hub has started `git merge` of the base
branch into it and stopped at the conflicts: the files listed below have conflict markers. The base branch
has moved on since the PR was made, usually because another PR was merged.

## What to do

1. For each conflicted file, read both sides and the history behind them (`git log --merge -p <file>`,
   `git diff`, the base branch's recent commits). Keep **both sides' features**: the PR's change and
   what the base branch gained. Do not drop either side to make the conflict go away.
2. Remove every conflict marker (`<<<<<<<`, `=======`, `>>>>>>>`). Look at the files that merged without
   conflicts too: a test, an import, or a list the two sides both extended may need both entries.
3. Numbered lists that both sides extended (design decisions in docs, migrations, changelog entries):
   keep the base branch's numbers as they are and renumber the PR's new entries after them, and fix
   the references to the renumbered entries.
4. Run the project's tests that cover the files you touched, and fix what the merge broke.
5. Do **not** commit, abort the merge, reset, rebase, push, or switch branches. task-hub makes the merge
   commit (with both parents) and pushes it after you finish. Do not change the board or the PR.
6. Write `.task-report.md` in the worktree root (task-hub never commits it):

```markdown
## Report

Which files conflicted, how you resolved each one (what you kept from each side), and the tests you ran
with their results.

## Please review

The resolutions a human should check, file by file.
```

If you cannot resolve a conflict without a decision only the human can make (the two sides want
opposite things, and the Goal does not say which wins), leave the files as they are and put this section
first in `.task-report.md`:

```markdown
## Blocked

One line: exactly what the human must decide.
```

task-hub then undoes the merge, and the card is marked Blocked with that line.
