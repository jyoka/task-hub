"""A live run on a real GitHub board, for the Windows CI's button (windows.yml, workflow_dispatch; docs/release.md):
one card from Backlog to a PR with a stand-in agent, then cleaned up (PR closed, branch deleted, card Done).
Not a unit test (no test_ in its name): it needs the network, a token and a test board.

  TASK_HUB_LIVE_TOKEN    a token with repo and project scopes (the workflow passes the repository secret)
  TASK_HUB_LIVE_PROJECT  the test board, owner/number
  TASK_HUB_LIVE_ISSUES   where its cards are, owner/name
  TASK_HUB_LIVE_REPO     where the stand-in agent opens its PR, owner/name

The agent is a stand-in (no AI, no cost): it adds a line to live-check.md and writes its report. What is real is
everything else: gh against GitHub, the Project's fields, the worktree, the push, the PR, and the card's moves.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin" / "task"
AGENT = r'''
import datetime, sys
from pathlib import Path
prompt = sys.argv[-1]
with open("live-check.md", "a", encoding="utf-8") as f:
    f.write(f"- {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} 動作確認(task-hub の CI)\n")
Path(".task-report.md").write_text("## Report\n\nlive-check.md に 1 行足しました(CI の代わりのエージェント)。\n\n"
                                   "## Please review\n\n- live-check.md: 1 行だけ\n", encoding="utf-8")
print("stand-in agent: done")
'''


def main():
    need = ["TASK_HUB_LIVE_TOKEN", "TASK_HUB_LIVE_PROJECT", "TASK_HUB_LIVE_ISSUES", "TASK_HUB_LIVE_REPO"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        sys.exit("missing: " + ", ".join(missing) + " (docs/release.md, 「Windows を本物のボードで確かめる」)")
    tmp = Path(tempfile.mkdtemp(prefix="task-hub-live-"))
    home = tmp / "home"
    (home / ".config" / "task-hub").mkdir(parents=True)
    agent = tmp / "agent.py"
    agent.write_text(AGENT, encoding="utf-8")
    (home / ".config" / "task-hub" / "config.ini").write_text(
        f"[board]\nproject = {os.environ['TASK_HUB_LIVE_PROJECT']}\nissues = {os.environ['TASK_HUB_LIVE_ISSUES']}\n\n"
        f"[runner]\nagent = live\nparallel = 1\n\n[agents]\nlive = {Path(sys.executable).as_posix()} {agent.as_posix()} {{prompt}}\n",
        encoding="utf-8")
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "GH_TOKEN": os.environ["TASK_HUB_LIVE_TOKEN"],
           "TASK_HERDR": "0", "TASK_NO_UPDATE_NOTIFIER": "1", "GIT_AUTHOR_NAME": "task-hub ci",
           "GIT_AUTHOR_EMAIL": "ci@example.com", "GIT_COMMITTER_NAME": "task-hub ci",
           "GIT_COMMITTER_EMAIL": "ci@example.com", "GIT_CONFIG_GLOBAL": str(home / ".gitconfig")}
    env.pop("PYTHONUTF8", None)  # bin/task turns it on itself

    def run(*args, check=True):
        r = subprocess.run(args, env=env, capture_output=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, timeout=300)
        if check and r.returncode:
            sys.exit(f"{' '.join(map(str, args[:3]))} failed ({r.returncode}):\n{r.stdout}{r.stderr}")
        return r.stdout

    def task(*args, check=True):
        return run(sys.executable, str(BIN), *args, check=check)

    run("gh", "auth", "setup-git")  # git pushes with the same token
    title = f"CI の動作確認 {os.environ.get('GITHUB_RUN_ID', time.strftime('%Y%m%d%H%M%S'))}"
    out = task("new", "--title", title, "--repo", os.environ["TASK_HUB_LIVE_REPO"],
               "--goal", "live-check.md に 1 行足す(task-hub の CI の動作確認)。")
    tid = next(line.split(":", 1)[1].strip().strip('"') for line in out.splitlines() if line.strip().startswith("id:"))
    print(f"card #{tid}: {title}")
    pr = None
    try:
        for attempt in range(10):  # a card just made can take a moment to show on the board
            r = task("start", tid, check=False)
            if "not found on the board" not in r:
                break
            time.sleep(6)
        end = time.time() + 600
        status = ""
        while time.time() < end:
            show = task("show", tid)
            status = next((line.split(":", 1)[1].strip() for line in show.splitlines()
                           if line.strip().startswith("status:")), "")
            if status in ("In review", "Blocked"):
                break
            time.sleep(10)
        pr = next((line.split(":", 1)[1].strip().strip('"') for line in show.splitlines()
                   if line.strip().startswith("pr:")), None)
        print(task("log", tid, check=False)[-3000:])
        if status != "In review" or not pr:
            sys.exit(f"card #{tid} ended {status or 'still running'}, not In review with a PR:\n{show}")
        print(f"ok: card #{tid} In review, {pr}")
    finally:  # nothing left on the board or the repository
        if pr:
            run("gh", "pr", "close", pr, "--delete-branch", check=False)
        task("done", tid, check=False)


if __name__ == "__main__":
    main()
