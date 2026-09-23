"""Black-box tests: run bin/task as a subprocess against a throwaway hub.

GitHub is replaced by a fake `gh` that answers `gh pr list` from a JSON file,
and the routine API by a local HTTP server that records every run it is asked to start.
"""
import http.server
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "task"

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
repo, head = a[a.index("--repo") + 1], a[a.index("--head") + 1]
db = json.load(open(os.environ["FAKE_GH_DB"]))
if repo in db.get("_fail", []):
    print("HTTP 404: Could not resolve to a Repository", file=sys.stderr); sys.exit(1)
pr = db.get(f"{repo} {head}")
print(json.dumps([pr] if pr else []))
"""


class Routine(http.server.BaseHTTPRequestHandler):
    calls = []
    status = 200

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Routine.calls.append({"auth": self.headers["Authorization"], "text": body["text"]})
        self.send_response(Routine.status)
        self.end_headers()
        n = len(Routine.calls)
        self.wfile.write(json.dumps({"claude_code_session_url": f"https://claude.ai/code/s{n}"}).encode())

    def log_message(self, *_):
        pass


class TaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Routine)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.hub = root / "hub"
        self.hub.mkdir()
        self.db = root / "prs.json"
        self.db.write_text("{}")
        gh = root / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.env = {**os.environ, "TASK_HUB_DIR": str(self.hub), "HOME": str(root), "TASK_GH": str(gh),
                    "FAKE_GH_DB": str(self.db),
                    "TASK_ROUTINE_URL": f"http://127.0.0.1:{self.server.server_port}/fire",
                    "TASK_ROUTINE_TOKEN": "test-token"}
        Routine.calls, Routine.status = [], 200

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def run_task(self, *args, code=0, env=None):
        r = subprocess.run([str(BIN), *args], env=env or self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, code, f"{r.stdout}{r.stderr}")
        return r.stdout

    def new(self, title="Fix login", repo="jyoka/app"):
        out = self.run_task("new", "--title", title, "--repo", repo, "--goal", "Make it work.")
        return re.search(r"id: (\d+)", out).group(1)

    def field(self, tid, name):
        m = re.search(rf"(?m)^  {name}: (.*)$", self.run_task("show", tid))
        return m.group(1).strip('"') if m else None

    def pr(self, tid, state="OPEN", draft=False, body=None, updated="2999-01-01T00:00:00Z", repo="jyoka/app"):
        db = json.loads(self.db.read_text())
        db[f"{repo} claude/task-{tid}"] = {
            "url": f"https://github.com/{repo}/pull/{tid}", "state": state, "isDraft": draft,
            "updatedAt": updated,
            "body": body if body is not None else
            "## Report\n\nChanged the redirect.\n\n## Please review\n\n- src/login.py: redirect target\n"}
        self.db.write_text(json.dumps(db))

    # --- lifecycle ---

    def test_full_lifecycle(self):
        tid = self.new()
        self.assertEqual(self.field(tid, "status"), "draft")
        self.assertIn("started[1]", self.run_task("ready", tid))
        self.assertEqual(self.field(tid, "status"), "in_progress")
        self.assertEqual(self.field(tid, "branch"), "claude/task-1")
        self.assertEqual(self.field(tid, "session"), "https://claude.ai/code/s1")
        self.run_task()  # no PR yet: stays in progress
        self.assertEqual(self.field(tid, "status"), "in_progress")
        self.pr(tid)
        self.assertIn("review", self.run_task())
        self.assertEqual(self.field(tid, "status"), "review")
        shown = self.run_task("show", tid)
        self.assertIn("Changed the redirect.", shown)
        self.assertIn("src/login.py: redirect target", shown)
        self.assertEqual(self.field(tid, "pr"), "https://github.com/jyoka/app/pull/1")
        self.pr(tid, state="MERGED")
        self.run_task("sync")
        self.assertEqual(self.field(tid, "status"), "done")

    def test_routine_gets_the_brief_and_the_token(self):
        tid = self.new()
        self.run_task("ready", tid)
        call = Routine.calls[0]
        self.assertEqual(call["auth"], "Bearer test-token")
        self.assertIn("task-hub task 1", call["text"])
        self.assertIn("repo: jyoka/app", call["text"])
        self.assertIn("branch: claude/task-1", call["text"])
        self.assertIn("Make it work.", call["text"])

    def test_draft_never_starts(self):
        self.new()
        self.run_task("sync")
        self.assertEqual(Routine.calls, [])

    def test_parallel_limit_is_three(self):
        ids = [self.new(f"t{i}") for i in range(4)]
        for tid in ids:
            self.run_task("ready", tid, "--no-dispatch")
        out = self.run_task("sync")
        self.assertIn("started[3]", out)
        self.assertEqual(len(Routine.calls), 3)
        self.assertEqual(self.field(ids[3], "status"), "ready")
        self.assertIn("all 3 slots busy", self.run_task("sync"))
        # one finishes -> the waiting one starts on the next sync
        self.pr(ids[0])
        out = self.run_task()
        self.assertIn("started[1]", out)
        self.assertEqual(self.field(ids[3], "status"), "in_progress")
        self.assertEqual(len(Routine.calls), 4)

    def test_oldest_ready_starts_first(self):
        ids = [self.new(t) for t in "abcd"]
        for tid in reversed(ids):
            self.run_task("ready", tid, "--no-dispatch")
        self.run_task("sync")
        self.assertIn(f"task-hub task {ids[0]}\n", Routine.calls[0]["text"])

    # --- blocked / re-queue ---

    def test_draft_pr_means_blocked_with_reason(self):
        tid = self.new()
        self.run_task("ready", tid)
        self.pr(tid, draft=True, body="## Blocked\n\nNeed the Stripe test key.\n\n## Report\n\nHalf done.\n")
        self.run_task()
        self.assertEqual(self.field(tid, "status"), "blocked")
        self.assertEqual(self.field(tid, "reason"), "Need the Stripe test key.")

    def test_requeued_task_ignores_its_old_draft_pr_until_updated(self):
        tid = self.new()
        self.run_task("ready", tid)
        self.pr(tid, draft=True, updated="2000-01-01T00:00:00Z")  # PR activity from before this run
        self.run_task()
        self.assertEqual(self.field(tid, "status"), "in_progress")
        self.pr(tid, draft=False)  # the new run finishes on the same branch
        self.run_task()
        self.assertEqual(self.field(tid, "status"), "review")

    def test_blocked_task_reruns_on_same_branch(self):
        tid = self.new()
        self.run_task("ready", tid)
        self.pr(tid, draft=True)
        self.run_task()
        self.run_task("ready", tid)
        self.assertEqual(self.field(tid, "status"), "in_progress")
        self.assertEqual(len(Routine.calls), 2)
        self.assertIn("branch: claude/task-1", Routine.calls[1]["text"])
        self.assertIsNone(self.field(tid, "reason"))

    def test_closed_pr_means_blocked(self):
        tid = self.new()
        self.run_task("ready", tid)
        self.pr(tid, state="CLOSED")
        self.run_task()
        self.assertEqual(self.field(tid, "status"), "blocked")

    # --- failures ---

    def test_unconfigured_routine_leaves_task_ready(self):
        env = {k: v for k, v in self.env.items() if not k.startswith("TASK_ROUTINE")}
        tid = self.new()
        out = self.run_task("ready", tid, env=env)
        self.assertIn("routine not configured", out)
        self.assertEqual(self.field(tid, "status"), "ready")

    def test_failed_start_leaves_task_ready(self):
        Routine.status = 401
        tid = self.new()
        out = self.run_task("ready", tid)
        self.assertIn("could not start the routine for task 1", out)
        self.assertEqual(self.field(tid, "status"), "ready")

    def test_github_error_is_reported_and_changes_nothing(self):
        tid = self.new(repo="jyoka/gone")
        self.run_task("ready", tid)
        self.db.write_text(json.dumps({"_fail": ["jyoka/gone"]}))
        out = self.run_task()
        self.assertIn("github_errors[1]", out)
        self.assertIn("Could not resolve", out)
        self.assertEqual(self.field(tid, "status"), "in_progress")

    # --- CLI behaviour ---

    def test_home_view_counts_what_needs_you(self):
        self.new("a")
        self.new("b")
        out = self.run_task()
        self.assertIn("draft=2", out)
        self.assertIn("2 task(s) need you", out)

    def test_done_by_hand_and_noop(self):
        tid = self.new()
        self.run_task("done", tid)
        self.assertIn("no-op", self.run_task("done", tid))
        self.assertIn("error:", self.run_task("ready", tid, code=1))

    def test_removed_agent_commands_explain_why(self):
        self.assertIn("agents no longer write to the board", self.run_task("claim", code=2))

    def test_unknown_flag_is_rejected(self):
        self.assertIn("unknown flag --stat", self.run_task("list", "--stat", "ready", code=2))

    def test_new_requires_title_repo_and_goal(self):
        self.run_task("new", "--title", "x", code=2)
        self.run_task("new", "--title", "x", "--repo", "not-a-repo", "--goal", "g", code=2)
        self.run_task("new", "--title", "x", "--repo", "a/b", code=2)

    def test_goal_headings_are_demoted_below_task_sections(self):
        self.run_task("new", "--title", "x", "--repo", "a/b", "--goal", "## What\nfix it")
        out = self.run_task("show", "1")
        self.assertIn("### What", out)
        self.assertNotIn("\n  ## What", out)

    def test_empty_states_are_explicit(self):
        self.assertIn("0 open tasks", self.run_task())
        self.assertIn("0 tasks with status ready", self.run_task("list", "--status", "ready"))
        self.assertIn("nothing changed", self.run_task("sync"))

    def test_changes_are_committed_locally_when_hub_is_a_git_repo(self):
        subprocess.run(["git", "init", "-q", str(self.hub)], check=True)
        subprocess.run(["git", "-C", str(self.hub), "config", "user.email", "t@e"], check=True)
        subprocess.run(["git", "-C", str(self.hub), "config", "user.name", "t"], check=True)
        tid = self.new()
        self.run_task("ready", tid)
        log = subprocess.run(["git", "-C", str(self.hub), "log", "--format=%s"],
                             capture_output=True, text=True).stdout
        self.assertIn("task 1: new draft", log)
        self.assertIn("task 1: started", log)

    def test_version(self):
        self.assertRegex(self.run_task("--version").strip(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
