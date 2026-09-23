"""Black-box tests: run bin/task as a subprocess against throwaway hubs."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "task"


def sh(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


class Hub:
    def __init__(self, path, home):
        self.path, self.home = Path(path), home

    def run(self, *args, code=0):
        env = {**os.environ, "TASK_HUB_DIR": str(self.path), "HOME": self.home}
        env.pop("TASK_ROUTINE_URL", None)
        env.pop("TASK_ROUTINE_TOKEN", None)
        r = subprocess.run([str(BIN), *args], env=env, capture_output=True, text=True)
        assert r.returncode == code, f"exit {r.returncode} != {code}\n{r.stdout}{r.stderr}"
        return r.stdout

    def new(self, title="Fix login", repo="jyoka/app"):
        out = self.run("new", "--title", title, "--repo", repo, "--goal", "Make it work.")
        return re.search(r"id: (\d+)", out).group(1)

    def status(self, tid):
        return re.search(r"status: (\w+)", self.run("show", tid)).group(1)

    def fill_report(self, tid):
        f = next((self.path / "tasks").glob(f"{int(tid):04d}-*.md"))
        text = f.read_text()
        text = text.replace("(agent fills this in)", "Changed the redirect.")
        text = text.replace("(agent lists the exact files, decisions, or risks the human must check)",
                            "- src/login.py: redirect target")
        f.write_text(text)


class LocalHubTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = Hub(self.tmp.name, self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_lifecycle(self):
        tid = self.hub.new()
        self.assertEqual(self.hub.status(tid), "draft")
        out = self.hub.run("ready", tid)
        self.assertIn("dispatch: skipped", out)  # no routine configured
        self.assertIn("claimed", self.hub.run("claim"))
        self.assertEqual(self.hub.status(tid), "in_progress")
        self.hub.fill_report(tid)
        self.hub.run("review", tid, "--pr", "https://github.com/jyoka/app/pull/1")
        self.assertEqual(self.hub.status(tid), "review")
        self.assertIn("pr: ", self.hub.run("show", tid))
        self.hub.run("done", tid)
        self.assertEqual(self.hub.status(tid), "done")

    def test_home_view_counts_what_needs_you(self):
        self.hub.new("a")
        self.hub.new("b")
        out = self.hub.run()
        self.assertIn("draft=2", out)
        self.assertIn("2 task(s) need you", out)

    def test_claim_only_takes_ready_tasks(self):
        self.hub.new()
        self.assertIn("no ready tasks", self.hub.run("claim"))

    def test_parallel_limit_is_three(self):
        ids = [self.hub.new(f"t{i}") for i in range(4)]
        for tid in ids:
            self.hub.run("ready", tid)
        for _ in range(3):
            self.assertIn("claimed", self.hub.run("claim"))
        self.assertIn("all 3 slots busy", self.hub.run("claim"))
        self.assertEqual(self.hub.status(ids[3]), "ready")

    def test_claim_takes_oldest_ready_first(self):
        a, b = self.hub.new("a"), self.hub.new("b")
        self.hub.run("ready", b)
        self.hub.run("ready", a)
        self.assertIn(f"id: {a}", self.hub.run("claim"))

    def test_review_refused_until_report_is_filled(self):
        tid = self.hub.new()
        self.hub.run("ready", tid)
        self.hub.run("claim")
        out = self.hub.run("review", tid, code=2)
        self.assertIn("Report", out)
        self.assertEqual(self.hub.status(tid), "in_progress")

    def test_invalid_transitions_are_refused(self):
        tid = self.hub.new()
        self.assertIn("error:", self.hub.run("done", tid, code=1))
        self.assertIn("error:", self.hub.run("block", tid, "--reason", "x", code=1))

    def test_repeated_mutation_is_a_noop(self):
        tid = self.hub.new()
        self.hub.run("ready", tid)
        self.assertIn("no-op", self.hub.run("ready", tid))

    def test_blocked_task_can_be_requeued(self):
        tid = self.hub.new()
        self.hub.run("ready", tid)
        self.hub.run("claim")
        self.hub.run("block", tid, "--reason", "need API key")
        self.assertIn("need API key", self.hub.run("show", tid))
        self.hub.run("ready", tid)
        self.assertEqual(self.hub.status(tid), "ready")
        self.assertNotIn("need API key", self.hub.run("show", tid))

    def test_unknown_flag_is_rejected(self):
        out = self.hub.run("list", "--stat", "ready", code=2)
        self.assertIn("unknown flag --stat", out)

    def test_new_requires_title_repo_and_goal(self):
        self.hub.run("new", "--title", "x", code=2)
        self.hub.run("new", "--title", "x", "--repo", "not-a-repo", "--goal", "g", code=2)
        self.hub.run("new", "--title", "x", "--repo", "a/b", code=2)

    def test_goal_headings_are_demoted_below_task_sections(self):
        self.hub.run("new", "--title", "x", "--repo", "a/b", "--goal", "## What\nfix it")
        out = self.hub.run("show", "1")
        self.assertIn("### What", out)
        self.assertNotIn("\n  ## What", out)

    def test_empty_states_are_explicit(self):
        self.assertIn("0 open tasks", self.hub.run())
        self.assertIn("0 tasks with status ready", self.hub.run("list", "--status", "ready"))

    def test_version(self):
        self.assertRegex(self.hub.run("--version").strip(), r"^\d+\.\d+\.\d+$")


class GitSyncTest(unittest.TestCase):
    """Two clones of one hub, like the local Mac and a cloud runner."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        sh("git", "init", "--bare", "-b", "main", str(root / "remote.git"))
        sh("git", "clone", str(root / "remote.git"), str(root / "a"))
        for name in ("a",):
            self._config(root / name)
        (root / "a" / ".gitignore").write_text(".rejected/\n")
        sh("git", "add", ".", cwd=root / "a")
        sh("git", "commit", "-m", "init", cwd=root / "a")
        sh("git", "push", "-u", "origin", "main", cwd=root / "a")
        sh("git", "clone", str(root / "remote.git"), str(root / "b"))
        self._config(root / "b")
        self.a, self.b = Hub(root / "a", self.tmp.name), Hub(root / "b", self.tmp.name)
        self.root = root

    def _config(self, path):
        sh("git", "config", "user.email", "t@example.com", cwd=path)
        sh("git", "config", "user.name", "t", cwd=path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_changes_reach_the_other_clone(self):
        tid = self.a.new()
        self.a.run("ready", tid)
        self.assertIn("claimed", self.b.run("claim"))  # b pulls first, so it sees the ready task
        sh("git", "pull", "--quiet", cwd=self.a.path)
        self.assertEqual(self.a.status(tid), "in_progress")

    def test_report_edits_survive_sync(self):
        tid = self.a.new()
        self.a.run("ready", tid)
        self.b.run("claim")
        self.b.fill_report(tid)  # uncommitted edit while another write lands on the remote
        self.a.new("other")
        self.b.run("review", tid)
        sh("git", "pull", "--quiet", cwd=self.a.path)
        self.assertEqual(self.a.status(tid), "review")
        self.assertIn("Changed the redirect.", self.a.run("show", tid))

    def _race(self, script):
        """Run `script` in clone a while b is inside its commit (after b pulled, before b pushes)."""
        hook = self.b.path / ".git" / "hooks" / "pre-commit"
        hook.write_text(f"#!/bin/sh\nrm \"$0\"\ncd {self.a.path} && {script} >/dev/null\n")
        hook.chmod(0o755)

    def test_same_task_claimed_twice_has_one_winner(self):
        tid = self.a.new()
        self.a.run("ready", tid)
        self._race(f"TASK_HUB_DIR={self.a.path} HOME={self.tmp.name} \"{BIN}\" claim")
        out = self.b.run("claim", code=1)
        self.assertIn("changed by someone else", out)
        self.assertTrue((self.b.path / ".rejected").is_dir())
        sh("git", "pull", "--quiet", cwd=self.a.path)
        self.assertEqual(self.a.status(tid), "in_progress")
        self.assertEqual(self.b.status(tid), "in_progress")  # b was reset to the winner's state

    def test_limit_holds_when_two_runners_claim_different_tasks(self):
        ids = [self.a.new(f"t{i}") for i in range(4)]
        for tid in ids:
            self.a.run("ready", tid, "--no-dispatch")
        self.a.run("claim")
        self.a.run("claim")  # 2 running, 1 slot left
        # while b claims ids[2], a grabs ids[3] directly -> 4 running without a git conflict
        y = next((self.a.path / "tasks").glob(f"{int(ids[3]):04d}-*.md"))
        self._race(f"sed -i.bak 's/status: ready/status: in_progress/' {y} && rm {y}.bak"
                   " && git commit -qam grab && git push -q")
        self.assertIn("slots busy", self.b.run("claim"))
        self.assertEqual(self.b.status(ids[2]), "ready")  # b gave its claim back
        running = self.b.run("list", "--status", "in_progress")
        self.assertIn("tasks[3]", running)

if __name__ == "__main__":
    unittest.main()
