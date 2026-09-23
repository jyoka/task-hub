# Routine setup (cloud agents)

Do this once. Steps marked **(you)** happen in a browser. Steps marked **(terminal)** can be
run by you or by Claude Code after you confirm.

## 1. Put the hub on GitHub (terminal)

```
cd "$HOME/AIprogramming PJ/task-hub"
gh repo create jyoka/task-hub --private --source . --push
```

Keep `main` unprotected: the cloud agents push status changes to it.

## 2. Give Claude access to the repos (you)

1. Open <https://github.com/apps/claude> and install the Claude GitHub App.
2. Grant it `jyoka/task-hub` and every project repo you want tasks for.

## 3. Create the routine (you)

At <https://claude.ai/code/routines>, click **New routine**:

| Setting | Value |
|---|---|
| Name | `task-hub worker` |
| Instructions | everything below the line in [routine/PROMPT.md](../routine/PROMPT.md) |
| Model | the strongest coding model available |
| Repositories | `jyoka/task-hub` **plus** every project repo tasks may target |
| Environment | Default (Trusted network) is enough, unless a project needs more |
| Connectors | remove all. The worker does not need any |
| Trigger 1 | Schedule: hourly (the backup run) |
| Trigger 2 | API (added after saving, see step 4) |

Click **Create**.

## 4. Add the API trigger (you)

1. Open the routine, choose **Edit**, then **Add another trigger**, then **API**.
2. Copy the URL. Click **Generate token** and copy the token. It is shown only once.
3. Save both on the Mac (never in the repo):

   ```
   mkdir -p ~/.config/task-hub
   cat > ~/.config/task-hub/routine.env <<'EOF'
   TASK_ROUTINE_URL=<the URL>
   TASK_ROUTINE_TOKEN=<the token>
   EOF
   chmod 600 ~/.config/task-hub/routine.env
   ```

## 5. First end-to-end test

Use a throwaway repo that is added to the routine.

```
task new --title "Add a hello.txt" --repo <owner/sandbox> --goal "Create hello.txt containing 'hello'. Acceptance: file exists on a PR."
task ready <id>        # should print: started[1]{id,session}: ...
```

Then check:

- the session URL shows the run working
- `task show <id>` becomes `review`, with the Report, Please review, and `pr` filled in
  (run `git -C "$HOME/AIprogramming PJ/task-hub" pull` first, or any `task` write pulls for you)
- the PR exists in the sandbox repo

If the status never changes but the PR exists, the routine could not push to the hub's `main`.
See [operations.md](operations.md).

## Adding a project repo later

1. Grant the Claude GitHub App access to it.
2. Add it to the routine's **Repositories**.
3. Tasks for it now work. Re-queue any that were blocked with `task ready <id>`.

## Updating the prompt

Edit [routine/PROMPT.md](../routine/PROMPT.md), commit, then paste it into the routine's
Instructions again. The routine does not read the file itself.
