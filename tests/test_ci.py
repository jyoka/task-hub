"""What CI runs for a change (tests/ci/scope.py, CONTRIBUTING.md テスト): only the docs tests for docs alone.

- A change of docs alone (Markdown at the top, docs/, site/, assets/) is docs only; one more file of code, tests,
  workflows, or Markdown the agents run on (worker/, skills/, ...) makes it a change for all the tests.
- No base (a push to main, a run by hand) and no change run all the tests.
- The docs tests named for tests/run.py are all there.
- The workflows keep the jobs the branch rules and the merge queue wait for (macos test, windows test and
  standard-user): never skipped as a whole, never left out by a path filter, and only the docs tests step runs on
  docs alone.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCOPE = ROOT / "tests" / "ci" / "scope.py"
WORKFLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(SCOPE.parent))
import scope  # noqa: E402


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


def jobs(workflow):
    """{job name: its lines} of a workflow, read by indentation (no YAML parser in the standard library)."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8").split("\njobs:\n", 1)[1]
    found, name = {}, None
    for line in text.splitlines():
        if m := re.match(r"^  ([\w-]+):\s*(#.*)?$", line):
            name = m[1]
            found[name] = []
        elif name:
            found[name].append(line)
    return found


class ScopeTest(unittest.TestCase):

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        git(self.repo, "init", "-q", "-b", "main")
        self.write("README.md", "app\n", "docs/setup.md", "setup\n", "bin/task_hub.py", "print()\n",
                   "skills/task/SKILL.md", "skill\n")
        git(self.repo, "checkout", "-q", "-b", "task/1")

    def write(self, *pairs, message="change"):
        for path, text in zip(pairs[::2], pairs[1::2]):
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", message)

    def scope(self, *args, output=None):
        env = {**os.environ, "GITHUB_OUTPUT": str(output or "")}
        r = subprocess.run([sys.executable, str(SCOPE), *args], cwd=self.repo, capture_output=True, text=True,
                           encoding="utf-8", env=env)
        return r.returncode, r.stdout, r.stderr

    def test_docs_alone_run_only_the_docs_tests(self):
        self.write("README.md", "app, better\n", "docs/日本語.md", "新しい\n", "site/index.html", "<p>\n",
                   "assets/media/a.png", "png", "CONTRIBUTING.md", "c\n")
        output = self.repo.parent / f"{self.repo.name}-output"
        self.addCleanup(output.unlink, missing_ok=True)
        output.write_text("before=1\n")
        self.assertEqual(self.scope("main", output=output),
                         (0, "docs_only=true  # 5 file(s) changed, all docs: only the docs tests\n", ""))
        self.assertEqual(output.read_bytes(), b"before=1\ndocs_only=true\n")  # for steps.scope.outputs, no \r

    def test_one_file_besides_the_docs_runs_all_the_tests(self):
        for path in ("bin/task_hub.py", "tests/test_x.py", ".github/workflows/macos.yml", "skills/task/SKILL.md",
                     "worker/PROMPT.md", ".kiro/steering/setup.md", "kiro/board-extension/README.md", "LICENSE"):
            with self.subTest(path):
                git(self.repo, "reset", "-q", "--hard", "main")
                self.write("README.md", "app, better\n", path, "changed\n")
                code, out, _ = self.scope("main")
                self.assertEqual(code, 0)
                self.assertTrue(out.startswith("docs_only=false  # 2 file(s) changed, not only docs "
                                               f"({path}): all the tests"), out)

    def test_a_file_moved_out_of_the_docs_or_deleted_counts_on_both_sides(self):
        git(self.repo, "mv", "docs/setup.md", "bin/setup.md")
        git(self.repo, "commit", "-qm", "moved")
        self.assertIn("docs_only=false  # 2 file(s) changed, not only docs (bin/setup.md)", self.scope("main")[1])
        git(self.repo, "reset", "-q", "--hard", "main")
        git(self.repo, "rm", "-q", "bin/task_hub.py")
        git(self.repo, "commit", "-qm", "deleted")
        self.assertIn("not only docs (bin/task_hub.py)", self.scope("main")[1])

    def test_only_the_branchs_own_changes_count_after_main_is_merged_in(self):
        # the merge queue merges main into the PR's branch: main's code changes are not the PR's
        self.write("docs/setup.md", "setup, better\n")
        git(self.repo, "checkout", "-q", "main")
        self.write("bin/task_hub.py", "print(1)\n", message="main moved")
        git(self.repo, "checkout", "-q", "task/1")
        git(self.repo, "merge", "-q", "--no-edit", "main")
        self.assertEqual(self.scope("main")[1], "docs_only=true  # 1 file(s) changed, all docs: only the docs tests\n")

    def test_no_base_or_no_change_runs_all_the_tests(self):
        self.assertEqual(self.scope("")[1], "docs_only=false  # no base to compare with (a push to main or a run by "
                                            "hand): all the tests\n")
        self.assertEqual(self.scope()[1].split("  # ")[0], "docs_only=false")
        self.assertEqual(self.scope("main")[1], "docs_only=false  # no change since main: all the tests\n")

    def test_a_base_git_cannot_read_fails_the_step(self):
        code, out, err = self.scope("origin/nothing")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("git diff origin/nothing...HEAD failed", err)

    def test_the_docs_tests_are_all_there(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import run
        ids = list(run.ids(unittest.defaultTestLoader.discover(str(ROOT / "tests"))))
        for name in scope.DOCS_TESTS:
            with self.subTest(name):
                self.assertTrue([i for i in ids if name in i])
        code, out, _ = self.scope("--tests")
        self.assertEqual((code, out.split()), (0, list(scope.DOCS_TESTS)))


class WorkflowTest(unittest.TestCase):
    """The checks the branch rules and `task merge` wait for report on every PR, docs only or not."""
    REQUIRED = {"macos.yml": ["test"], "windows.yml": ["test", "standard-user"]}

    def test_no_path_filter_leaves_a_workflow_out(self):
        for workflow in self.REQUIRED:
            with self.subTest(workflow):
                on = (WORKFLOWS / workflow).read_text(encoding="utf-8").split("\njobs:\n", 1)[0]
                self.assertNotRegex(on, r"\bpaths(-ignore)?:")

    def test_the_required_jobs_decide_first_and_skip_only_steps(self):
        for workflow, names in self.REQUIRED.items():
            found = jobs(workflow)
            for name in names:
                with self.subTest(f"{workflow} {name}"):
                    lines = found[name]
                    # never the whole job: a job skipped by its `if:` or by a failed job it needs counts as passed
                    self.assertFalse([line for line in lines if re.match(r"^    (if|needs):", line)])
                    steps = "\n".join(lines).split("\n      - ")
                    first = next(i for i, s in enumerate(steps) if "id: scope" in s)
                    self.assertIn("tests/ci/scope.py \"$CI_DIFF_BASE\"", steps[first])
                    self.assertFalse([s for s in steps[:first] if "if:" in s or "run:" in s])
                    conditions = re.findall(r"^\s*(?:- )?if: (.*)$", "\n".join(lines), re.M)
                    self.assertTrue(conditions)
                    # only the docs tests step is for docs alone: on any other change every step runs as before
                    only_docs = [c for c in conditions if "docs_only" in c
                                 and c != "steps.scope.outputs.docs_only != 'true'"]
                    self.assertEqual(only_docs, ["steps.scope.outputs.docs_only == 'true'"] if workflow == "macos.yml"
                                     else [])

    def test_the_docs_tests_step_runs_the_docs_tests(self):
        steps = "\n".join(jobs("macos.yml")["test"]).split("\n      - ")
        [docs] = [s for s in steps if "docs_only == 'true'" in s]
        self.assertIn("names=$(python3 tests/ci/scope.py --tests)", docs)
        self.assertIn("python3 tests/run.py -j 4 $names", docs)

    def test_a_push_to_main_and_a_run_by_hand_have_no_base(self):
        macos = "\n".join(jobs("macos.yml")["test"])
        self.assertIn("CI_DIFF_BASE: ${{ github.event.pull_request.base.sha }}\n", macos)  # empty on a push to main
        windows = jobs("windows.yml")
        for name in ("test", "standard-user"):
            with self.subTest(name):
                self.assertIn("CI_DIFF_BASE: ${{ github.event_name == 'push' && startsWith(github.ref, 'refs/heads/') "
                              "&& github.ref_name != github.event.repository.default_branch && "
                              "format('origin/{0}', github.event.repository.default_branch) || '' }}\n",
                              "\n".join(windows[name]))


if __name__ == "__main__":
    unittest.main()
