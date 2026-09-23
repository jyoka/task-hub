# Routine setup (cloud agents)

A **routine** is a saved job on your claude.ai account: "when triggered, start a Claude Code
session in the cloud with these repos and follow these instructions". `task ready` triggers it
through an API URL and token. You set it up once, in the browser, because it belongs to your
claude.ai account and its token is shown only once.

The task board itself does **not** go to GitHub. Only the project repos need GitHub access.

## 1. Give Claude access to your project repos

1. Open <https://github.com/apps/claude> and install the Claude GitHub App.
2. Grant it every project repo you want tasks for.
3. For the first test, also create an empty private sandbox repo, for example
   `gh repo create jyoka/task-sandbox --private --add-readme`, and grant it too.

## 2. Create the routine

At <https://claude.ai/code/routines>, click **New routine**:

| Setting | Value |
|---|---|
| Name | `task-hub worker` |
| Instructions | everything below the line in [routine/PROMPT.md](../routine/PROMPT.md) |
| Model | the strongest coding model available |
| Repositories | every project repo tasks may target (and the sandbox) |
| Environment | Default (Trusted network) is enough, unless a project needs more |
| Connectors | remove all. The worker does not need any |
| Trigger | API only. No schedule: `task` decides when runs start |

Save the routine.

## 3. Add the API trigger and store the token

1. Open the routine, choose **Edit**, then **Add another trigger**, then **API**.
2. Copy the URL. Click **Generate token** and copy the token. It is shown only once.
3. Save both on the Mac (never in a repo):

   ```
   mkdir -p ~/.config/task-hub
   cat > ~/.config/task-hub/routine.env <<'EOF'
   TASK_ROUTINE_URL=<the URL>
   TASK_ROUTINE_TOKEN=<the token>
   EOF
   chmod 600 ~/.config/task-hub/routine.env
   ```

## 4. Check `gh`

`gh auth status` must show you logged in. `task` uses it to read the agents' PRs.

## 5. First end-to-end test

```
task new --title "Add hello.txt" --repo jyoka/task-sandbox \
  --goal "Add hello.txt at the repo root containing 'hello'. Acceptance: the file is in a PR."
task ready <id>          # prints started[1] with the session URL
```

Then:

- open the session URL and watch the run
- when it ends, run `task`: the task should become `review`, with Report, Please review, and `pr`
- check the PR in `jyoka/task-sandbox`: branch `claude/task-<id>`, ready for review
- merge it, run `task` again: the task becomes `done`

Also try the blocked path once: a task whose Goal cannot be done without asking
(for example "use the API key I will give you") should end as a draft PR and a `blocked` task.

## Adding a project repo later

1. Grant the Claude GitHub App access to it.
2. Add it to the routine's **Repositories**.

## Updating the prompt

Edit [routine/PROMPT.md](../routine/PROMPT.md), commit, then paste it into the routine's
Instructions again. The routine does not read the file itself.
