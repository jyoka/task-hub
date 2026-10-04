"""Windows: black-box runs of bin/task on the paths only Windows takes (docs/windows.md). Skipped elsewhere.

The fakes are test_task.py's, each behind an .exe launcher as pip makes them for console scripts: Windows runs
no #! line, and a batch file cuts a prompt of several lines at the first line break. They lock with a small
fcntl stand-in (msvcrt), so they run unchanged.
TASK_TEST_WINDOWS_INSTALL=1 (CI only) also runs windows/install.ps1 for real: it installs into this user's
profile, PATH and Task Scheduler, since the scheduled watch runs as the user, whatever a test sets.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zipfile
from pathlib import Path

WINDOWS = os.name == "nt"
FCNTL = r'''
import msvcrt, time
LOCK_EX = 2
def flock(f, op):  # a byte far past the end: another opener's truncation never touches it
    while True:
        try:
            f.seek(1 << 30)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.01)
'''
if WINDOWS:  # test_task imports fcntl, which Windows lacks
    sys.modules["fcntl"] = types.ModuleType("fcntl")
    exec(FCNTL, sys.modules["fcntl"].__dict__)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_task import BIN, FAKE_AGENT, FAKE_GH, STATUS_OPTIONS  # noqa: E402

REPO = BIN.parent.parent


def write_exe(path, script):
    """A console program running `script` with this Python: pip's launcher, a #! line, then a zip with __main__.py."""
    import pip._vendor.distlib as distlib
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("__main__.py", script)
    path.write_bytes((Path(distlib.__file__).parent / "t64.exe").read_bytes()
                     + f'#!"{sys.executable}"\n'.encode() + archive.getvalue())


@unittest.skipUnless(WINDOWS, "Windows only")
class WindowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = self.root = Path(self.tmp.name)
        self.db = root / "gh.json"
        self.db.write_text(json.dumps({
            "issues_repo": "jyoka/tasks", "issues": {}, "items": {}, "prs": {},
            "fields": [{"id": "F_status", "name": "Status", "type": "ProjectV2SingleSelectField",
                        "dataType": "SINGLE_SELECT",
                        "options": [{"id": f"O_{i}", "name": n} for i, n in enumerate(STATUS_OPTIONS)]},
                       {"id": "F_title", "name": "Title", "type": "ProjectV2Field", "dataType": "TITLE"},
                       {"id": "F_repo", "name": "Target repo", "type": "ProjectV2Field", "dataType": "TEXT"},
                       {"id": "F_agent", "name": "Agent", "type": "ProjectV2Field", "dataType": "TEXT"},
                       {"id": "F_base", "name": "Base branch", "type": "ProjectV2Field", "dataType": "TEXT"}]}))
        fakes = root / "fakes"
        fakes.mkdir()
        (fakes / "fcntl.py").write_text(FCNTL)
        write_exe(root / "gh.exe", FAKE_GH)
        write_exe(root / "agent.exe", FAKE_AGENT)
        self.calls = root / "agent-calls.txt"
        git_id = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
                  "GIT_COMMITTER_EMAIL": "t@e"}
        self.env = {**os.environ, **git_id, "HOME": str(root), "USERPROFILE": str(root), "TASK_HERDR": "0",
                    "TASK_GH": str(root / "gh.exe"), "TASK_TEST_GH_DB": str(self.db),
                    "TASK_TEST_AGENT_CALLS": str(self.calls), "PYTHONPATH": str(fakes),
                    "TASK_CLONE_URL": (root / "origins").as_uri() + "/{repo}.git",
                    "TASK_NO_UPDATE_NOTIFIER": "1"}  # the checkout's origin is GitHub: no update check in the tests
        self.env.pop("PYTHONUTF8", None)  # bin/task must turn UTF-8 mode on itself
        self.write_config()
        self.origin("jyoka/app")

    def tearDown(self):
        runs = self.root / ".local/state/task-hub/runs"
        for f in runs.glob("*.json") if runs.exists() else []:
            pid = json.loads(f.read_text()).get("pid")
            if pid:
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        time.sleep(0.5)  # the killed processes let go of their files
        self.tmp.cleanup()

    # --- helpers ---

    def write_config(self, extra="", agent=None):
        # forward slashes: shlex reads a backslash as an escape (docs/windows.md)
        agent = agent or f"{(self.root / 'agent.exe').as_posix()} {{prompt}}"
        cfg = self.root / ".config" / "task-hub" / "config.ini"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("[board]\nproject = jyoka/2\nissues = jyoka/tasks\n\n[runner]\nagent = fake\n\n"
                       f"[agents]\nfake = {agent}\n" + extra, encoding="utf-8")

    def origin(self, repo):
        bare = self.root / "origins" / f"{repo}.git"
        seed = self.root / "seed"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
        (seed / "README.md").write_text("app\n")
        subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-qm", "init"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"], check=True, capture_output=True)

    def task(self, *args, code=0):
        r = subprocess.run([sys.executable, str(BIN), *args], env=self.env, capture_output=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, code, f"{r.stdout}{r.stderr}")
        return r.stdout

    def new(self, mode="ok", title="Add hello"):
        out = self.task("new", "--title", title, "--repo", "jyoka/app", "--goal", f"Say hello.\nMODE:{mode}")
        return re.search(r"id: (\d+)", out).group(1)

    def gh(self):
        return json.loads(self.db.read_text(encoding="utf-8"))

    def status(self, tid):
        return self.gh()["items"][f"PVTI_{tid}"]["values"].get("status")

    def wait(self, tid, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if self.status(tid) != "In progress":
                return self.status(tid)
            time.sleep(0.3)
        self.fail(f"task {tid} still In progress; log:\n{self.task('log', tid, '--full')}")

    def agent_calls(self):
        return [eval(line) for line in self.calls.read_text(encoding="utf-8").splitlines()] \
            if self.calls.exists() else []

    def run_state(self, tid):
        return json.loads((self.root / ".local/state/task-hub/runs" / f"{tid}.json").read_text())

    def branch_file(self, tid, name):
        bare = self.root / "origins" / "jyoka/app.git"
        return subprocess.run(["git", "-C", str(bare), "show", f"task/{tid}:{name}"], capture_output=True,
                              encoding="utf-8").stdout.replace("\r\n", "\n")  # whatever core.autocrlf says

    # --- tests ---

    def test_a_task_in_japanese_runs_to_a_pr(self):
        tid = self.new(title="挨拶を追加する")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        prompt = self.agent_calls()[0]["prompt"]
        self.assertIn("Task 1: 挨拶を追加する", prompt)  # through the code page and the command line
        self.assertIn("Say hello.\nMODE:ok", prompt)  # every line of it, not cut at the first
        self.assertEqual(self.branch_file(tid, "hello.txt"), "hello from mode ok\n")
        self.assertIn("挨拶を追加する", self.task("list"))

    def test_a_running_task_is_alive_until_it_is_killed(self):
        tid = self.new("slow")
        self.task("start", tid)
        end = time.time() + 30
        while not self.run_state(tid).get("pid") and time.time() < end:
            time.sleep(0.2)
        self.env["TASK_WATCH_ONCE"] = "1"
        self.task("watch")  # alive: the watch leaves it In progress
        self.assertEqual(self.status(tid), "In progress")
        subprocess.run(["taskkill", "/PID", self.run_state(tid)["pid"], "/T", "/F"], capture_output=True)
        time.sleep(1)
        self.task("watch")  # gone: blocked as stopped
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn("the run stopped unexpectedly", self.gh()["issues"][tid]["comments"][-1]["body"])

    def test_a_config_from_notepad_or_powershell(self):
        cfg = self.root / ".config" / "task-hub" / "config.ini"
        cfg.write_text("; メモ帳で保存\n" + cfg.read_text(encoding="utf-8"), encoding="utf-8-sig")  # with a BOM
        self.new()
        cfg.write_text(cfg.read_text(encoding="utf-8-sig"), encoding="utf-16")  # what `>` writes in PowerShell 5.1
        self.assertIn("is not saved as UTF-8", self.task("list", code=1))

    def test_a_leading_env_sets_variables(self):
        # the built-in claude starts with `env NAME=value ...`; Windows has no env program
        self.write_config(agent=f"env FAKE_AGENT_KEY=k1 {(self.root / 'agent.exe').as_posix()} {{prompt}}")
        tid = self.new()
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertEqual(self.agent_calls()[0]["key"], "k1")

    def npm_shim(self, target):
        """What npm's cmd-shim writes for a package's bin: node with its script, or a native program as it is."""
        bindir = self.root / "npm"
        (bindir / "node_modules/fake/bin").mkdir(parents=True, exist_ok=True)
        run = '"%_prog%"  "%dp0%\\node_modules\\fake\\bin\\' + target + '" %*' if target.endswith(".js") \
            else '"%dp0%\\node_modules\\fake\\bin\\' + target + '"   %*'
        (bindir / "fake.cmd").write_text(
            '@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n'
            'IF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n) ELSE (\r\n  SET "_prog=node"\r\n'
            '  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\nendLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & '
            + run + '\r\n')
        self.env["PATH"] = f"{bindir};{self.env['PATH']}"
        return bindir / "node_modules/fake/bin" / target

    def test_an_npm_cmd_shim_gets_the_whole_prompt(self):
        self.npm_shim("fake.js").write_text(
            "const r = require('child_process').spawnSync(process.argv[2], process.argv.slice(3), {stdio: 'inherit'});\n"
            "process.exit(r.status);\n")
        self.write_config(agent=f"fake {(self.root / 'agent.exe').as_posix()} {{prompt}}")
        tid = self.new()
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertIn("Say hello.\nMODE:ok", self.agent_calls()[0]["prompt"])

    def test_an_npm_cmd_shim_of_a_native_program_runs_it_without_node(self):
        shutil.copy(self.root / "agent.exe", self.npm_shim("agent.exe"))
        self.write_config(agent="fake {prompt}")
        tid = self.new()
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertIn("Say hello.\nMODE:ok", self.agent_calls()[0]["prompt"])

    def test_setup_runs_in_powershell(self):
        self.write_config("\n[setup]\njyoka/app = New-Item -ItemType Directory .venv | Out-Null\n"
                          "  Set-Content .venv/.gitignore '*'\n  Set-Content .venv/marker ready\n")
        tid = self.new("needsetup")
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "In review")
        self.assertEqual(self.branch_file(tid, "hello.txt"), "setup seen: ready\n")

    def test_failing_setup_blocks(self):
        self.write_config("\n[setup]\njyoka/app = git --no-such-flag\n")
        tid = self.new()
        self.task("start", tid)
        self.assertEqual(self.wait(tid), "Blocked")
        self.assertEqual(self.agent_calls(), [])
        self.assertIn("setup failed (exit 129)", self.gh()["issues"][tid]["comments"][-1]["body"])


@unittest.skipUnless(WINDOWS and os.environ.get("TASK_TEST_WINDOWS_INSTALL") == "1",
                     "changes the user PATH and Task Scheduler: CI only")
class InstallTest(unittest.TestCase):
    def ps(self, *args):
        return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               str(REPO / "windows" / "install.ps1"), *args],
                              capture_output=True, encoding="utf-8", errors="replace")

    def setUp(self):
        self.home = Path.home()
        self.addCleanup(self.ps, "-Uninstall")

    def watch_loops(self):
        ps = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                             "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and "
                             "$_.CommandLine -like '*task-watch.ps1*' } "
                             "| ForEach-Object { $_.ProcessId }"], capture_output=True, text=True).stdout
        return [int(x) for x in ps.split()]

    def test_install_watch_and_uninstall(self):
        r = self.ps("-Watch", "-From", str(REPO))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("registered and started the scheduled task", r.stdout)  # not the Startup folder fallback
        shim = self.home / ".local/bin/task.cmd"
        self.assertTrue((self.home / ".local/lib/task-hub/bin/task").exists())
        version = subprocess.run([str(shim), "--version"], capture_output=True, text=True)
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        bash = Path(shutil.which("git")).resolve().parent.parent / "bin" / "bash.exe"  # Git Bash, as Claude Code uses
        version = subprocess.run([str(bash), "-c", "task --version"], capture_output=True, text=True,
                                 env={**os.environ, "PATH": f"{self.home / '.local/bin'};{os.environ['PATH']}"})
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        # an agent whose prompt names task-watch.ps1 must outlive -Uninstall
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "see task-watch.ps1"])
        self.addCleanup(bystander.wait)
        self.addCleanup(bystander.kill)  # cleanups run last first: kill, then wait
        # with no config the watch fails and says so in its log, then waits to try again: it is running
        log = self.home / ".local/state/task-hub/watch.log"
        end = time.time() + 60
        while time.time() < end and "the board is not configured" not in (log.read_text(errors="replace")
                                                                        if log.exists() else ""):
            time.sleep(1)
        self.assertIn("the board is not configured", log.read_text(errors="replace"))
        self.assertTrue(set(self.watch_loops()) - {bystander.pid})  # the loop itself
        r = self.ps("-Uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(shim.exists())
        time.sleep(1)
        self.assertEqual(self.watch_loops(), [bystander.pid])
        self.assertIsNone(bystander.poll())
        tasks = subprocess.run(["schtasks", "/Query", "/TN", "task-hub watch"], capture_output=True)
        self.assertNotEqual(tasks.returncode, 0)


if __name__ == "__main__":
    unittest.main()
