"""Black-box tests: run bin/task as a subprocess against a throwaway hub.

- GitHub repos are local bare repos (TASK_CLONE_URL), so clone/worktree/push are real git.
- `gh` is a fake that keeps PRs in a JSON file and records every call.
- The agent is a fake CLI whose behaviour is chosen by a MODE word in the task's goal.
- herdr is disabled (TASK_HERDR=0): runs use the background-process path.
"""
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "task"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
db_path = os.environ["TASK_TEST_GH_DB"]
db = json.load(open(db_path))
a = sys.argv[1:]
def opt(name):
    return a[a.index(name) + 1] if name in a else None
db.setdefault("calls", []).append(a[:2] + (["--draft"] if "--draft" in a else []) + (["--undo"] if "--undo" in a else []))
prs = db.setdefault("prs", {})
if a[:2] == ["pr", "list"]:
    pr = prs.get(f"{opt('--repo')} {opt('--head')}")
    print(json.dumps([pr] if pr else []))
elif a[:2] == ["pr", "create"]:
    key = f"{opt('--repo')} {opt('--head')}"
    url = f"https://github.com/{opt('--repo')}/pull/{len(prs) + 1}"
    prs[key] = {"url": url, "state": "OPEN", "isDraft": "--draft" in a,
                "body": open(opt("--body-file")).read(), "base": opt("--base")}
    print(url)
else:
    pr = next(p for p in prs.values() if p["url"] == a[2])
    if a[:2] == ["pr", "edit"]:
        pr["body"] = open(opt("--body-file")).read()
    elif a[:2] == ["pr", "ready"]:
        pr["isDraft"] = "--undo" in a
json.dump(db, open(db_path, "w"))
'''

FAKE_AGENT = r'''#!/usr/bin/env python3
import os, re, subprocess, sys
from pathlib import Path
prompt = sys.argv[-1]
with open(os.environ["TASK_TEST_AGENT_CALLS"], "a") as f:
    f.write(repr({"argv0": sys.argv[1:-1], "cwd": os.getcwd(), "prompt": prompt}) + "\n")
mode = re.search(r"MODE:(\w+)", prompt).group(1)
report = "## Report\n\nAdded hello.txt. Ran the tests: 3 passed.\n\n## Please review\n\n- hello.txt: wording\n"
print(f"fake agent working, mode {mode}")
if mode == "crash":
    sys.exit(1)
if mode == "slow":  # works a bit, then keeps running until stopped
    Path("hello.txt").write_text("partial work\n")
    print("waiting", flush=True)
    import time; time.sleep(60)
if mode not in ("nochange", "stuck"):
    Path("hello.txt").write_text(f"hello from mode {mode}\n")
if mode == "commit":  # an agent that ignores the "do not commit" rule
    subprocess.run(["git", "add", "-A"]); subprocess.run(["git", "commit", "-qm", "agent commit"])
if mode in ("blocked", "stuck"):  # stuck = blocked before changing anything
    report = "## Blocked\n\nNeed the Stripe test key.\n\n" + report
if mode != "noreport":
    Path(".task-report.md").write_text(report)
'''


class TaskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root, self.hub = root, root / "hub"
        self.hub.mkdir()
        self.db = root / "gh.json"
        self.db.write_text("{}")
        self.calls = root / "agent-calls.txt"
        for name, src in (("gh", FAKE_GH), ("agent", FAKE_AGENT)):
            (root / name).write_text(src)
            (root / name).chmod(0o755)
        git_id = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
                  "GIT_COMMITTER_EMAIL": "t@e"}
        self.env = {**os.environ, **git_id, "HOME": str(root), "TASK_HUB_DIR": str(self.hub),
                    "TASK_GH": str(root / "gh"), "TASK_HERDR": "0", "TASK_TEST_GH_DB": str(self.db),
                    "TASK_TEST_AGENT_CALLS": str(self.calls),
                    "TASK_CLONE_URL": f"file://{root}/origins/{{repo}}.git"}
        cfg = root / ".config" / "task-hub" / "config.ini"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(f"[runner]\nagent = fake\n\n[agents]\nfake = {root}/agent {{prompt}}\n"
                       f"other = {root}/agent --other {{prompt}}\n")
        self.origin("jyoka/app")

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def origin(self, repo):
        bare = self.root / "origins" / f"{repo}.git"
        seed = self.root / "seed"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
        (seed / "README.md").write_text("app\n")
        subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-qm", "init"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["rm", "-rf", str(seed)], check=True)
        return bare

    def task(self, *args, code=0):
        r = subprocess.run([str(BIN), *args], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, code, f"{r.stdout}{r.stderr}")
        return r.stdout

    def new(self, mode="ok", title="Add hello", repo="jyoka/app", *extra):
        out = self.task("new", "--title", title, "--repo", repo, "--goal", f"Say hello. MODE:{mode}", *extra)
        return re.search(r"id: (\d+)", out).group(1)

    def field(self, tid, name):
        m = re.search(rf"(?m)^  {name}: (.*)$", self.task("show", tid))
        return m.group(1).strip('"') if m else None

    def wait(self, tid, timeout=20):
        """Wait for the background run to leave in_progress."""
        end = time.time() + timeout
        while time.time() < end:
            if self.field(tid, "status") != "in_progress":
                return self.field(tid, "status")
            time.sleep(0.2)
        self.fail(f"task {tid} still in_progress; log:\n{self.task('log', tid, '--full')}")

    def gh(self):
        return json.loads(self.db.read_text())

    def pr(self, tid):
        return self.gh().get("prs", {}).get(f"jyoka/app task/{tid}")

    def origin_files(self, branch, repo="jyoka/app"):
        bare = self.root / "origins" / f"{repo}.git"
        r = subprocess.run(["git", "-C", str(bare), "ls-tree", "--name-only", branch], capture_output=True, text=True)
        return r.stdout.split()

    def agent_calls(self):
        return [eval(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    # --- the main path ---

    def test_full_lifecycle(self):
        tid = self.new()
        self.assertEqual(self.field(tid, "status"), "draft")
        out = self.task("start", tid)
        self.assertIn("started[1]", out)
        self.assertEqual(self.wait(tid), "review")
        pr = self.pr(tid)
        self.assertFalse(pr["isDraft"])
        self.assertEqual(pr["base"], "main")
        self.assertIn("## Report\n\nAdded hello.txt", pr["body"])
        self.assertIn("## Please review\n\n- hello.txt: wording", pr["body"])
        self.assertEqual(self.field(tid, "pr"), pr["url"])
        shown = self.task("show", tid)
        self.assertIn("Ran the tests: 3 passed.", shown)
        self.assertIn("hello.txt", self.origin_files("task/1"))
        self.assertNotIn(".task-report.md", self.origin_files("task/1"))
        # merged on GitHub -> done on the next sync, worktree cleaned up
        db = self.gh()
        db["prs"]["jyoka/app task/1"]["state"] = "MERGED"
        self.db.write_text(json.dumps(db))
        self.assertIn("done", self.task())
        self.assertEqual(self.field(tid, "status"), "done")
        self.assertFalse((self.root / ".local/share/task-hub/worktrees" / tid).exists())

    def test_agent_gets_instructions_and_brief_in_the_worktree(self):
        tid = self.new()
        self.task("start", tid)
        self.wait(tid)
        call = self.agent_calls()[0]
        self.assertTrue(call["cwd"].endswith(f"worktrees/{tid}"))
        self.assertIn("Do **not** commit", call["prompt"])  # worker/PROMPT.md
        self.assertIn("Task 1: Add hello", call["prompt"])
        self.assertIn("Branch: task/1", call["prompt"])
        self.assertIn("Say hello. MODE:ok", call["prompt"])
        self.assertNotIn("task-hub worker instructions", call["prompt"])  # file header is not sent

    def test_draft_never_runs(self):
        self.new()
        self.task()
        self.assertEqual(self.agent_calls(), [])

    # --- choosing the task and agent ---

    def test_start_without_id_takes_the_only_candidate(self):
        tid = self.new()
        self.task("start")
        self.assertEqual(self.wait(tid), "review")

    def test_start_without_id_and_no_terminal_lists_candidates(self):
        self.new(title="first")
        self.new(title="second")
        out = self.task("start", code=2)
        self.assertIn("candidates[2]", out)
        self.assertIn("task start <id>", out)

    def test_start_with_nothing_to_start(self):
        self.assertIn("0 drafts or blocked tasks", self.task("start"))

    def test_agent_per_task_and_default_from_config(self):
        a = self.new(title="a")
        b = self.new("ok", "b", "jyoka/app", "--agent", "other")
        self.task("start", a)
        self.task("start", b)
        self.wait(a), self.wait(b)
        self.assertEqual(self.field(a, "agent"), "fake")
        self.assertEqual(self.field(b, "agent"), "other")
        self.assertIn(["--other"], [c["argv0"] for c in self.agent_calls()])

    def test_unknown_agent_is_rejected(self):
        self.assertIn("unknown agent", self.task("new", "--title", "x", "--repo", "a/b", "--goal", "g",
                                                 "--agent", "nope", code=2))

    # --- the limit ---

    def fake_running(self, tid):
        """Make a task look like a live run: status in_progress, pid of a process named like a run."""
        proc = subprocess.Popen(["python3", "-c", "import time; time.sleep(60)", "_run"])
        self.addCleanup(proc.kill)
        f = next((self.hub / "tasks").glob(f"{int(tid):04d}-*.md"))
        text = re.sub(r"(?m)^status: .*$", "status: in_progress", f.read_text())
        f.write_text(re.sub(r"(?m)^pid:.*$", f"pid: {proc.pid}", text))
        return proc

    def test_parallel_limit_is_three(self):
        ids = [self.new("ok", f"t{i}") for i in range(4)]
        procs = [self.fake_running(tid) for tid in ids[:3]]
        out = self.task("start", ids[3])
        self.assertIn("status: ready", out)
        self.assertIn("all 3 slots busy", out)
        self.assertEqual(self.agent_calls(), [])
        # one run ends (its process exits) -> the next `task` frees the slot and starts the 4th
        procs[0].kill()
        procs[0].wait()
        self.task()
        self.assertEqual(self.field(ids[0], "status"), "blocked")  # died without finishing
        self.assertEqual(self.wait(ids[3]), "review")
        self.assertEqual(len(self.agent_calls()), 1)

    # --- blocked and re-runs ---

    def test_blocked_report_makes_a_draft_pr(self):
        tid = self.new("blocked")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "blocked")
        self.assertEqual(self.field(tid, "reason"), "Need the Stripe test key.")
        pr = self.pr(tid)
        self.assertTrue(pr["isDraft"])
        self.assertTrue(pr["body"].startswith("## Blocked\n\nNeed the Stripe test key."))

    def test_blocked_without_changes_keeps_the_agents_reason_and_opens_no_pr(self):
        tid = self.new("stuck")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "blocked")
        self.assertEqual(self.field(tid, "reason"), "Need the Stripe test key.")
        self.assertIsNone(self.pr(tid))
        self.assertIn("Ran the tests", self.task("show", tid))  # the report still reaches the board

    def test_rerun_continues_on_same_branch_and_pr(self):
        tid = self.new("blocked")
        self.task("start", tid)
        self.wait(tid)
        # the human edits the goal so the next run succeeds, then re-runs
        f = next((self.hub / "tasks").glob("0001-*.md"))
        f.write_text(f.read_text().replace("MODE:blocked", "MODE:ok"))
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "review")
        pr = self.pr(tid)
        self.assertFalse(pr["isDraft"])  # same PR switched to ready
        self.assertEqual(len(self.gh()["prs"]), 1)
        self.assertNotIn("## Blocked", pr["body"])
        second = self.agent_calls()[1]["prompt"]
        self.assertIn("An earlier run of this task stopped", second)
        self.assertIn("It was blocked because: Need the Stripe test key.", second)

    def test_no_report_is_blocked(self):
        tid = self.new("noreport")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "blocked")
        self.assertIn("without a report", self.field(tid, "reason"))
        self.assertTrue(self.pr(tid)["isDraft"])  # the work is pushed so it is not lost

    def test_crash_without_changes_is_blocked_and_opens_no_pr(self):
        tid = self.new("crash")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "blocked")
        self.assertIn("exit 1", self.field(tid, "reason"))
        self.assertIsNone(self.pr(tid))
        self.assertIn("agent exited with code 1", self.task("log", tid))

    def test_report_without_changes_is_blocked(self):
        tid = self.new("nochange")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "blocked")
        self.assertIn("changed no files", self.field(tid, "reason"))

    def test_agent_that_commits_itself_still_works(self):
        tid = self.new("commit")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "review")
        self.assertIn("hello.txt", self.origin_files("task/1"))

    def test_ctrl_c_stops_the_agent_but_keeps_its_work(self):
        tid = self.new("slow")
        self.task("start", tid)
        end = time.time() + 15
        while time.time() < end and "waiting" not in self.task("log", tid):
            time.sleep(0.2)
        os.kill(int(self.field(tid, "pid")), signal.SIGINT)  # what Ctrl-C in the herdr pane sends
        self.assertEqual(self.wait(tid), "blocked")
        self.assertIn("stopped with Ctrl-C", self.task("log", tid))
        self.assertTrue(self.pr(tid)["isDraft"])  # partial work pushed, not lost
        self.assertIn("hello.txt", self.origin_files("task/1"))

    def test_dead_run_is_detected(self):
        tid = self.new()
        proc = self.fake_running(tid)
        self.task()
        self.assertEqual(self.field(tid, "status"), "in_progress")  # alive: left alone
        proc.kill()
        proc.wait()
        self.task()
        self.assertEqual(self.field(tid, "status"), "blocked")
        self.assertIn("stopped unexpectedly", self.field(tid, "reason"))

    def test_unreachable_repo_blocks_with_reason(self):
        tid = self.new(repo="jyoka/missing")
        out = self.task("start", tid)
        self.assertIn("could not start", out)
        self.assertEqual(self.field(tid, "status"), "blocked")

    # --- CLI behaviour ---

    def test_home_view_counts_what_needs_you(self):
        self.new(title="a")
        self.new(title="b")
        out = self.task()
        self.assertIn("draft=2", out)
        self.assertIn("2 task(s) need you", out)

    def test_done_by_hand_and_noop(self):
        tid = self.new()
        self.task("done", tid)
        self.assertIn("no-op", self.task("done", tid))
        self.assertIn("error:", self.task("start", tid, code=1))

    def test_unknown_flag_is_rejected(self):
        self.assertIn("unknown flag --stat", self.task("list", "--stat", "ready", code=2))

    def test_new_requires_title_repo_and_goal(self):
        self.task("new", "--title", "x", code=2)
        self.task("new", "--title", "x", "--repo", "not-a-repo", "--goal", "g", code=2)
        self.task("new", "--title", "x", "--repo", "a/b", code=2)

    def test_goal_headings_are_demoted_below_task_sections(self):
        self.task("new", "--title", "x", "--repo", "a/b", "--goal", "## What\nfix it")
        out = self.task("show", "1")
        self.assertIn("### What", out)
        self.assertNotIn("\n  ## What", out)

    def test_empty_states_are_explicit(self):
        self.assertIn("0 open tasks", self.task())
        self.assertIn("0 tasks with status ready", self.task("list", "--status", "ready"))
        self.assertIn("has not run yet", self.task("log", self.new()))

    def test_changes_are_committed_to_the_board_history(self):
        tid = self.new()
        self.task("start", tid)
        self.wait(tid)
        log = subprocess.run(["git", "-C", str(self.hub), "log", "--format=%s"], env=self.env,
                             capture_output=True, text=True).stdout
        self.assertIn("task 1: new draft", log)
        self.assertIn("task 1: review", log)

    def test_board_defaults_to_a_private_folder_outside_the_tool_repo(self):
        env = {k: v for k, v in self.env.items() if k != "TASK_HUB_DIR"}
        r = subprocess.run([str(BIN), "new", "--title", "x", "--repo", "a/b", "--goal", "g"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        board = self.root / ".local/share/task-hub/board"
        self.assertEqual(len(list((board / "tasks").glob("*.md"))), 1)
        self.assertTrue((board / ".git").is_dir())
        self.assertFalse((BIN.parent.parent / "tasks").exists())

    def test_version(self):
        self.assertRegex(self.task("--version").strip(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
