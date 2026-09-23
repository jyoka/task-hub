"""Black-box tests: run bin/task as a subprocess, with GitHub replaced by fakes.

- The Project board, Issues, and PRs live in a fake `gh` that keeps everything in one JSON file.
- Project repos are local bare repos (TASK_CLONE_URL), so clone/worktree/push are real git.
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
import fcntl, json, os, re, sys
path = os.environ["TASK_TEST_GH_DB"]
lock = open(path + ".lock", "w"); fcntl.flock(lock, fcntl.LOCK_EX)  # runs call gh concurrently
db = json.load(open(path))
a = sys.argv[1:]
def opt(name):
    return a[a.index(name) + 1] if name in a else None
def fail(msg):
    print(msg, file=sys.stderr); sys.exit(1)
out = None
cmd = a[:2]
fields = dict(x.split("=", 1) for x in a[3::2]) if cmd == ["api", "graphql"] else {}  # -f name=value pairs
kind = cmd[1] if cmd[0] == "project" else ("item-list" if "items(" in fields.get("query", "") else "field-list") \
    if cmd == ["api", "graphql"] else None
if db.get("down") and kind and (db["down"] is True or kind == db["down"]):
    fail("GraphQL: API rate limit exceeded for user ID 1.")
if cmd == ["project", "view"]:
    out = {"id": "PVT_1", "url": "https://github.com/users/jyoka/projects/2"}
elif kind == "field-list":
    assert fields["id"] == "PVT_1"
    out = {"data": {"node": {"fields": {"nodes": db["fields"]}}}}
elif kind == "item-list":
    db["item_list_calls"] = db.get("item_list_calls", 0) + 1
    # each "alias: fieldValueByName(name: ...)" gets the value only if the name is spelled as on the board
    aliases = re.findall(r'(\w+): fieldValueByName\(name: "([^"]+)"\)', fields["query"])
    names = {f["name"] for f in db["fields"]}
    nodes = []
    for iid, it in db["items"].items():
        if fields["q"] == "-status:Done" and it["values"].get("status") == "Done":
            continue
        issue = db["issues"][str(it["number"])]
        node = {"id": iid, "content": {"number": it["number"], "title": issue["title"],
                                       "repository": {"nameWithOwner": db["issues_repo"]},
                                       "url": f"https://github.com/{db['issues_repo']}/issues/{it['number']}"}}
        for alias, name in aliases:
            v = it["values"].get(name.lower()) if name in names else None
            node[alias] = None if v is None else {"name" if name == "Status" else "text": v}
        nodes.append(node)
    out = {"data": {"node": {"items": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
elif cmd == ["project", "item-add"]:
    number = int(opt("--url").rstrip("/").rsplit("/", 1)[-1])
    iid = f"PVTI_{number}"
    db["items"][iid] = {"number": number, "values": {}}
    out = {"id": iid}
elif cmd == ["project", "item-edit"]:
    field = next(f for f in db["fields"] if f["id"] == opt("--field-id"))
    if "--single-select-option-id" in a:
        value = next(o["name"] for o in field["options"] if o["id"] == opt("--single-select-option-id"))
    else:
        value = opt("--text")
    db["items"][opt("--id")]["values"][field["name"].lower()] = value
    out = {"id": opt("--id")}
elif cmd == ["issue", "create"]:
    if opt("--repo") != db["issues_repo"]:
        fail("could not resolve repository")
    n = len(db["issues"]) + 1
    db["issues"][str(n)] = {"title": opt("--title"), "body": open(opt("--body-file")).read(), "state": "OPEN", "comments": []}
    print(f"https://github.com/{db['issues_repo']}/issues/{n}")
elif cmd == ["issue", "comment"]:
    db["issues"][a[2]]["comments"].append({"body": open(opt("--body-file")).read()})
elif cmd == ["issue", "view"]:
    i = db["issues"][a[2]]
    out = {"body": i["body"], "state": i["state"], "comments": i["comments"]}
elif cmd == ["issue", "close"]:
    db["issues"][a[2]]["state"] = "CLOSED"
elif cmd == ["pr", "list"]:
    if opt("--repo") in db.get("broken_repos", []):
        fail("HTTP 404: Could not resolve to a Repository")
    pr = db["prs"].get(f"{opt('--repo')} {opt('--head')}")
    out = [pr] if pr else []
elif cmd == ["pr", "create"]:
    if db.get("pr_create_fails"):
        fail("pull request create failed: GraphQL: Resource not accessible by integration")
    key = f"{opt('--repo')} {opt('--head')}"
    url = f"https://github.com/{opt('--repo')}/pull/{len(db['prs']) + 1}"
    db["prs"][key] = {"url": url, "state": "OPEN", "isDraft": "--draft" in a,
                      "body": open(opt("--body-file")).read(), "base": opt("--base")}
    print(url)
elif cmd == ["pr", "edit"]:
    next(p for p in db["prs"].values() if p["url"] == a[2])["body"] = open(opt("--body-file")).read()
elif a[0] == "api" and "/pulls/" in a[1]:  # REST: repos/<owner>/<name>/pulls/<number>
    repo, number = a[1].split("/", 1)[1].rsplit("/pulls/", 1)
    pr = next(p for p in db["prs"].values() if p["url"] == f"https://github.com/{repo}/pull/{number}")
    out = {"merged": pr.get("merged", False)}
elif a[0] == "api" and "/pulls?" in a[1]:  # REST: repos/<owner>/<name>/pulls?head=<owner>:<branch>&state=closed
    repo = a[1].split("/", 1)[1].split("/pulls?")[0]
    head = a[1].split("head=")[1].split("&")[0].split(":", 1)[1]
    pr = db["prs"].get(f"{repo} {head}")
    out = [{"merged_at": "2026-09-23T00:00:00Z" if pr.get("merged") else None}] if pr and pr["state"] != "OPEN" else []
elif cmd == ["pr", "ready"]:
    next(p for p in db["prs"].values() if p["url"] == a[2])["isDraft"] = "--undo" in a
else:
    fail(f"fake gh: unsupported {a}")
json.dump(db, open(path, "w"))
if out is not None:
    print(json.dumps(out))
'''

FAKE_AGENT = r'''#!/usr/bin/env python3
import os, re, subprocess, sys
from pathlib import Path
prompt = sys.argv[-1]
with open(os.environ["TASK_TEST_AGENT_CALLS"], "a") as f:
    f.write(repr({"argv0": sys.argv[1:-1], "cwd": os.getcwd(), "prompt": prompt}) + "\n")
mode = re.findall(r"MODE:(\w+)", prompt)[-1]  # the latest goal wins (re-runs keep the old report below it)
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
if mode in ("blocked", "stuck"):  # stuck = blocked before changing anything
    report = "## Blocked\n\nNeed the Stripe test key.\n\n" + report
if mode != "noreport":
    Path(".task-report.md").write_text(report)
if mode == "prfail":  # GitHub is up, but opening the PR is refused
    import json
    db = json.load(open(os.environ["TASK_TEST_GH_DB"])); db["pr_create_fails"] = True
    json.dump(db, open(os.environ["TASK_TEST_GH_DB"], "w"))
if mode == "outage":  # GitHub becomes unreachable right as the agent finishes
    import json
    db = json.load(open(os.environ["TASK_TEST_GH_DB"])); db["down"] = True
    json.dump(db, open(os.environ["TASK_TEST_GH_DB"], "w"))
'''

STATUS_OPTIONS = ["Backlog", "Ready", "In progress", "In review", "Blocked", "Done"]  # GitHub's spelling


class TaskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name)
        self.db = root / "gh.json"
        self.save_db({"issues_repo": "jyoka/tasks", "issues": {}, "items": {}, "prs": {},
                      "fields": [{"id": "F_status", "name": "Status", "type": "ProjectV2SingleSelectField", "dataType": "SINGLE_SELECT",
                                  "options": [{"id": f"O_{i}", "name": n} for i, n in enumerate(STATUS_OPTIONS)]},
                                 {"id": "F_title", "name": "Title", "type": "ProjectV2Field", "dataType": "TITLE"},
                                 {"id": "F_repo", "name": "Target repo", "type": "ProjectV2Field", "dataType": "TEXT"},
                                 {"id": "F_agent", "name": "Agent", "type": "ProjectV2Field", "dataType": "TEXT"},
                                 {"id": "F_base", "name": "Base branch", "type": "ProjectV2Field", "dataType": "TEXT"}]})
        self.calls = root / "agent-calls.txt"
        for name, src in (("gh", FAKE_GH), ("agent", FAKE_AGENT)):
            (root / name).write_text(src)
            (root / name).chmod(0o755)
        git_id = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
                  "GIT_COMMITTER_EMAIL": "t@e"}
        self.env = {**os.environ, **git_id, "HOME": str(root), "TASK_GH": str(root / "gh"), "TASK_HERDR": "0",
                    "TASK_TEST_GH_DB": str(self.db), "TASK_TEST_AGENT_CALLS": str(self.calls),
                    "TASK_CLONE_URL": f"file://{root}/origins/{{repo}}.git"}
        self.write_config()
        self.origin("jyoka/app")

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def write_config(self, extra=""):
        cfg = self.root / ".config" / "task-hub" / "config.ini"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(f"[board]\nproject = jyoka/2\nissues = jyoka/tasks\n\n[runner]\nagent = fake\n\n"
                       f"[agents]\nfake = {self.root}/agent {{prompt}}\nother = {self.root}/agent --other {{prompt}}\n"
                       + extra)

    def save_db(self, db):
        self.db.write_text(json.dumps(db))

    def gh(self):
        return json.loads(self.db.read_text())

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

    def task(self, *args, code=0):
        r = subprocess.run([str(BIN), *args], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, code, f"{r.stdout}{r.stderr}")
        return r.stdout

    def new(self, mode="ok", title="Add hello", repo="jyoka/app", *extra):
        out = self.task("new", "--title", title, "--repo", repo, "--goal", f"Say hello. MODE:{mode}", *extra)
        return re.search(r"id: (\d+)", out).group(1)

    def status(self, tid):
        return self.gh()["items"][f"PVTI_{tid}"]["values"].get("status")

    def move(self, tid, status):
        """What the human does by dragging the card on GitHub."""
        db = self.gh()
        db["items"][f"PVTI_{tid}"]["values"]["status"] = status
        self.save_db(db)

    def comments(self, tid):
        return [c["body"] for c in self.gh()["issues"][tid]["comments"]]

    def wait(self, tid, timeout=20):
        """Wait for the background run to leave In progress."""
        end = time.time() + timeout
        while time.time() < end:
            if self.status(tid) != "In progress":
                return self.status(tid)
            time.sleep(0.2)
        self.fail(f"task {tid} still In progress; log:\n{self.task('log', tid, '--full')}")

    def pr(self, tid):
        return self.gh()["prs"].get(f"jyoka/app task/{tid}")

    def origin_files(self, branch):
        bare = self.root / "origins" / "jyoka/app.git"
        return subprocess.run(["git", "-C", str(bare), "ls-tree", "--name-only", branch],
                              capture_output=True, text=True).stdout.split()

    def push_branch(self, branch, filename):
        """A branch someone pushed to the project repo, with one extra file."""
        bare = self.root / "origins" / "jyoka/app.git"
        seed = self.root / f"clone-{branch.replace('/', '-')}"
        subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "checkout", "-qb", branch], check=True)
        (seed / filename).write_text("work on the branch\n")
        subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-qm", filename], check=True, env=self.env)
        subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", branch], check=True, capture_output=True)

    def agent_calls(self):
        return [eval(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def run_file(self, tid):
        return self.root / ".local/state/task-hub/runs" / f"{tid}.json"

    def fake_running(self, tid):
        """Make a task look like a live run on this machine."""
        proc = subprocess.Popen(["python3", "-c", "import time; time.sleep(60)", "_run"])
        self.addCleanup(proc.kill)
        self.move(tid, "In progress")
        self.run_file(tid).parent.mkdir(parents=True, exist_ok=True)
        self.run_file(tid).write_text(json.dumps({"pid": str(proc.pid), "started": "2026-01-01T00:00:00Z",
                                                  "repo": "jyoka/app", "branch": f"task/{tid}"}))
        return proc

    # --- registering ---

    def test_new_creates_an_issue_and_a_draft_card(self):
        tid = self.new("ok", "Add hello", "jyoka/app", "--agent", "other")
        db = self.gh()
        self.assertEqual(db["issues"][tid]["title"], "Add hello")
        self.assertIn("MODE:ok", db["issues"][tid]["body"])
        self.assertEqual(db["items"][f"PVTI_{tid}"]["values"],
                         {"status": "Backlog", "target repo": "jyoka/app", "agent": "other"})

    def test_draft_never_runs(self):
        self.new()
        self.task()
        self.assertEqual(self.agent_calls(), [])

    # --- the main path ---

    def test_card_moved_to_ready_runs_and_ends_in_review_then_done(self):
        tid = self.new()
        self.move(tid, "Ready")  # dragged on GitHub
        self.assertIn("started[1]", self.task())
        self.assertEqual(self.wait(tid), "In review")
        pr = self.pr(tid)
        self.assertFalse(pr["isDraft"])
        self.assertEqual(pr["base"], "main")
        self.assertIn("## Report\n\nAdded hello.txt", pr["body"])
        self.assertIn("## Please review\n\n- hello.txt: wording", pr["body"])
        self.assertIn(f"Closes jyoka/tasks#{tid}", pr["body"])
        report = self.comments(tid)[-1]
        self.assertTrue(report.startswith("<!-- task-hub report -->"))
        self.assertIn("Ran the tests: 3 passed.", report)
        self.assertIn(pr["url"], report)
        self.assertIn("hello.txt", self.origin_files(f"task/{tid}"))
        self.assertNotIn(".task-report.md", self.origin_files(f"task/{tid}"))
        # merged: GitHub closes the Issue and its "Item closed" workflow moves the card to Done;
        # the next sync notices the card left the open columns and cleans up locally
        db = self.gh()
        db["prs"][f"jyoka/app task/{tid}"]["state"] = "MERGED"
        db["issues"][tid]["state"] = "CLOSED"
        self.save_db(db)
        self.move(tid, "Done")
        self.assertIn("cleaned up", self.task())
        self.assertFalse((self.root / ".local/share/task-hub/worktrees" / tid).exists())
        self.assertFalse(self.run_file(tid).exists())

    def test_start_command_also_works(self):
        tid = self.new()
        self.assertIn("started[1]", self.task("start", tid))
        self.assertEqual(self.wait(tid), "In review")

    def test_agent_gets_instructions_and_the_issue_body(self):
        tid = self.new()
        self.task("start", tid)
        self.wait(tid)
        call = self.agent_calls()[0]
        self.assertTrue(call["cwd"].endswith(f"worktrees/{tid}"))
        self.assertIn("Do **not** commit", call["prompt"])
        self.assertIn("Task 1: Add hello", call["prompt"])
        self.assertIn("Branch: task/1", call["prompt"])
        self.assertIn("Say hello. MODE:ok", call["prompt"])

    def test_watch_starts_ready_cards(self):
        tid = self.new()
        self.move(tid, "Ready")
        self.env["TASK_WATCH_ONCE"] = "1"
        out = self.task("watch")
        self.assertIn("started[1]", out)
        self.assertEqual(self.wait(tid), "In review")

    # --- choosing ---

    def test_start_without_id_takes_the_only_candidate(self):
        tid = self.new()
        self.task("start")
        self.assertEqual(self.wait(tid), "In review")

    def test_start_without_id_and_no_terminal_lists_candidates(self):
        self.new(title="first")
        self.new(title="second")
        out = self.task("start", code=2)
        self.assertIn("candidates[2]", out)

    def test_agent_per_card_and_default_from_config(self):
        a = self.new(title="a")
        b = self.new("ok", "b", "jyoka/app", "--agent", "other")
        self.task("start", a)
        self.task("start", b)
        self.wait(a), self.wait(b)
        self.assertIn([], [c["argv0"] for c in self.agent_calls()])
        self.assertIn(["--other"], [c["argv0"] for c in self.agent_calls()])

    def test_unknown_agent_on_a_card_blocks_only_that_card(self):
        bad, good = self.new(title="bad"), self.new(title="good")
        db = self.gh()
        db["items"][f"PVTI_{bad}"]["values"]["agent"] = "nope"  # typo made on GitHub
        self.save_db(db)
        self.move(bad, "Ready")
        self.move(good, "Ready")
        self.task()
        self.assertEqual(self.status(bad), "Blocked")
        self.assertIn("unknown agent", self.comments(bad)[-1])
        self.assertEqual(self.wait(good), "In review")

    # --- the limit ---

    def test_parallel_limit_is_three(self):
        ids = [self.new("ok", f"t{i}") for i in range(4)]
        procs = [self.fake_running(tid) for tid in ids[:3]]
        self.move(ids[3], "Ready")
        out = self.task()
        self.assertIn("all 3 slots busy", out)
        self.assertEqual(self.status(ids[3]), "Ready")
        self.assertEqual(self.agent_calls(), [])
        procs[0].kill()
        procs[0].wait()
        self.task()
        self.assertEqual(self.status(ids[0]), "Blocked")  # its run died
        self.assertEqual(self.wait(ids[3]), "In review")

    # --- blocked and re-runs ---

    def test_blocked_report_makes_a_draft_pr_and_a_blocked_card(self):
        tid = self.new("blocked")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "Blocked")
        self.assertTrue(self.pr(tid)["isDraft"])
        self.assertIn("## Blocked\n\nNeed the Stripe test key.", self.comments(tid)[-1])

    def test_blocked_without_changes_comments_and_opens_no_pr(self):
        tid = self.new("stuck")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "Blocked")
        self.assertIsNone(self.pr(tid))
        self.assertIn("Need the Stripe test key.", self.comments(tid)[-1])

    def test_rerun_continues_on_same_branch_and_pr(self):
        tid = self.new("blocked")
        self.task("start", tid)
        self.wait(tid)
        # the human answers by editing the Issue on GitHub, then moves the card to Ready again
        db = self.gh()
        db["issues"][tid]["body"] = "Say hello. Test key is in the vault. MODE:ok"
        self.save_db(db)
        self.move(tid, "Ready")
        self.task()
        self.assertEqual(self.wait(tid), "In review")
        self.assertFalse(self.pr(tid)["isDraft"])
        self.assertEqual(len(self.gh()["prs"]), 1)
        second = self.agent_calls()[1]["prompt"]
        self.assertIn("An earlier run of this task stopped", second)
        self.assertIn("Need the Stripe test key.", second)

    def test_no_report_is_blocked(self):
        tid = self.new("noreport")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "Blocked")
        self.assertIn("without a report", self.comments(tid)[-1])

    def test_ctrl_c_stops_the_agent_but_keeps_its_work(self):
        tid = self.new("slow")
        self.task("start", tid)
        end = time.time() + 15
        while time.time() < end and "waiting" not in self.task("log", tid):
            time.sleep(0.2)
        os.kill(int(json.loads(self.run_file(tid).read_text())["pid"]), signal.SIGINT)
        self.assertEqual(self.wait(tid), "Blocked")
        self.assertTrue(self.pr(tid)["isDraft"])
        self.assertIn("hello.txt", self.origin_files(f"task/{tid}"))

    def test_github_down_when_the_run_finishes_keeps_the_report(self):
        tid = self.new("outage")
        self.task("start", tid)
        run = json.loads(self.run_file(tid).read_text())
        end = time.time() + 20
        while time.time() < end:  # until the run process has ended
            pid = json.loads(self.run_file(tid).read_text()).get("pid")
            if pid and subprocess.run(["ps", "-p", pid], capture_output=True).returncode != 0:
                break
            time.sleep(0.2)
        log = self.task("log", tid)
        self.assertIn("could not finish", log)
        report = Path(run["worktree"]) / ".task-report.md"
        self.assertTrue(report.exists())  # kept, so nothing the agent wrote is lost
        # GitHub comes back: the next sync sees the dead run and blocks the card, pointing at the log
        db = self.gh(); db["down"] = False; self.save_db(db)
        self.task()
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn("stopped unexpectedly", self.comments(tid)[-1])
        self.assertIn("Ran the tests: 3 passed.", self.comments(tid)[-1])  # the kept report reaches GitHub
        self.assertFalse(report.exists())

    def test_finish_failing_with_github_up_posts_the_report(self):
        tid = self.new("prfail")
        self.task("start", tid)
        self.wait(tid)
        self.assertEqual(self.status(tid), "Blocked")
        last = self.comments(tid)[-1]
        self.assertIn("could not finish the run", last)
        self.assertIn("Ran the tests: 3 passed.", last)  # the agent's report is not lost

    def test_card_in_progress_without_a_run_here_is_blocked(self):
        tid = self.new()
        self.move(tid, "In progress")  # dragged by hand, nothing runs it
        self.task()
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn("no run of this task on this machine", self.comments(tid)[-1])

    def test_existing_branch_from_elsewhere_is_never_reused(self):
        # a task/1 branch already exists in the repo (an older board, or someone else's work)
        bare = self.root / "origins" / "jyoka/app.git"
        seed = self.root / "other"
        subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "checkout", "-qb", "task/1"], check=True)
        (seed / "old.txt").write_text("someone else's work\n")
        subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-qm", "old"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "task/1"], check=True, capture_output=True)
        tid = self.new()
        self.task("start", tid)
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn("task/1 already exists", self.comments(tid)[-1])
        self.assertEqual(self.agent_calls(), [])
        self.assertEqual(self.origin_files("task/1"), ["README.md", "old.txt"])  # untouched

    # --- starting from another branch (Base branch) ---

    def test_base_branch_card_starts_from_it_and_its_pr_goes_into_it(self):
        self.push_branch("feat/x", "feat.txt")
        tid = self.new("ok", "Add hello", "jyoka/app", "--base", "feat/x")
        self.assertEqual(self.gh()["items"][f"PVTI_{tid}"]["values"]["base branch"], "feat/x")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertEqual(self.pr(tid)["base"], "feat/x")
        self.assertEqual(self.origin_files(f"task/{tid}"), ["README.md", "feat.txt", "hello.txt"])
        self.assertEqual(self.origin_files("feat/x"), ["README.md", "feat.txt"])  # untouched until merged
        self.assertIn("feat/x", self.agent_calls()[0]["prompt"])

    def test_base_branch_not_on_github_blocks_with_reason(self):
        tid = self.new("ok", "Add hello", "jyoka/app", "--base", "feat/only-local")
        self.task("start", tid)
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn("feat/only-local", self.comments(tid)[-1])
        self.assertIn("push", self.comments(tid)[-1])
        self.assertEqual(self.agent_calls(), [])

    def test_pr_merged_into_base_branch_moves_the_card_to_done(self):
        # GitHub closes an Issue from "Closes ..." only when the PR is merged into the default branch
        self.push_branch("feat/x", "feat.txt")
        tid = self.new("ok", "Add hello", "jyoka/app", "--base", "feat/x")
        self.task("start", tid)
        self.wait(tid)
        self.task()
        self.assertEqual(self.status(tid), "In review")  # not merged yet
        db = self.gh()
        db["prs"][f"jyoka/app task/{tid}"].update(state="MERGED", merged=True)
        self.save_db(db)
        self.assertIn("Done", self.task())
        self.assertEqual(self.status(tid), "Done")
        self.assertEqual(self.gh()["issues"][tid]["state"], "CLOSED")
        self.assertFalse(self.run_file(tid).exists())

    def test_rerun_after_base_branch_changed_or_deleted_is_blocked_with_reason(self):
        self.push_branch("feat/x", "feat.txt")
        self.push_branch("feat/y", "y.txt")
        tid = self.new("blocked", "Add hello", "jyoka/app", "--base", "feat/x")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "Blocked")
        for value, reason in (("feat/y", "Base branch was changed"), ("", "Base branch was changed"),
                              ("feat/x", "feat/x is not on GitHub")):
            if value == "feat/x":  # merged and deleted on GitHub, then the card is re-run
                subprocess.run(["git", "-C", str(self.root / "origins/jyoka/app.git"), "branch", "-D", "feat/x"],
                               check=True, capture_output=True)
            db = self.gh()
            db["items"][f"PVTI_{tid}"]["values"]["base branch"] = value
            self.save_db(db)
            self.task("start", tid)
            self.assertEqual(self.status(tid), "Blocked")
            self.assertIn(reason, self.comments(tid)[-1])
        self.assertEqual(len(self.agent_calls()), 1)  # never re-ran on the wrong base
        self.assertEqual(self.pr(tid)["base"], "feat/x")

    def test_base_branch_can_be_set_after_a_run_that_pushed_nothing_or_was_reset(self):
        self.push_branch("feat/y", "y.txt")
        tid = self.new("stuck")  # no base; the agent blocks without changing anything: no branch, no PR
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "Blocked")
        db = self.gh()
        db["items"][f"PVTI_{tid}"]["values"]["base branch"] = "feat/y"
        db["issues"][tid]["body"] = "Say hello on feat/y. MODE:blocked"
        self.save_db(db)
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "Blocked")  # ran on feat/y, pushed, draft PR into feat/y
        self.assertEqual(self.pr(tid)["base"], "feat/y")
        self.assertEqual(self.origin_files(f"task/{tid}"), ["README.md", "hello.txt", "y.txt"])
        # the documented way to start over on another base: close the PR, delete the task branch
        self.push_branch("feat/z", "z.txt")
        db = self.gh()
        db["prs"][f"jyoka/app task/{tid}"]["state"] = "CLOSED"
        db["items"][f"PVTI_{tid}"]["values"]["base branch"] = "feat/z"
        db["issues"][tid]["body"] = "Say hello on feat/z. MODE:ok"
        self.save_db(db)
        subprocess.run(["git", "-C", str(self.root / "origins/jyoka/app.git"), "branch", "-D", f"task/{tid}"],
                       check=True, capture_output=True)
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertEqual(self.pr(tid)["base"], "feat/z")
        self.assertEqual(self.origin_files(f"task/{tid}"), ["README.md", "hello.txt", "z.txt"])

    def test_base_branch_value_is_checked(self):
        self.assertIn("without origin/", self.task("new", "--title", "x", "--repo", "jyoka/app", "--base",
                                                   "origin/feat/x", "--goal", "g", code=2))
        self.task("new", "--title", "x", "--repo", "jyoka/app", "--base", "a..b", "--goal", "g", code=2)
        self.task("new", "--title", "x", "--repo", "jyoka/app", "--base", "HEAD", "--goal", "g", code=2)
        self.push_branch("feat/x", "feat.txt")
        tid = self.new()
        db = self.gh()
        db["items"][f"PVTI_{tid}"]["values"]["base branch"] = " feat/x "  # typed on the card with spaces
        self.save_db(db)
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertEqual(self.pr(tid)["base"], "feat/x")

    def test_merge_into_base_branch_is_seen_without_this_machines_run_file(self):
        self.push_branch("feat/x", "feat.txt")
        tid = self.new("ok", "Add hello", "jyoka/app", "--base", "feat/x")
        self.task("start", tid)
        self.wait(tid)
        self.run_file(tid).unlink()  # the task ran on another machine
        db = self.gh()
        db["prs"][f"jyoka/app task/{tid}"].update(state="MERGED", merged=True)
        self.save_db(db)
        self.task()
        self.assertEqual(self.status(tid), "Done")
        self.assertEqual(self.gh()["issues"][tid]["state"], "CLOSED")

    def test_missing_repo_on_card_blocks_with_reason(self):
        tid = self.new()
        db = self.gh()
        db["items"][f"PVTI_{tid}"]["values"]["target repo"] = ""
        self.save_db(db)
        self.move(tid, "Ready")
        self.task()
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn('no valid "Target repo"', self.comments(tid)[-1])

    # --- setup problems ---

    def test_missing_config_explains_setup(self):
        (self.root / ".config/task-hub/config.ini").write_text("[runner]\nagent = fake\n")
        out = self.task(code=1)
        self.assertIn("board is not configured", out)
        self.assertIn("docs/setup.md", out)

    def test_missing_project_fields_are_listed(self):
        db = self.gh()
        db["fields"] = [f for f in db["fields"] if f["name"] != "Agent"]
        next(f for f in db["fields"] if f["name"] == "Base branch")["dataType"] = "SINGLE_SELECT"
        db["fields"][0]["options"] = [o for o in db["fields"][0]["options"] if o["name"] != "Blocked"]
        self.save_db(db)
        out = self.task(code=1)
        self.assertIn('Status option "Blocked"', out)
        self.assertIn('text field "Agent"', out)
        self.assertIn('text field "Base branch" (it is SINGLE_SELECT, make it TEXT)', out)

    def test_field_names_are_matched_without_regard_to_case(self):
        db = self.gh()
        for f in db["fields"]:
            f["name"] = {"Target repo": "Target Repo", "Base branch": "base branch"}.get(f["name"], f["name"])
        self.save_db(db)
        self.push_branch("feat/x", "feat.txt")
        tid = self.new("ok", "Add hello", "jyoka/app", "--base", "feat/x")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertEqual(self.pr(tid)["base"], "feat/x")

    def test_github_outage_is_reported_and_watch_keeps_going(self):
        tid = self.new()
        self.move(tid, "Ready")
        db = self.gh()
        db["down"] = True  # e.g. the GraphQL rate limit
        self.save_db(db)
        out = self.task(code=1)
        self.assertIn("rate limit", out)
        self.assertNotIn("auth refresh", out)  # not a permissions problem; waiting fixes it
        db["down"] = "item-list"  # the watch had read the Project before GitHub went down
        self.save_db(db)
        self.env["TASK_WATCH_ONCE"] = "1"
        out = self.task("watch")  # prints the error and would keep looping
        self.assertIn("error: GraphQL: API rate limit exceeded", out)
        self.assertEqual(self.status(tid), "Ready")

    def test_a_watch_cycle_makes_one_github_call_when_nothing_changes(self):
        for title in ("a", "b"):
            self.new(title=title)
        tid = self.new(title="c")
        self.task("start", tid)
        self.wait(tid)
        db = self.gh()
        db["item_list_calls"] = 0
        self.save_db(db)
        self.env["TASK_WATCH_ONCE"] = "1"
        self.task("watch")
        self.assertEqual(self.gh()["item_list_calls"], 1)

    # --- CLI behaviour ---

    def test_home_view_counts_what_needs_you(self):
        self.new(title="a")
        self.new(title="b")
        out = self.task()
        self.assertIn("Backlog=2", out)
        self.assertNotIn("Done=", out)
        self.assertIn("2 task(s) need you", out)

    def test_done_by_hand_closes_the_issue(self):
        tid = self.new()
        self.task("done", tid)
        self.assertEqual(self.status(tid), "Done")
        self.assertEqual(self.gh()["issues"][tid]["state"], "CLOSED")
        self.assertIn("no-op", self.task("done", tid))

    def test_unknown_flag_is_rejected(self):
        self.assertIn("unknown flag --stat", self.task("show", "1", "--stat", code=2))

    def test_new_requires_title_repo_and_goal(self):
        self.task("new", "--title", "x", code=2)
        self.task("new", "--title", "x", "--repo", "not-a-repo", "--goal", "g", code=2)
        self.task("new", "--title", "x", "--repo", "a/b", code=2)

    def test_empty_states_are_explicit(self):
        self.assertIn("0 open tasks", self.task())
        self.assertIn("0 Backlog or Blocked tasks", self.task("start"))
        self.assertIn("has not run on this machine", self.task("log", "5"))

    def test_version(self):
        self.assertRegex(self.task("--version").strip(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
