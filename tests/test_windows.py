"""Windows: black-box runs of bin/task on the paths only Windows takes (docs/windows.md). Skipped elsewhere.

The fakes are test_task.py's, each behind an .exe launcher as pip makes them for console scripts: Windows runs
no #! line, and a batch file cuts a prompt of several lines at the first line break. They lock with a small
fcntl stand-in (msvcrt), so they run unchanged.
SetupTest runs windows/install.ps1's stages in a temporary user folder, with GitHub Releases a local server and the
user's and machine's PATH in test keys under HKCU (TASK_INSTALL_USER_ENV, TASK_INSTALL_MACHINE_ENV).
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
import threading
import time
import types
import unittest
import zipfile
from pathlib import Path

WINDOWS = os.name == "nt"
FCNTL = r'''
import msvcrt, time
LOCK_EX, LOCK_UN = 2, 8
def flock(f, op):  # a byte far past the end: another opener's truncation never touches it
    while True:
        try:
            f.seek(1 << 30)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK if op & LOCK_UN else msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.01)
'''
if WINDOWS:  # test_task imports fcntl, which Windows lacks
    sys.modules["fcntl"] = types.ModuleType("fcntl")
    exec(FCNTL, sys.modules["fcntl"].__dict__)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_bench  # noqa: E402
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


class Job:
    """A Windows job object that ends its processes when closed, and lets them break away, as Task Scheduler's."""
    KILL_ON_JOB_CLOSE, BREAKAWAY_OK, SILENT_BREAKAWAY_OK = 0x2000, 0x800, 0x1000
    EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("per_process_user_time", ctypes.c_int64), ("per_job_user_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                        ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority_class", wintypes.DWORD),
                        ("scheduling_class", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                        ("peak_job_memory", ctypes.c_size_t)]

        self.Extended = Extended
        k = self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                ctypes.c_void_p]
        k.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = k.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = self.KILL_ON_JOB_CLOSE | self.BREAKAWAY_OK
        self.check(self.handle and k.SetInformationJobObject(self.handle, self.EXTENDED_LIMIT_INFORMATION,
                                                             ctypes.byref(info), ctypes.sizeof(info)))

    def check(self, ok):
        if not ok:
            import ctypes
            raise OSError(f"job object call failed (Windows error {ctypes.get_last_error()})")

    def breakaway_possible(self):
        """False when this process is already in a job that keeps its children in: they could not leave ours."""
        import ctypes
        from ctypes import wintypes
        k, in_job = self.kernel32, wintypes.BOOL()
        self.check(k.IsProcessInJob(k.GetCurrentProcess(), None, ctypes.byref(in_job)))
        if not in_job:
            return True
        info = self.Extended()
        self.check(k.QueryInformationJobObject(None, self.EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                               ctypes.sizeof(info), None))
        return bool(info.basic.flags & (self.BREAKAWAY_OK | self.SILENT_BREAKAWAY_OK))

    def add(self, proc):
        self.check(self.kernel32.AssignProcessToJobObject(self.handle, int(proc._handle)))

    def close(self):
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


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
        """The fake GitHub, read under the fake gh's lock: Windows refuses to replace a file another process has
        open, so a read without it could make a fake gh's rename fail, and the run that called it go Blocked."""
        import fcntl  # the msvcrt stand-in above
        with open(f"{self.db}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return json.loads(self.db.read_text(encoding="utf-8"))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def status(self, tid):
        return self.gh()["items"][f"PVTI_{tid}"]["values"].get("status")

    def wait(self, tid, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if self.status(tid) != "In progress":
                return self.status(tid)
            time.sleep(0.3)
        self.fail(f"task {tid} still In progress; log:\n{self.task('log', tid, '--full')}")

    def finish(self, tid, want, timeout=60):
        """Wait for the run to end on the card `want`; else fail with the run's last comment and its log."""
        got = self.wait(tid, timeout)
        if got != want:
            comments = self.gh()["issues"][tid]["comments"]
            self.fail(f"task {tid} went {got}, not {want}\nlast comment: "
                      f"{comments[-1]['body'] if comments else '(none)'}\nlog:\n{self.task('log', tid, '--full')}")

    def agent_calls(self):
        return [eval(line) for line in self.calls.read_text(encoding="utf-8").splitlines()] \
            if self.calls.exists() else []

    def started(self, tid):
        """The pid of the task's run, once the run has recorded it."""
        end = time.time() + 30
        while not self.run_state(tid).get("pid"):
            if time.time() > end:
                self.fail(f"task {tid}'s run never recorded its pid; log:\n{self.task('log', tid, '--full')}")
            time.sleep(0.2)
        return self.run_state(tid)["pid"]

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
        self.finish(tid, "In review")
        prompt = self.agent_calls()[0]["prompt"]
        self.assertIn("Task 1: 挨拶を追加する", prompt)  # through the code page and the command line
        self.assertIn("Say hello.\nMODE:ok", prompt)  # every line of it, not cut at the first
        self.assertEqual(self.branch_file(tid, "hello.txt"), "hello from mode ok\n")
        self.assertIn("挨拶を追加する", self.task("list"))

    def test_a_running_task_is_alive_until_it_is_killed(self):
        tid = self.new("slow")
        self.task("start", tid)
        self.started(tid)
        self.env["TASK_WATCH_ONCE"] = "1"
        self.task("watch")  # alive: the watch leaves it In progress
        self.assertEqual(self.status(tid), "In progress")
        subprocess.run(["taskkill", "/PID", self.run_state(tid)["pid"], "/T", "/F"], capture_output=True)
        time.sleep(1)
        self.task("watch")  # gone: blocked as stopped
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn("the run stopped unexpectedly", self.gh()["issues"][tid]["comments"][-1]["body"])

    def test_a_pid_handed_to_another_process_is_not_the_run(self):
        # Windows hands out pids again soon: the watch must not take another process for the run, even one whose
        # command line says `_run 1` somewhere, as an agent's prompt can
        tid = self.new("slow")
        self.task("start", tid)
        pid = self.started(tid)
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", f"_run {tid} in a prompt"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)  # cleanups run last first: kill, then wait
        state = self.root / ".local/state/task-hub/runs" / f"{tid}.json"
        state.write_text(json.dumps({**self.run_state(tid), "pid": str(other.pid)}))
        self.env["TASK_WATCH_ONCE"] = "1"
        self.task("watch")
        self.assertEqual(self.status(tid), "Blocked")
        self.assertIn("the run stopped unexpectedly", self.gh()["issues"][tid]["comments"][-1]["body"])
        self.assertIsNone(other.poll())  # and left alone

    def test_a_run_outlives_the_job_of_the_watch_that_started_it(self):
        # Task Scheduler runs the watch in a job and ends what is left in it when the task stops (install.ps1
        # -Uninstall, -Watch again, signing out): the run breaks away from it and goes on
        job = Job()
        if not job.breakaway_possible():
            self.skipTest("this test runs in a job that allows no breakaway")
        tid = self.new("slow")
        holder = subprocess.Popen(  # waits until it is in the job, starts the task, says so, then stays in the job
            [sys.executable, "-c", "import subprocess, sys, time; sys.stdin.readline(); "
             "print(subprocess.run(sys.argv[1:], stdin=subprocess.DEVNULL, capture_output=True).returncode, "
             "flush=True); time.sleep(60)", sys.executable, str(BIN), "start", tid],
            env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.stdin.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)  # cleanups run last first: kill, wait, then close its pipes
        job.add(holder)
        holder.stdin.write("go\n")
        holder.stdin.flush()
        self.assertEqual(holder.stdout.readline().strip(), "0")
        self.started(tid)
        job.close()  # what stopping the scheduled task does
        holder.wait(timeout=10)  # the job did end what stayed in it
        time.sleep(1)
        self.env["TASK_WATCH_ONCE"] = "1"
        self.task("watch")  # the run is alive: still In progress, not Blocked as stopped
        self.assertEqual(self.status(tid), "In progress")

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
        self.finish(tid, "In review")
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

    @unittest.skipUnless(shutil.which("node"), "needs Node.js, as every agent installed with npm does")
    def test_an_npm_cmd_shim_gets_the_whole_prompt(self):
        self.npm_shim("fake.js").write_text(
            "const r = require('child_process').spawnSync(process.argv[2], process.argv.slice(3), {stdio: 'inherit'});\n"
            "process.exit(r.status);\n")
        self.write_config(agent=f"fake {(self.root / 'agent.exe').as_posix()} {{prompt}}")
        tid = self.new()
        self.task("start", tid)
        self.finish(tid, "In review")
        self.assertIn("Say hello.\nMODE:ok", self.agent_calls()[0]["prompt"])

    def test_an_npm_cmd_shim_of_a_native_program_runs_it_without_node(self):
        shutil.copy(self.root / "agent.exe", self.npm_shim("agent.exe"))
        self.write_config(agent="fake {prompt}")
        tid = self.new()
        self.task("start", tid)
        self.finish(tid, "In review")
        self.assertIn("Say hello.\nMODE:ok", self.agent_calls()[0]["prompt"])

    def test_an_npm_cmd_shim_runs_its_script_with_the_node_beside_it(self):
        # npm puts node.exe next to the shims when Node.js is installed there: that one, not whatever PATH finds
        script = self.npm_shim("fake.js")
        script.write_text("// run by the node.exe beside the shim\n")
        seen = self.root / "node-script.txt"
        write_exe(self.root / "npm" / "node.exe",  # a stand-in node: notes its script, then runs the rest
                  f"import subprocess, sys\nopen({str(seen)!r}, 'w').write(sys.argv[1])\n"
                  "sys.exit(subprocess.run(sys.argv[2:]).returncode)\n")
        self.write_config(agent=f"fake {(self.root / 'agent.exe').as_posix()} {{prompt}}")
        tid = self.new()
        self.task("start", tid)
        self.finish(tid, "In review")
        self.assertEqual(Path(seen.read_text()), script)
        self.assertIn("Say hello.\nMODE:ok", self.agent_calls()[0]["prompt"])

    def test_a_batch_file_agent_blocks_and_says_what_to_point_at(self):
        # not an npm shim: there is no program in it for task-hub to run instead, and cmd would cut the prompt
        (self.root / "agent.cmd").write_text(f'@"{self.root / "agent.exe"}" %1\r\n')
        self.write_config(agent=f"{(self.root / 'agent.cmd').as_posix()} {{prompt}}")
        tid = self.new()
        self.task("start", tid)
        self.finish(tid, "Blocked")
        self.assertEqual(self.agent_calls(), [])
        self.assertIn("is a batch file, which cannot take a prompt of several lines", self.task("log", tid, "--full"))

    def test_a_goal_too_long_for_a_command_line_blocks_and_says_so(self):
        goal = self.root / "goal.md"
        goal.write_text("Say hello.\nMODE:ok\n" + "Keep every word of this. " * 1500)  # 37,500 characters
        out = self.task("new", "--title", "Long", "--repo", "jyoka/app", "--goal-file", str(goal))
        tid = re.search(r"id: (\d+)", out).group(1)
        self.task("start", tid)
        self.finish(tid, "Blocked")
        log = self.task("log", tid, "--full")
        self.assertIn("agent cannot run: its command line is over Windows' 32,767 characters", log)
        self.assertNotIn("agent not found", log)  # what Windows says, and the wrong lead for the human

    def test_an_env_destination_with_backslashes_is_never_committed(self):
        # `/voice\.env` in info/exclude is voice.env to git, not voice/.env: the secret went into the PR
        voice = self.root / "co" / "voice.env"
        voice.parent.mkdir()
        voice.write_text("VOICE=2\n")
        self.write_config(f"\n[env]\njyoka/app = {voice.as_posix()} -> voice\\.env\n")
        tid = self.new("env")
        self.task("start", tid)
        self.finish(tid, "In review")
        self.assertEqual(self.branch_file(tid, "hello.txt"), "key seen: VOICE=2\n")
        self.assertEqual(self.branch_file(tid, "voice/.env"), "")  # not on the branch

    def test_setup_runs_in_powershell(self):
        self.write_config("\n[setup]\njyoka/app = New-Item -ItemType Directory .venv | Out-Null\n"
                          "  Set-Content .venv/.gitignore '*'\n  Set-Content .venv/marker ready\n")
        tid = self.new("needsetup")
        self.task("start", tid)
        self.finish(tid, "In review")
        self.assertEqual(self.branch_file(tid, "hello.txt"), "setup seen: ready\n")

    def test_failing_setup_blocks(self):
        self.write_config("\n[setup]\njyoka/app = git --no-such-flag\n")
        tid = self.new()
        self.task("start", tid)
        self.finish(tid, "Blocked")
        self.assertEqual(self.agent_calls(), [])
        self.assertIn("setup failed (exit 129)", self.gh()["issues"][tid]["comments"][-1]["body"])


@unittest.skipUnless(WINDOWS, "Windows only")
class InstallBoardTest(unittest.TestCase):
    """kiro/install-board, the board and config.ini stages, as windows/install.ps1 runs it: GitHub is
    test_install.py's fake gh, `task` is the task.cmd install.ps1 writes, and the user folder has a Japanese name."""

    def setUp(self):
        import test_install
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.home = root / "ユーザー"
        bindir, fakes, self.work = root / "bin", root / "fakes", root / "work"
        for d in (self.home / ".local" / "bin", bindir, fakes, self.work):
            d.mkdir(parents=True)
        (fakes / "fcntl.py").write_text(FCNTL)
        write_exe(bindir / "gh.exe", test_install.fake_gh("2.0.0"))
        self.db = root / "gh.json"
        self.db.write_text(json.dumps({"auth": {"login": "alice", "scopes": "gist, project, read:org, repo"},
                                       "code": "ABCD-1234", "approve": None, "repos": {}, "projects": [],
                                       "calls": []}))
        # as install.ps1 writes it: in the console's code page
        (self.home / ".local" / "bin" / "task.cmd").write_text(
            f'@setlocal\r\n@set PYTHONUTF8=1\r\n@"{sys.executable}" "{BIN}" %*\r\n', encoding="mbcs")
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "PYTHONPATH": str(fakes),
                    "TASK_TEST_GH_DB": str(self.db), "TASK_NO_UPDATE_NOTIFIER": "1"}
        for k in ("PYTHONUTF8", "PYTHONIOENCODING", "TASK_GH"):  # the helper and bin/task must not need them
            self.env.pop(k, None)

    def helper(self, *args):
        return subprocess.run([sys.executable, str(REPO / "kiro" / "install-board"), *map(str, args)],
                              env=self.env, capture_output=True, encoding="utf-8", stdin=subprocess.DEVNULL)

    def test_board_then_config_then_again(self):
        r = self.helper("board", "7. ボード", "alice", self.work)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("7. ボード: 作りました", r.stdout)
        self.assertIn("private の alice/tasks", r.stdout)
        r = self.helper("config", "8. 設定", self.work)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn(r"8. 設定: 作りました(~\.config\task-hub\config.ini。task list で確かめました)", r.stdout)
        config = (self.home / ".config" / "task-hub" / "config.ini").read_text(encoding="utf-8")
        self.assertIn("windows\\install.ps1", config)
        for line in ("project = alice/1", "issues = alice/tasks", "agent = kiro", "kiro = kiro-cli whoami"):
            self.assertIn(line, config)
        self.assertNotIn("[ide]", config)  # `kiro {path}` is the Mac's

        r = self.helper("board", "7. ボード", "alice", self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("7. ボード: 済み", r.stdout)
        r = self.helper("config", "8. 設定", self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("8. 設定: 済み", r.stdout)
        for what in ("board", "config"):
            r = self.helper("check", what)
            self.assertTrue(r.stdout.startswith("ok\t"), r.stdout + r.stderr)

    def test_check_says_what_to_run_on_windows(self):
        r = self.helper("check", "config")
        self.assertTrue(r.stdout.startswith("ng\t"), r.stdout + r.stderr)
        self.assertIn(r"~\.config\task-hub\config.ini がありません", r.stdout)
        self.assertIn("windows\\install.ps1", r.stdout)
        self.assertNotIn("sh kiro/install.sh", r.stdout)


def exe_bytes(script):
    with tempfile.TemporaryDirectory() as d:
        write_exe(Path(d) / "x.exe", script)
        return (Path(d) / "x.exe").read_bytes()


FAKE_UV = r'''
import json, os, sys
log = os.environ["TASK_TEST_UV_LOG"]
a = sys.argv[1:]
with open(log, "a") as f:
    f.write(json.dumps(a) + "\n")
if a == ["python", "install", "3.12"]:
    open(log + ".installed", "w").close()
    sys.exit(0)
if a[:2] == ["python", "find"] and os.environ.get("VIRTUAL_ENV") and "--system" not in a:
    print(os.path.join(os.environ["VIRTUAL_ENV"], "Scripts", "python.exe"))  # as uv does: the active virtualenv's
    sys.exit(0)
if a[:2] == ["python", "find"] and os.path.exists(log + ".installed"):
    print(sys.executable)  # "uv's Python" is this one
    sys.exit(0)
if a == ["python", "uninstall", "3.12"] and os.path.exists(log + ".installed"):
    os.remove(log + ".installed")
    sys.exit(0)
sys.exit(2)
'''
# logged in while the file TASK_TEST_KIRO_LOGGED_IN is there
FAKE_KIRO_CLI = r'''
import os, sys
a = sys.argv[1:]
if a == ["--version"]:
    print("kiro-cli 2.29.1 (fake)")
    sys.exit(0)
if a == ["whoami"]:
    sys.exit(0 if os.path.exists(os.environ["TASK_TEST_KIRO_LOGGED_IN"]) else 1)
sys.exit(2)
'''
# msiexec /a <msi> /qn TARGETDIR=<dir>: the test's "MSI" is a zip
FAKE_MSIEXEC = r'''
import sys, zipfile
a = sys.argv[1:]
zipfile.ZipFile(a[a.index("/a") + 1]).extractall(next(x.split("=", 1)[1] for x in a if x.startswith("TARGETDIR=")))
'''
# opens no window: keeps the login script it was given
FAKE_OPEN_WINDOW = r'''
import os, sys
with open(os.environ["TASK_TEST_WINDOWS"], "a", encoding="utf-8") as f:
    f.write(open(sys.argv[1], encoding="utf-8-sig").read() + "----\n")
'''


def delete_key(path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            subs = []
            while True:
                try:
                    subs.append(winreg.EnumKey(k, len(subs)))
                except OSError:
                    break
        for sub in subs:
            delete_key(rf"{path}\{sub}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


@unittest.skipUnless(WINDOWS and os.environ.get("PROCESSOR_ARCHITECTURE") == "AMD64", "Windows on x64 only")
class SetupTest(unittest.TestCase):
    """windows/install.ps1, stages 1 to 6, as a person with no admin rights runs it: what is missing comes from GitHub
    Releases and Kiro's download server (a local server), checked by its SHA-256, into the user folder, and is
    recorded. GitHub is test_install.py's fake gh; a login opens no window, its script is kept in windows.log."""
    GH_TAG, UV_TAG, GIT_TAG = "v2.0.0", "0.9.0", "v2.56.0.windows.2"
    GH_ZIP, UV_ZIP, GIT_ZIP = "gh_2.0.0_windows_amd64.zip", "uv-x86_64-pc-windows-msvc.zip", "MinGit-2.56.0.2-64-bit.zip"
    KIRO_MSI = "2.29.1/kiro-cli-x86_64-pc-windows-msvc.msi"

    def setUp(self):
        import test_install
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        root = self.root = Path(self.tmp.name)
        # a Japanese name; with a letter no code page has, for the test of what a shortcut (.lnk) keeps
        self.home = root / ("ユーザー\U0001f600" if self._testMethodName.endswith("_no_code_page_has") else "ユーザー")
        self.home.mkdir()
        self.uv_log, self.windows = root / "uv.log", root / "windows.log"
        self.kiro_logged_in = root / "kiro-logged-in"
        fakes, self.kirobin, self.program_files = root / "fakes", root / "kirobin", root / "Program Files"
        for d in (fakes, self.kirobin, self.program_files):
            d.mkdir()
        (fakes / "fcntl.py").write_text(FCNTL)
        write_exe(self.kirobin / "kiro-cli.exe", FAKE_KIRO_CLI)
        write_exe(root / "msiexec.exe", FAKE_MSIEXEC)
        write_exe(root / "open-window.exe", FAKE_OPEN_WINDOW)
        self.db = root / "gh.json"
        self.set_gh_auth(None)
        # task-hub's origin: release tags are added by the tests that want them
        self.origin = root / "task-hub.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(REPO), str(self.origin)], check=True, capture_output=True)

        srv = self.srv = test_install.Releases()
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        gh = test_install.zip_bytes({"LICENSE": "MIT", "bin/gh.exe": exe_bytes(test_install.fake_gh("2.0.0"))})
        uv = test_install.zip_bytes({"uv.exe": exe_bytes(FAKE_UV)})
        git = test_install.zip_bytes({"cmd/git.exe": exe_bytes(
            f"import subprocess, sys\nsys.exit(subprocess.call([{shutil.which('git')!r}, *sys.argv[1:]]))\n")})
        msi = test_install.zip_bytes({"LocalApp/Kiro-Cli/kiro-cli.exe": exe_bytes(FAKE_KIRO_CLI)})
        sha = test_install.sha256
        srv.redirects.update({"/cli/cli/releases/latest": f"/cli/cli/releases/tag/{self.GH_TAG}",
                              "/astral-sh/uv/releases/latest": f"/astral-sh/uv/releases/tag/{self.UV_TAG}",
                              "/git-for-windows/git/releases/latest": f"/git-for-windows/git/releases/tag/{self.GIT_TAG}"})
        srv.files.update({
            f"/cli/cli/releases/download/{self.GH_TAG}/{self.GH_ZIP}": gh,
            f"/cli/cli/releases/download/{self.GH_TAG}/gh_2.0.0_checksums.txt":
                f"{'0' * 64}  gh_2.0.0_windows_arm64.zip\n{sha(gh)}  {self.GH_ZIP}\n".encode(),
            f"/astral-sh/uv/releases/download/{self.UV_TAG}/{self.UV_ZIP}": uv,
            f"/astral-sh/uv/releases/download/{self.UV_TAG}/{self.UV_ZIP}.sha256": f"{sha(uv)}  {self.UV_ZIP}\n".encode(),
            f"/git-for-windows/git/releases/download/{self.GIT_TAG}/{self.GIT_ZIP}": git,
            f"/api/repos/git-for-windows/git/releases/tags/{self.GIT_TAG}": json.dumps(
                {"tag_name": self.GIT_TAG, "body": "",
                 "assets": [{"name": "MinGit-2.56.0.2-arm64.zip", "digest": "sha256:" + "0" * 64},
                            {"name": self.GIT_ZIP, "digest": "sha256:" + sha(git)}]}).encode(),
            f"/kiro/stable/{self.KIRO_MSI}": msi,
            "/kiro/stable/latest/manifest.json": json.dumps({"version": "2.29.1", "packages": [
                {"os": "macos", "kind": "dmg", "fileType": "dmg", "architecture": "universal",
                 "download": "2.29.1/Kiro CLI.dmg", "sha256": "0" * 64},
                {"os": "windows", "kind": "msi", "fileType": "msi", "architecture": "x86_64",
                 "download": self.KIRO_MSI, "sha256": sha(msi)}]}).encode()})
        # this test's "registry": the user's and the machine's environment
        self.reg = rf"Software\task-hub-test\{os.getpid()}-{id(self)}"
        self.addCleanup(delete_key, self.reg)
        system = Path(os.environ["SystemRoot"]) / "System32"
        self.env = {**os.environ, "USERPROFILE": str(self.home), "HOME": str(self.home),
                    "PATH": f"{system};{system / 'WindowsPowerShell' / 'v1.0'}",  # no git, Python, gh or kiro-cli
                    "TASK_INSTALL_GITHUB": srv.url, "TASK_INSTALL_GITHUB_API": srv.url + "/api",
                    "TASK_INSTALL_KIRO_CLI": srv.url + "/kiro", "TASK_INSTALL_MSIEXEC": str(root / "msiexec.exe"),
                    "TASK_INSTALL_PROGRAM_FILES": str(self.program_files),
                    "TASK_INSTALL_OPEN_WINDOW": str(root / "open-window.exe"),
                    "TASK_INSTALL_USER_ENV": self.reg + r"\user", "TASK_INSTALL_MACHINE_ENV": self.reg + r"\machine",
                    "TASK_TEST_UV_LOG": str(self.uv_log), "TASK_TEST_GH_DB": str(self.db),
                    "TASK_TEST_KIRO_LOGGED_IN": str(self.kiro_logged_in), "TASK_TEST_WINDOWS": str(self.windows),
                    "PYTHONPATH": str(fakes), "APPDATA": str(self.home / "AppData" / "Roaming"),  # Kiro's settings.json
                    "TASK_INSTALL_AUTOSTART_DIR": str(root / "autostart")}  # not this PC's Task Scheduler or Startup
        for k in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONHOME", "VIRTUAL_ENV", "GH_TOKEN", "GITHUB_TOKEN",
                  "GIT_CONFIG_GLOBAL"):
            self.env.pop(k, None)
        # Slack triage's key off: tests run side by side, and one key can be registered once (the key's own test
        # turns it on, with a key of its own)
        self.slack_config(enabled=False)
        self.addCleanup(self.stop_hotkeys)

    def slack_config(self, **c):
        f = self.home / ".config/task-hub/slack-triage.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")

    def stop_hotkeys(self):  # this test's programs waiting for a key, whatever the test left
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name = 'powershell.exe'\" | Where-Object { "
                        "$_.CommandLine -and $_.CommandLine.Contains($env:HOTKEY_HOME) } | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                       env={**os.environ, "HOTKEY_HOME": str(self.home)}, capture_output=True)

    def set_path(self, which, *dirs):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{self.reg}\{which}") as k:
            winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(map(str, dirs)))

    def user_path(self):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{self.reg}\user") as k:
            return winreg.QueryValueEx(k, "Path")[0].split(";")

    def set_gh_auth(self, auth):
        self.db.write_text(json.dumps({"auth": auth, "code": "ABCD-1234", "approve": None, "repos": {},
                                       "projects": [], "calls": []}))

    def ready(self):
        """A PC with git, Python and kiro-cli (installed after this window opened), logged in to GitHub and Kiro."""
        self.set_path("machine", Path(shutil.which("git")).parent)
        self.set_path("user", Path(sys.executable).parent, self.kirobin)
        self.set_gh_auth({"login": "alice", "scopes": "gist, project, read:org, repo"})
        self.kiro_logged_in.touch()

    def tag(self, name, rev="HEAD"):
        subprocess.run(["git", "-C", str(self.origin), "tag", name, rev], check=True)

    def install(self, *args, code=0):
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(REPO / "windows" / "install.ps1"), "-From", str(self.origin), *args],
                           env=self.env, capture_output=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def manifest(self):
        return json.loads((self.home / ".local/state/task-hub/install-manifest.json").read_text(encoding="utf-8"))

    def lib_git(self, *args):
        return subprocess.run(["git", "-C", str(self.home / ".local/lib/task-hub"), *args], capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_a_bare_pc_gets_everything_then_nothing_twice(self):
        self.set_gh_auth({"login": "alice", "scopes": "gist, project, read:org, repo"})
        self.kiro_logged_in.touch()
        out = self.install()
        self.assertIn("task-hub をセットアップします(管理者権限は使いません)", out)
        self.assertIn("1. 前提の確認: 入れました(", out)
        self.assertIn(r"git 2.56.0.2(MinGit、~\.local\lib\git)", out)
        self.assertIn("2. Python: 入れました(uv で Python 3.12", out)
        self.assertIn(r"3. gh: 入れました(gh 2.0.0、~\.local\bin\gh.exe)", out)
        self.assertIn(r"4. kiro-cli: 入れました(~\.local\lib\kiro-cli\kiro-cli.exe)", out)
        self.assertIn("5. GitHub のログイン: 設定しました(alice、git も gh のログインを使います)", out)
        self.assertIn("5. kiro-cli のログイン: 済み", out)
        self.assertIn("6. task-hub 本体: 入れました(clone(", out)
        self.assertIn(r"~\.local\bin\task.cmd、~\.local\bin\task、ユーザーの PATH に ~\.local\bin)", out)
        self.assertIn("7. ボード: 作りました(", out)
        self.assertIn(r"8. 設定: 作りました(~\.config\task-hub\config.ini。task list で確かめました)", out)
        self.assertIn(r"9. Kiro との連携: 入れました(~\.kiro\skills\task(ジャンクション)、~\.kiro\skills\chief(ジャンクション)、"
                      r"~\.kiro\steering\task-hub.md(コピー)、~\.kiro\hooks\task-hub-events.json(コピー)、"
                      r"~\.kiro\workflows\task-hub-events.workflow.json(コピー)、"
                      r"~\AppData\Roaming\Kiro\User\settings.json(Workflows を有効に)。Kiro を再起動すると読み込まれます)", out)
        self.assertIn("10. 常駐: 飛ばしました(", out)
        self.assertIn(r"11. Slackトリアージ: 入れました(~\.local\bin\slack-triage.cmd、サインインのたびに起動キーを待つ常駐。"
                      "止めています(slack-triage off)", out)
        self.assertIn("\n診断:\n○ 1. 前提の確認: ", out)
        self.assertNotIn("× ", out)
        self.assertEqual(out.splitlines()[-2:], ["ここまで終わりました。", "次にすること: Kiro を再起動し(開いているチャットには、"
                                                 "少なくともウィンドウの再読み込みが要ります)、新しいチャットで /task を試してください"])
        lib, bindir, kiro = self.home / ".local/lib", self.home / ".local/bin", self.home / ".kiro"
        for s in ("task", "chief"):  # junctions to the clone
            self.assertEqual(os.path.realpath(kiro / "skills" / s), os.path.realpath(lib / "task-hub/skills" / s))
        self.assertEqual((kiro / "steering/task-hub.md").read_bytes(),
                         (lib / "task-hub/kiro/steering/task-hub.md").read_bytes())
        for f in (lib / "git/cmd/git.exe", bindir / "uv.exe", bindir / "gh.exe", lib / "kiro-cli/kiro-cli.exe",
                  lib / "task-hub/bin/task", bindir / "task.cmd", bindir / "task"):
            self.assertTrue(f.exists(), f)
        self.assertIn("task-hub: made by windows/install.ps1", (bindir / "task.cmd").read_text(encoding="mbcs"))
        self.assertEqual([json.loads(x) for x in self.uv_log.read_text().splitlines()][:2],
                         [["python", "find", "--python-preference", "only-managed", "--system", "3.12"],
                          ["python", "install", "3.12"]])
        m = self.manifest()
        self.assertEqual(m["python"], sys.executable)
        self.assertEqual(m["installed"], {
            "git": str(lib / "git"), "git-path": str(lib / "git/cmd"), "uv": str(bindir / "uv.exe"), "uv-python": "3.12",
            "gh": str(bindir / "gh.exe"), "git-credential": str(bindir / "gh.exe"),
            "kiro-cli": str(lib / "kiro-cli"), "kiro-cli-path": str(lib / "kiro-cli"),
            "task-hub": str(lib / "task-hub"), "task": str(bindir / "task.cmd"), "task-sh": str(bindir / "task"),
            "user-path": str(bindir), "config": str(self.home / ".config/task-hub/config.ini"),
            "kiro-skill-task": str(kiro / "skills/task"), "kiro-skill-chief": str(kiro / "skills/chief"),
            "kiro-steering": str(kiro / "steering/task-hub.md"), "kiro-hook": str(kiro / "hooks/task-hub-events.json"),
            "kiro-workflow": str(kiro / "workflows/task-hub-events.workflow.json"),
            "kiro-settings": str(self.home / "AppData/Roaming/Kiro/User/settings.json"),
            "slack-triage": str(bindir / "slack-triage.cmd"),
            "slack-triage-autostart": str(self.root / "autostart/task-hub slack-triage.lnk")})
        self.assertEqual(set(m["sha256"]), {"kiro-steering", "kiro-hook", "kiro-workflow"})
        self.assertEqual(self.user_path(), [str(bindir), str(lib / "kiro-cli"), str(lib / "git/cmd")])
        self.assertFalse(self.windows.exists())  # no login was needed
        r = subprocess.run([str(bindir / "task.cmd"), "--version"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        self.srv.log.clear()
        out = self.install()
        for line in ("1. 前提の確認: 済み(", f"2. Python: 済み({sys.executable})", r"3. gh: 済み(~\.local\bin\gh.exe)",
                     r"4. kiro-cli: 済み(~\.local\lib\kiro-cli\kiro-cli.exe)", "5. GitHub のログイン: 済み(alice)",
                     "5. kiro-cli のログイン: 済み", r"6. task-hub 本体: 済み(~\.local\lib\task-hub(", "7. ボード: 済み(",
                     "8. 設定: 済み(", "9. Kiro との連携: 済み(スキル、steering、フック、ワークフロー、Workflows の設定)",
                     "すべて済みです。変えたものはありません。",
                     "11. Slackトリアージ: 済み(止めています", "次にすること: Kiro の新しいチャットで /task を試してください"):
            self.assertIn(line, out)
        self.assertEqual(self.srv.log, ["/", "/"])  # only "does GitHub answer", the installer's and the diagnosis'
        self.assertEqual(self.manifest(), m)

    def test_a_python_uv_already_had_is_used_and_left_at_uninstall(self):
        # uv's own 3.12, which is not python on PATH: uninstall.ps1 must not remove it, and with it the virtualenvs
        # built on it
        uvbin = self.root / "uvbin"
        uvbin.mkdir()
        write_exe(uvbin / "uv.exe", FAKE_UV)
        Path(str(self.uv_log) + ".installed").touch()
        self.set_path("machine", Path(shutil.which("git")).parent)
        self.set_path("user", uvbin, self.kirobin)
        self.set_gh_auth({"login": "alice", "scopes": "gist, project, read:org, repo"})
        self.kiro_logged_in.touch()
        self.install()
        m = self.manifest()
        self.assertEqual(m["python"], sys.executable)
        self.assertNotIn("uv-python", m["installed"])
        self.assertNotIn("uv", m["installed"])  # nor the user's uv
        out = self.uninstall("-Yes")
        self.assertNotIn("uv で入れた Python", out)
        self.assertNotIn(["python", "uninstall", "3.12"], [json.loads(x) for x in self.uv_log.read_text().splitlines()])

    def test_a_python_uv_installs_with_a_virtualenv_active_is_used_and_removed_at_uninstall(self):
        # run from a terminal with a virtualenv active: its Python is neither one uv had nor the one to use
        uvbin = self.root / "uvbin"
        uvbin.mkdir()
        write_exe(uvbin / "uv.exe", FAKE_UV)
        self.set_path("machine", Path(shutil.which("git")).parent)
        self.set_path("user", uvbin, self.kirobin)
        self.set_gh_auth({"login": "alice", "scopes": "gist, project, read:org, repo"})
        self.kiro_logged_in.touch()
        self.env["VIRTUAL_ENV"] = str(self.home / "project" / ".venv")
        self.install()
        m = self.manifest()
        self.assertEqual(m["python"], sys.executable)
        self.assertEqual(m["installed"].get("uv-python"), "3.12")
        self.uninstall("-Yes")
        self.assertIn(["python", "uninstall", "3.12"], [json.loads(x) for x in self.uv_log.read_text().splitlines()])

    def test_finds_what_was_installed_after_the_window_opened(self):
        self.ready()
        out = self.install()
        self.assertIn("1. 前提の確認: 済み(", out)
        self.assertIn(f"2. Python: 済み({sys.executable} を使います)", out)
        self.assertIn(f"4. kiro-cli: 済み({self.kirobin / 'kiro-cli.exe'})", out)
        self.assertNotIn("/git-for-windows/git/releases/latest", self.srv.log)
        self.assertFalse(self.uv_log.exists())
        self.assertEqual(self.manifest()["python"], sys.executable)
        for key in ("uv", "git", "kiro-cli", "kiro-cli-path"):
            self.assertNotIn(key, self.manifest()["installed"])

    def test_a_kiro_cli_from_the_official_installer_is_put_on_path(self):
        self.ready()
        self.set_path("user", Path(sys.executable).parent)  # kiro-cli is only where the official MSI puts it
        official = self.program_files / "Kiro-Cli"
        official.mkdir()
        write_exe(official / "kiro-cli.exe", FAKE_KIRO_CLI)
        out = self.install()
        self.assertIn(f"4. kiro-cli: PATH に足しました({official / 'kiro-cli.exe'})", out)
        self.assertNotIn(f"/kiro/stable/{self.KIRO_MSI}", self.srv.log)
        self.assertIn(str(official), self.user_path())
        self.assertEqual(self.manifest()["installed"]["kiro-cli-path"], str(official))
        self.assertNotIn("kiro-cli", self.manifest()["installed"])

    def test_a_checksum_that_does_not_match_installs_nothing(self):
        self.ready()
        self.srv.files[f"/cli/cli/releases/download/{self.GH_TAG}/gh_2.0.0_checksums.txt"] = \
            f"{'1' * 64}  {self.GH_ZIP}\n".encode()
        out = self.install(code=1)
        self.assertIn(f"3. gh: 止まりました。{self.GH_ZIP} のチェックサムが合いません(一覧: {'1' * 64}、", out)
        self.assertIn("次にすること: 時間をおいてもう一度実行してください", out)
        self.assertFalse((self.home / ".local/bin/gh.exe").exists())
        self.assertNotIn("gh", self.manifest().get("installed", {}))

    def test_stops_for_each_login_in_a_window_and_goes_on_from_there(self):
        self.ready()
        self.set_gh_auth(None)
        self.kiro_logged_in.unlink()
        out = self.install(code=1)
        self.assertIn("5. GitHub のログイン: 止まりました。GitHub にログインしていません。開いた窓で、案内に沿って"
                      "ブラウザで承認してください", out)
        self.assertIn("次にすること: 承認が終わったら、もう一度実行してください", out)
        script = self.windows.read_text(encoding="utf-8")
        self.assertEqual(script.count("'auth' 'login' '--web' '-s' 'project' '-h' 'github.com' '-p' 'https'"), 1)
        self.assertIn("Remove-Item -LiteralPath $PSCommandPath", script)
        self.assertFalse((self.home / ".local/lib/task-hub").exists())  # nothing is cloned before the login

        self.set_gh_auth({"login": "alice", "scopes": "repo"})  # logged in, without the project scope
        out = self.install(code=1)
        self.assertIn("5. GitHub のログイン: 止まりました。Projects の権限(project)が要ります。", out)
        self.assertIn("'auth' 'refresh' '-h' 'github.com' '-s' 'project'", self.windows.read_text(encoding="utf-8"))

        self.set_gh_auth({"login": "alice", "scopes": "gist, project, read:org, repo"})
        self.windows.unlink()
        out = self.install(code=1)
        self.assertIn("5. GitHub のログイン: 設定しました(alice、git も gh のログインを使います)", out)
        self.assertIn("5. kiro-cli のログイン: 止まりました。kiro-cli にログインしていません。", out)
        self.assertIn(f"'{self.kirobin / 'kiro-cli.exe'}' 'login'", self.windows.read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".local/state/task-hub/gh-login.ps1").exists())

        self.kiro_logged_in.touch()
        out = self.install()
        self.assertIn("5. kiro-cli のログイン: 済み", out)
        self.assertIn("6. task-hub 本体: 入れました(clone(", out)
        self.assertFalse((self.home / ".local/state/task-hub/kiro-login.ps1").exists())

    def test_the_clone_follows_the_newest_release_tag(self):
        self.ready()
        self.tag("v0.11.0", "HEAD~1")  # a release before v0.12.0, the first the easy setup installs: not one it takes
        out = self.install()
        self.assertIn("6. task-hub 本体: 入れました(clone(main ", out)
        self.tag("v0.12.0", "HEAD~1")
        out = self.install()
        self.assertIn(" → v0.12.0", out)
        self.tag("v0.12.2")
        self.tag("v0.12.10", "HEAD~1")  # numbers compared as numbers: v0.12.10 is the newest
        out = self.install()
        self.assertIn("6. task-hub 本体: 入れました(v0.12.0 → v0.12.10)", out)

    def test_an_earlier_manual_install_is_taken_over_and_its_branch_kept(self):
        self.ready()
        self.tag("v0.12.0", "HEAD~1")
        lib, shim = self.home / ".local/lib/task-hub", self.home / ".local/bin/task.cmd"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(lib)], check=True, capture_output=True)
        branch = self.lib_git("symbolic-ref", "--short", "HEAD")
        shim.parent.mkdir(parents=True)
        # as docs/windows.md's install wrote it, unmarked: full paths in the code page (an English Windows has no
        # letters for the Japanese folder name: they became ?, which is why it now writes %USERPROFILE%)
        shim.write_text(f'@setlocal\r\n@set PYTHONUTF8=1\r\n@"{sys.executable}" "{lib / "bin/task"}" %*\r\n',
                        encoding="mbcs", errors="replace", newline="")
        out = self.install()
        self.assertEqual(self.lib_git("symbolic-ref", "--short", "HEAD"), branch)  # not switched to v0.12.0
        self.assertIn("task-hub: made by windows/install.ps1", shim.read_text(encoding="mbcs"))
        self.assertIn(r"6. task-hub 本体: 入れました(~\.local\bin\task.cmd", out)
        self.assertNotIn("task-hub", self.manifest()["installed"])  # not the installer's clone

    def test_someone_elses_task_cmd_is_left_alone(self):
        self.ready()
        shim = self.home / ".local/bin/task.cmd"
        shim.parent.mkdir(parents=True)
        shim.write_text("@echo another task\r\n", newline="")
        out = self.install(code=1)
        self.assertIn(r"6. task-hub 本体: 止まりました。~\.local\bin\task.cmd がすでにあります", out)
        self.assertEqual(shim.read_bytes(), b"@echo another task\r\n")

    def test_kiro_files_of_someone_else_are_left_alone(self):
        self.ready()
        own = self.home / ".kiro/skills/task"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("my own /task\n")
        out = self.install()
        self.assertIn(r"~\.kiro\skills\task は別のものを指しているので、そのままにしました", out)
        self.assertEqual((own / "SKILL.md").read_text(), "my own /task\n")
        self.assertNotIn("kiro-skill-task", self.manifest()["installed"])
        # a steering file someone changed is not overwritten, even when task-hub's changes
        steering = self.home / ".kiro/steering/task-hub.md"
        steering.write_text("edited\n")
        out = self.install(code=1)
        self.assertIn(r"9. Kiro との連携: 止まりました。~\.kiro\steering\task-hub.md は、このインストーラが入れた内容と"
                      "確認できないので書き換えていません", out)
        self.assertEqual(steering.read_text(), "edited\n")

    def doctor(self, code=0):
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(REPO / "windows" / "doctor.ps1")],
                           env=self.env, capture_output=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def files(self):  # every file and folder under the user folder, with its size and time
        return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in self.home.rglob("*")
                if not p.is_symlink() and not (p.is_dir() and os.path.realpath(p) != str(p))}

    def test_the_diagnosis_lists_every_stage_and_changes_nothing(self):
        self.ready()
        self.install()
        before = self.files()
        out = self.doctor()
        self.assertTrue(out.startswith("task-hub の診断です(何も変えません)\n"), out)
        for line in ("○ 1. 前提の確認: git、GitHub に接続", f"○ 2. Python: {sys.executable}", r"○ 3. gh: ~\.local\bin\gh.exe",
                     f"○ 4. kiro-cli: {self.kirobin / 'kiro-cli.exe'}", "○ 5. GitHub のログイン: alice",
                     "○ 5. kiro-cli のログイン: ログイン済み", r"○ 6. task-hub 本体: ~\.local\lib\task-hub(",
                     "○ 7. ボード: ", r"○ 8. 設定: ~\.config\task-hub\config.ini、agent = kiro",
                     "○ 9. Kiro との連携: スキル、steering、フック、ワークフロー、Workflows は有効", "○ 10. 常駐: 使っていません",
                     "○ 11. Slackトリアージ: 止めています"):
            self.assertIn(line, out)
        self.assertEqual(out.splitlines()[-2:], ["すべて揃っています。", "次にすること: Kiro の新しいチャットで /task を試してください"])
        self.assertEqual(self.files(), before)

        self.set_gh_auth(None)
        (self.home / ".kiro/skills/chief").rmdir()  # the junction itself, not the clone's folder
        out = self.doctor(code=1)
        self.assertIn("× 5. GitHub のログイン: GitHub にログインしていません\n    → powershell -ExecutionPolicy Bypass "
                      "-File windows\\install.ps1 を実行し、開いた窓でブラウザでログインしてください", out)
        self.assertIn("× 7. ボード: gh が Projects の権限でログインできていないので確かめていません", out)
        self.assertIn(r"× 9. Kiro との連携: ~\.kiro\skills\chief がありません", out)
        self.assertTrue((self.home / ".local/lib/task-hub/skills/chief").is_dir())
        self.assertIn("足りないものが 3 つあります。", out)
        self.assertEqual(out.splitlines()[-1], "次にすること: powershell -ExecutionPolicy Bypass -File windows\\install.ps1 "
                                              "を実行し、開いた窓でブラウザでログインしてください")

    def test_the_hook_and_the_workflow_run_from_cmd_and_powershell(self):
        # Kiro runs a hook's command line in a shell: which one is not known yet on Windows, so both must run it
        self.ready()
        self.install()
        kiro = self.home / ".kiro"
        hook = json.loads((kiro / "hooks/task-hub-events.json").read_text(encoding="utf-8"))["hooks"][0]["action"]["command"]
        flow = json.loads((kiro / "workflows/task-hub-events.workflow.json").read_text(encoding="utf-8"))
        watch = flow["steps"][0]["steps"][0]["config"]["command"]
        self.assertNotIn("$HOME", hook + watch)
        self.assertNotIn("herdr", json.dumps(flow, ensure_ascii=False))  # no herdr tabs on Windows
        events = self.home / ".local/state/task-hub/events.jsonl"
        shells = {"cmd": lambda c: ["cmd.exe", "/d", "/c", c],
                  "powershell": lambda c: ["powershell.exe", "-NoProfile", "-Command", c]}
        for n, (name, shell) in enumerate(shells.items()):
            run = lambda c, stdin=None: subprocess.run(shell(c), env=self.env, capture_output=True, input=stdin,
                                                       encoding="utf-8", errors="replace")
            (self.home / ".local/state/task-hub/kiro-cursor").unlink(missing_ok=True)
            r = run(hook)
            self.assertEqual((r.returncode, r.stdout), (0, ""), f"{name}: {r.stdout}{r.stderr}")  # the past is not news
            with events.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"time": "2026-10-12T00:00:00Z", "id": str(5 + n), "title": "日本語のタスク",
                                    "repo": "alice/app", "event": "In review", "digest": {"verdict": "pass"}},
                                   ensure_ascii=False) + "\n")
            r = run(hook)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stdout}{r.stderr}")
            self.assertIn("task-hub: new events since your last message:", r.stdout, name)
            self.assertIn(f"event: #{5 + n} In review | 日本語のタスク", r.stdout, name)
            r = run(watch, stdin=json.dumps({"cursor": None, "config": {}}))
            self.assertEqual(r.returncode, 0, f"{name}: {r.stdout}{r.stderr}")
            self.assertEqual(json.loads(r.stdout)["outcome"], "idle", name)

    def test_a_command_path_with_a_space_still_runs_unquoted(self):
        spaced = self.root / "with space"
        spaced.mkdir()
        (spaced / "x.exe").write_bytes(b"")
        code = ("import importlib.machinery, importlib.util, sys\n"
                f"loader = importlib.machinery.SourceFileLoader('task_hub_bin', {str(BIN)!r})\n"
                "task = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))\n"
                "loader.exec_module(task)\n"
                "print(task.windows_command_path(sys.argv[1]))\n")
        p = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(spaced / "x.exe")], env=self.env,
                           capture_output=True, encoding="utf-8", check=True).stdout.strip()
        if p.startswith('"'):  # no 8.3 names on this volume: quoted, which cmd.exe still runs
            self.assertEqual(p, f'"{(spaced / "x.exe").as_posix()}"')
        else:
            self.assertNotIn(" ", p)
            self.assertTrue(os.path.samefile(p, spaced / "x.exe"))

    def slack(self, *args):
        r = subprocess.run([str(self.home / ".local/bin/slack-triage.cmd"), *args], env=self.env, capture_output=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=60)
        return r.stdout + r.stderr

    def hotkey_status(self):
        f = self.home / ".local/state/task-hub/slack-triage-hotkey.status"
        return f.read_text(encoding="utf-8").strip() if f.exists() else ""

    @unittest.skipIf(os.environ.get("TASK_TEST_NO_DESKTOP"), "a hotkey needs a desktop (tests/ci/as-standard-user.ps1)")
    def test_slack_triage_key_from_install_to_uninstall(self):
        self.ready()
        self.slack_config(owner_name="佐藤 花子", hotkey_key="j", hotkey_mods="ctrl,alt,shift")  # a key of this test's
        out = self.install()
        self.assertIn("11. Slackトリアージ: 入れました(", out)
        self.assertIn("Slack のスレッドをコピーして Ctrl+Alt+Shift+J で使えます。止めるときは slack-triage off", out)
        self.assertEqual(self.hotkey_status(), "ok Ctrl+Alt+Shift+J")
        self.assertIn("11. Slackトリアージ: 済み(Slack のスレッドをコピーして Ctrl+Alt+Shift+J で使えます)", self.install())
        self.assertIn("○ 11. Slackトリアージ: Slack のスレッドをコピーして Ctrl+Alt+Shift+J で使えます", self.doctor())

        self.assertIn("Ctrl+Alt+Shift+J を止めました", self.slack("off"))
        self.assertEqual(self.hotkey_status(), "off")  # the program read it, and ended
        self.assertIn("○ 11. Slackトリアージ: 止めています", self.doctor())
        self.assertIn("Ctrl+Alt+Shift+J で起動できます", self.slack("on"))
        self.assertIn("起動キーを Ctrl+Alt+Shift+K にしました", self.slack("key", "k"))
        self.assertEqual(self.hotkey_status(), "ok Ctrl+Alt+Shift+K")

        out = self.uninstall("-Yes")
        self.assertIn(r"消しました: Slackトリアージの起動キーを待つ常駐(", out)
        self.assertIn(r"消しました: ~\.local\bin\slack-triage.cmd", out)
        self.assertFalse((self.root / "autostart/task-hub slack-triage.lnk").exists())
        time.sleep(1)
        self.assertIn("× 11. Slackトリアージ: task-hub 本体がないので確かめていません", self.doctor(code=1))

    @unittest.skipIf(os.environ.get("TASK_TEST_NO_DESKTOP"), "a hotkey needs a desktop (tests/ci/as-standard-user.ps1)")
    def test_starting_at_logon_with_a_user_folder_name_no_code_page_has(self):
        # on an English Windows a Japanese name is such a name: the shortcut must not lose it
        self.ready()
        self.slack_config(owner_name="佐藤 花子", hotkey_key="m", hotkey_mods="ctrl,alt,shift")
        out = self.install()
        self.assertIn("Slack のスレッドをコピーして Ctrl+Alt+Shift+M で使えます", out)
        lnk = self.root / "autostart/task-hub slack-triage.lnk"
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                            "(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK).Arguments"],
                           env={**os.environ, "LNK": str(lnk)}, capture_output=True, encoding="utf-8", errors="replace")
        self.assertNotIn("?", r.stdout)  # short 8.3 names, which the shortcut keeps
        for path in re.findall(r'"([^"]+)"', r.stdout):
            self.assertTrue(os.path.exists(path), path)
        self.assertIn("11. Slackトリアージ: 済み(Slack のスレッドをコピーして Ctrl+Alt+Shift+M で使えます)", self.install())
        self.assertIn("○ 11. Slackトリアージ: Slack のスレッドをコピーして Ctrl+Alt+Shift+M で使えます", self.doctor())
        self.assertIn("消しました: Slackトリアージの起動キーを待つ常駐(", self.uninstall("-Yes"))
        time.sleep(1)
        loops = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                                "@(Get-CimInstance Win32_Process -Filter \"Name = 'powershell.exe'\" | Where-Object { "
                                "$_.CommandLine -like '*slack-triage-hotkey.ps1*' -and $_.CommandLine -like '*-Main*' -and "
                                "$_.CommandLine.Contains($env:ROOT) }).Count"],
                               env={**os.environ, "ROOT": str(self.root)}, capture_output=True, text=True)
        self.assertEqual(loops.stdout.strip(), "0")  # the uninstaller found it by its short name, and stopped it

    def uninstall(self, *args, code=0):
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(REPO / "windows" / "uninstall.ps1"), *args],
                           env=self.env, capture_output=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def git_credentials(self):
        r = subprocess.run(["git", "config", "--global", "--get-regexp", r"^credential\."], env=self.env,
                           capture_output=True, text=True)
        return r.stdout.splitlines()

    def test_uninstall_lists_then_removes_only_what_was_recorded(self):
        self.set_gh_auth({"login": "alice", "scopes": "gist, project, read:org, repo"})
        self.kiro_logged_in.touch()
        (self.home / ".gitconfig").write_text('[credential]\n\thelper = manager\n'  # the user's own
                                              '[credential "https://example.com"]\n\thelper = store\n', encoding="utf-8")
        self.install()  # a bare PC: everything comes from the installer
        self.assertTrue([c for c in self.git_credentials() if "gh.exe auth git-credential" in c])
        lib, bindir, kiro = self.home / ".local/lib", self.home / ".local/bin", self.home / ".kiro"
        (kiro / "skills/other").mkdir()  # someone's own
        before = self.files()
        out = self.uninstall()
        for line in (r"- ~\.kiro\skills\task(ジャンクション)", r"- ~\.local\lib\task-hub(task-hub の clone)",
                     r"- ~\.local\lib\kiro-cli(kiro-cli)", r"- ~\.local\lib\git(git(MinGit))", "- uv で入れた Python 3.12",
                     r"- git が GitHub のログインに ~\.local\bin\gh.exe を使う設定(~\.gitconfig)",
                     r"- ユーザーの PATH の ~\.local\bin", "https://github.com/alice/tasks/settings"):
            self.assertIn(line, out)
        self.assertEqual(out.splitlines()[-1], "次にすること: 消してよければ、powershell -ExecutionPolicy Bypass -File "
                                              "windows\\uninstall.ps1 -Yes を実行してください")
        self.assertEqual(self.files(), before)  # only listed

        out = self.uninstall("-Yes")
        self.assertNotIn("消せませんでした", out)
        self.assertIn("https://github.com/alice/tasks/settings", out)  # read before config.ini was removed
        for gone in (bindir / "gh.exe", bindir / "uv.exe", bindir / "task.cmd", bindir / "task", lib / "git",
                     lib / "kiro-cli", lib / "task-hub", kiro / "skills/task", kiro / "skills/chief",
                     kiro / "steering/task-hub.md", kiro / "hooks/task-hub-events.json",
                     kiro / "workflows/task-hub-events.workflow.json", self.home / ".config/task-hub/config.ini",
                     bindir / "slack-triage.cmd", self.root / "autostart/task-hub slack-triage.lnk",
                     self.home / ".local/state/task-hub/install-manifest.json"):
            self.assertFalse(os.path.lexists(gone), gone)
        self.assertTrue((kiro / "skills/other").is_dir())
        self.assertTrue((self.home / "AppData/Roaming/Kiro/User/settings.json").exists())  # the user's: said, not removed
        self.assertIn(r"~\AppData\Roaming\Kiro\User\settings.json の Workflows の設定(インストーラは有効にしただけです)", out)
        self.assertEqual([p for p in self.user_path() if p], [])
        self.assertIn(["python", "uninstall", "3.12"], [json.loads(x) for x in self.uv_log.read_text().splitlines()])
        # git no longer asks the removed gh.exe for the login (every fetch and push would fail); the user's own stay
        self.assertEqual(self.git_credentials(), ["credential.helper manager", "credential.https://example.com.helper store"])
        self.assertEqual(out.splitlines()[-1], "次にすること: Kiro を再起動してください(/task と /chief が外れます)")

    def test_uninstall_keeps_a_clone_it_did_not_make_and_never_empties_it_through_a_junction(self):
        self.ready()
        lib = self.home / ".local/lib/task-hub"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(lib)], check=True, capture_output=True)
        self.install()  # takes the clone over, but does not record it
        out = self.uninstall("-Yes")
        self.assertIn(r"消しました: ~\.kiro\skills\task(ジャンクション)", out)
        self.assertNotIn("task-hub の clone", out)
        self.assertTrue((lib / "skills/task/SKILL.md").exists())  # the junction went, not what it led to
        self.assertTrue((lib / ".git").is_dir())

    def test_uninstall_waits_while_a_task_runs(self):
        self.ready()
        self.install()
        lib = self.home / ".local/lib/task-hub"
        run = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", str(lib / "bin" / "task"), "_run", "7"])
        self.addCleanup(run.wait)
        self.addCleanup(run.kill)
        out = self.uninstall("-Yes", code=1)
        self.assertIn("作業中のタスクがあります(#7)", out)
        self.assertTrue((self.home / ".local/bin/task.cmd").exists())
        self.assertTrue((self.home / ".local/state/task-hub/install-manifest.json").exists())
        self.assertIsNone(run.poll())

    def test_uninstall_of_an_install_from_before_the_easy_setup(self):
        shim = self.home / ".local/bin/task.cmd"
        shim.parent.mkdir(parents=True)
        shim.write_text("@setlocal\r\n", newline="")
        out = self.uninstall("-Yes")
        self.assertIn("の記録(~\\.local\\state\\task-hub\\install-manifest.json)がありません", out)
        self.assertIn(r"消しました: ~\.local\bin\task.cmd", out)
        self.assertFalse(shim.exists())

    def test_scripts_with_japanese_are_saved_with_a_bom(self):
        # Windows PowerShell 5.1 reads a .ps1 without one in the ANSI code page: the Japanese would be garbled
        for f in (REPO / "windows").glob("*.ps1"):
            data = f.read_bytes()
            if any(b > 127 for b in data):
                self.assertTrue(data.startswith(b"\xef\xbb\xbf"), f)


# a release's installer, in the releases of UpdateTest: says how it was run, then does what the real one does to the
# clone (switches it to its own tag), or stops as the real one does when the file "stop" is there
FAKE_RELEASE_INSTALLER = r'''
param([switch]$Watch)
$lib = Join-Path $env:USERPROFILE '.local\lib\task-hub'
$me = Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
Write-Host "fake installer of @TAG@ from $me$(if ($Watch) { ' -Watch' })"
if (Test-Path (Join-Path $env:USERPROFILE 'stop')) { Write-Host '次にすること: もう一度'; exit 1 }
git -C $lib checkout -q --detach @TAG@
'''


@unittest.skipUnless(WINDOWS, "Windows only")
class UpdateTest(unittest.TestCase):
    """task update on Windows: an installer's clone (on a release tag) is updated by the newest release's own
    windows\\install.ps1, run from a copy of that release, with -Watch when the watch is installed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "ユーザー"
        self.lib = self.home / ".local/lib/task-hub"
        self.origin, self.seed = root / "task-hub.git", root / "seed"
        git_id = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
                  "GIT_COMMITTER_EMAIL": "t@e"}
        self.env = {**os.environ, **git_id, "USERPROFILE": str(self.home), "HOME": str(self.home),
                    "TASK_NO_UPDATE_NOTIFIER": "1"}
        for k in ("PYTHONUTF8", "PYTHONIOENCODING"):
            self.env.pop(k, None)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.seed)], check=True, capture_output=True)
        self.release("v0.12.0")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.lib)], check=True, capture_output=True)
        self.git(self.lib, "checkout", "-q", "--detach", "v0.12.0")  # where the installer keeps its clone

    def git(self, where, *args):
        return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True, text=True,
                              env=self.env).stdout.strip()

    def release(self, tag):
        """A release of task-hub: this checkout's bin/task, and a stand-in windows\\install.ps1"""
        (self.seed / "bin").mkdir(exist_ok=True)
        (self.seed / "windows").mkdir(exist_ok=True)
        shutil.copy(BIN, self.seed / "bin/task")
        (self.seed / "windows/install.ps1").write_text(FAKE_RELEASE_INSTALLER.replace("@TAG@", tag), encoding="utf-8-sig")
        (self.seed / "release.txt").write_text(tag)
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-qm", f"release {tag}")
        self.git(self.seed, "tag", tag)
        self.git(self.seed, "push", "-q", "origin", "main", tag)

    def update(self, code=0):
        r = subprocess.run([sys.executable, str(self.lib / "bin/task"), "update"], env=self.env, capture_output=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def test_an_installers_clone_is_updated_by_the_new_releases_installer(self):
        self.assertIn("up_to_date: v0.12.0 (newest release v0.12.0)", self.update())
        self.release("v0.13.0")
        manifest = self.home / ".local/state/task-hub/install-manifest.json"  # its folder: update.json is there
        manifest.write_text(json.dumps({"version": 1, "installed": {"watch": "scheduled-task:task-hub watch"}}))
        out = self.update()
        self.assertIn("update: v0.12.0 -> v0.13.0, by v0.13.0's installer", out)
        self.assertIn("fake installer of v0.13.0 from task-hub -Watch", out)  # the new one, from a copy, with -Watch
        self.assertIn("updated: v0.12.0 -> v0.13.0 (v0.13.0)", out)
        self.assertEqual(self.git(self.lib, "describe", "--tags", "--exact-match"), "v0.13.0")
        self.assertEqual(list(Path(tempfile.gettempdir()).glob("task-hub-update-*")), [])  # the copy is gone

        self.release("v0.14.0")
        (self.home / "stop").touch()
        out = self.update(code=1)
        self.assertIn("v0.14.0's installer stopped (exit 1)", out)
        self.assertIn("次にすること: もう一度", out)  # the installer's own next step, as it said it
        self.assertEqual(self.git(self.lib, "describe", "--tags", "--exact-match"), "v0.13.0")


SLACK_APP = REPO / "slack-triage" / "app"
SLACK_THREAD = ("山田 太郎 12:36\n@佐藤 花子 社内ツールの README に Windows の手順を足してほしい & 急ぎではないです\n"
                "https://example.slack.com/archives/C0123ABC/p1727840000123456")
# Kiro's answer, as kiro-cli chat prints it
FAKE_SLACK_KIRO = r'''
import json, sys
if sys.argv[1:2] == ["whoami"]:
    sys.exit(0)
answer = {"summary": {"overview": "README に Windows の手順がない", "requests": ["山田さん → 佐藤さん: 手順を足す"],
                      "decided": [], "open": []},
          "tasks": [{"title": "README に Windows の手順を足す & 確かめる", "repo": "alice/app", "research": False,
                     "goal": "README.md に Windows のセットアップ手順を足す。100% 動くこと"}]}
sys.stdout.buffer.write(("<<<JSON\n" + json.dumps(answer, ensure_ascii=False) + "\nJSON>>>\n").encode("utf-8"))
'''
# task new: keeps its arguments and the goal file
FAKE_SLACK_TASK = r'''
import json, os, sys
a = sys.argv[1:]
goal = open(a[a.index("--goal-file") + 1], encoding="utf-8").read()
with open(os.environ["SLACK_TEST_TASK_CALLS"], "w", encoding="utf-8") as f:
    json.dump({"args": a, "goal": goal}, f, ensure_ascii=False)
print("task:\n  id: 42\n  status: Backlog\n  url: https://github.com/alice/tasks/issues/42")
'''
# runs slack-triage with its screens replaced: `run` registers the first draft; `dialogs` presses the buttons of each
# real tkinter dialog, as a person would
SLACK_RUNNER = r'''
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.environ["SLACK_APP"])
from slack_triage import cli, winui
calls = []
if sys.argv[1] == "run":
    class UI(winui.WinUI):
        def review_task(self, task, i, total, summary):
            calls.append(["review", task["title"], summary["overview"]])
            return "register"
        def registered(self, task, url): calls.append(["registered", url])
        def alert(self, m): calls.append(["alert", m])
        def notify(self, m): calls.append(["notify", m])
    winui.WinUI = UI
    cli.read_clipboard = lambda: os.environ["SLACK_TEST_THREAD"]
    print(json.dumps({"code": cli.main(["run"]), "calls": calls}, ensure_ascii=False))
elif sys.argv[1] == "clipboard":
    print(json.dumps({"text": cli.read_windows_clipboard()}, ensure_ascii=False))
elif sys.argv[1] == "dialogs":
    try:
        import tkinter
        tkinter.Tk().destroy()
    except Exception as e:  # no desktop to draw on
        print(json.dumps({"skip": str(e)}))
        sys.exit(0)
    actions = []
    def fake_run(root):
        root.after(100, lambda: actions.pop(0)(root))
        root.mainloop()
        return root.answer
    winui._run = fake_run
    def text_of(root):  # every Text widget's words, to see what the person would read
        return "".join(w.get("1.0", "end") for w in root.winfo_children()[1].winfo_children() if w.winfo_class() == "Text")
    seen = {}
    def press(label, before=None):
        def act(root):
            if before:
                before(root)
            seen.setdefault(label, text_of(root) if len(root.winfo_children()) > 1 else "")
            root.buttons[label].invoke()
        return act
    task = {"title": "日本語のタイトル & 記号", "goal": "1 行目\n2 行目", "repo": "alice/app"}
    summary = {"overview": "概要です", "requests": [], "decided": [], "open": []}
    ui = winui.WinUI()
    actions.append(press("登録"))
    out = {"review": ui.review_task(task, 0, 1, summary)}
    out["review_text"] = seen.get("登録", "")
    def edit(root):
        root.edit[0].delete(0, "end")
        root.edit[0].insert(0, "直したタイトル")
        root.edit[1].insert("end", "\n3 行目")
    actions.append(press("登録へ", edit))
    out["edit"] = ui.edit_task(task)
    actions.append(press("キャンセル"))
    out["edit_cancel"] = ui.edit_task(task)
    actions.append(press("OK", lambda root: root.entry.insert("end", "bob/tool")))
    out["ask"] = winui.ask_text("リポジトリ", "")
    def pick(root):
        root.box.selection_clear(0, "end")
        root.box.selection_set(1)
        root.box.selection_set(2)
    actions.append(press("OK", pick))
    out["many"] = winui.choose_many("⌘ を押しながら選ぶ", ["alice/a", "alice/b", "alice/c"], ["alice/a"])
    actions.append(press("はい"))
    out["confirm"] = winui.confirm("よいですか")
    print(json.dumps(out, ensure_ascii=False))
else:
    print(json.dumps({"code": cli.main(sys.argv[1:])}, ensure_ascii=False))
'''


@unittest.skipUnless(WINDOWS, "Windows only")
class SlackTriageTest(unittest.TestCase):
    """slack-triage on Windows (docs/slack-triage.md): the clipboard, the tkinter screens, task new with no batch file
    between, and the commands that do not need the key yet (check, key)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        root = self.root = Path(self.tmp.name)
        self.home = root / "ユーザー"
        (self.home / ".config/task-hub").mkdir(parents=True)
        write_exe(root / "kiro-cli.exe", FAKE_SLACK_KIRO)
        write_exe(root / "task.exe", FAKE_SLACK_TASK)
        (root / "runner.py").write_text(SLACK_RUNNER, encoding="utf-8")
        self.calls = root / "task-calls.json"
        self.env = {**os.environ, "USERPROFILE": str(self.home), "HOME": str(self.home), "SLACK_APP": str(SLACK_APP),
                    "KIRO_BIN": str(root / "kiro-cli.exe"), "TASK_BIN": str(root / "task.exe"),
                    "SLACK_TEST_TASK_CALLS": str(self.calls), "SLACK_TEST_THREAD": SLACK_THREAD}
        for k in ("PYTHONUTF8", "PYTHONIOENCODING"):
            self.env.pop(k, None)

    def config(self, **c):
        (self.home / ".config/task-hub/slack-triage.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")

    def runner(self, *args, env=None):
        r = subprocess.run([sys.executable, str(self.root / "runner.py"), *args], env=env or self.env,
                           capture_output=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_a_thread_on_the_clipboard_becomes_a_task(self):
        self.config(owner_name="佐藤 花子", aliases=[], candidates=["alice/app"], allowed_owner="alice")
        out = json.loads(self.runner("run").stdout.splitlines()[-1])
        self.assertEqual(out["code"], 0, out)
        self.assertIn(["review", "README に Windows の手順を足す & 確かめる", "README に Windows の手順がない"], out["calls"])
        self.assertNotIn("alert", [c[0] for c in out["calls"]], out["calls"])
        self.assertEqual(out["calls"][-1], ["registered", "https://github.com/alice/tasks/issues/42"])
        sent = json.loads(self.calls.read_text(encoding="utf-8"))
        a = sent["args"]
        self.assertEqual(a[:5], ["new", "--title", "README に Windows の手順を足す & 確かめる", "--repo", "alice/app"])
        self.assertTrue(sent["goal"].startswith("README.md に Windows のセットアップ手順を足す。100% 動くこと"))
        self.assertIn("- Slackスレッド: https://example.slack.com/archives/C0123ABC/p1727840000123456", sent["goal"])

    def test_the_screens_are_tkinter_dialogs(self):
        out = json.loads(self.runner("dialogs").stdout.splitlines()[-1])
        if "skip" in out:
            self.skipTest(f"no desktop: {out['skip']}")
        self.assertEqual(out["review"], "register")
        self.assertIn("■ 日本語のタイトル & 記号", out["review_text"])
        self.assertEqual((out["edit"]["title"], out["edit"]["goal"]), ("直したタイトル", "1 行目\n2 行目\n3 行目"))
        self.assertIsNone(out["edit_cancel"])
        self.assertEqual(out["ask"], "bob/tool")
        self.assertEqual(out["many"], ["alice/b", "alice/c"])
        self.assertTrue(out["confirm"])

    def test_the_clipboard_is_read_as_unicode(self):
        text = "日本語のスレッド\r\n2 行目 ✓"

        def ps(command, value=""):  # the text goes in as a variable, never into the command
            return subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                                   "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + command],
                                  capture_output=True, encoding="utf-8", errors="replace",
                                  env={**os.environ, "SLACK_TEST_CLIP": value})
        before = ps("Get-Clipboard -Raw").stdout
        if ps("Set-Clipboard -Value $env:SLACK_TEST_CLIP", text).returncode != 0:
            self.skipTest("no clipboard here")
        self.addCleanup(ps, "Set-Clipboard -Value $env:SLACK_TEST_CLIP", before or " ")  # what the person had copied
        self.assertEqual(json.loads(self.runner("clipboard").stdout.splitlines()[-1])["text"], text)

    def test_the_key_starts_slack_triage(self):
        # windows/slack-triage-hotkey.ps1 by itself: a key of this test's, sent with keybd_event as if typed
        import ctypes
        self.config(hotkey_key="q", hotkey_mods="ctrl,alt,shift")
        mark = self.root / "pressed.txt"
        main = self.root / "main.py"
        main.write_text(f"open({str(mark)!r}, 'a').write('pressed\\n')\n")
        loop = subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(REPO / "windows/slack-triage-hotkey.ps1"), "-Python", sys.executable, "-Main", str(main)],
                                env=self.env)
        self.addCleanup(loop.wait)
        self.addCleanup(loop.kill)
        status = self.home / ".local/state/task-hub/slack-triage-hotkey.status"
        end = time.time() + 30
        while time.time() < end and not status.exists():
            time.sleep(0.25)
        self.assertEqual(status.read_text(encoding="utf-8").strip(), "ok Ctrl+Alt+Shift+Q")
        keys = (0x11, 0x12, 0x10, 0x51)  # Ctrl, Alt, Shift, Q
        for k in keys:
            ctypes.windll.user32.keybd_event(k, 0, 0, 0)
        for k in reversed(keys):
            ctypes.windll.user32.keybd_event(k, 0, 2, 0)  # KEYEVENTF_KEYUP
        end = time.time() + 10
        while time.time() < end and not mark.exists():
            time.sleep(0.25)
        if not mark.exists():
            self.skipTest("keys cannot be sent to this session")
        # a new key, then off: the program reads the config again by itself
        self.config(hotkey_key="w", hotkey_mods="ctrl,alt,shift")
        end = time.time() + 10
        while time.time() < end and "W" not in status.read_text(encoding="utf-8"):
            time.sleep(0.25)
        self.assertEqual(status.read_text(encoding="utf-8").strip(), "ok Ctrl+Alt+Shift+W")
        self.config(hotkey_key="w", hotkey_mods="ctrl,alt,shift", enabled=False)
        self.assertEqual(loop.wait(15), 0)
        self.assertEqual(status.read_text(encoding="utf-8").strip(), "off")

    def test_check_and_the_key_on_windows(self):
        self.config(owner_name="佐藤 花子", candidates=[])
        env = {**self.env, "KIRO_BIN": "", "PATH": str(Path(os.environ["SystemRoot"]) / "System32")}
        r = self.runner("check", env=env)
        self.assertIn("× 起動キー: 常駐していません", r.stdout)
        self.assertIn("powershell -ExecutionPolicy Bypass -File windows\\install.ps1 を実行してください", r.stdout)
        r = self.runner("key", "t", "ctrl,shift", env=env)
        self.assertIn("起動キーを Ctrl+Shift+T にしました", r.stdout)
        c = json.loads((self.home / ".config/task-hub/slack-triage.json").read_text(encoding="utf-8"))
        self.assertEqual((c["hotkey_key"], c["hotkey_mods"]), ("t", "ctrl,shift"))
        r = self.runner("key", "t", "ctrl,cmd", env=env)  # cmd is a Mac name: Win on Windows
        self.assertIn("Ctrl+Win+T", r.stdout)


@unittest.skipUnless(WINDOWS and os.environ.get("TASK_TEST_WINDOWS_INSTALL") == "1",
                     "changes the user PATH and Task Scheduler: CI only")
class InstallTest(unittest.TestCase):
    """The real install: this user's profile, PATH and Task Scheduler. GitHub's login and kiro-cli are fakes found
    first on PATH (the runner's own gh is on the machine's PATH, which the test hides); git's global config is a
    temporary file."""

    def ps(self, *args):
        return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               str(REPO / "windows" / "install.ps1"), *args],
                              env=self.env, capture_output=True, encoding="utf-8", errors="replace")

    def setUp(self):
        import test_install
        self.home = Path.home()
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        fakes = root / "fakes"
        fakes.mkdir()
        (fakes / "fcntl.py").write_text(FCNTL)
        write_exe(fakes / "gh.exe", test_install.fake_gh("2.0.0"))
        write_exe(fakes / "kiro-cli.exe", FAKE_KIRO_CLI)
        (root / "kiro-logged-in").touch()
        db = root / "gh.json"
        db.write_text(json.dumps({"auth": {"login": "alice", "scopes": "gist, project, read:org, repo"},
                                  "code": "ABCD-1234", "approve": None, "repos": {}, "projects": [], "calls": []}))
        self.env = {**os.environ, "PATH": f"{fakes};{os.environ['PATH']}", "PYTHONPATH": str(fakes),
                    "TASK_INSTALL_MACHINE_ENV": rf"Software\task-hub-test\{os.getpid()}\machine",
                    "TASK_TEST_GH_DB": str(db), "TASK_TEST_KIRO_LOGGED_IN": str(root / "kiro-logged-in"),
                    "HOME": str(root), "GIT_CONFIG_GLOBAL": str(root / ".gitconfig")}
        self.addCleanup(delete_key, rf"Software\task-hub-test\{os.getpid()}")
        config = self.home / ".config/task-hub/config.ini"  # stage 8 writes it, for the fake GitHub's board
        if not config.exists():
            self.addCleanup(config.unlink, missing_ok=True)
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
        self.assertIn("10. 常駐: 始めました(タスク スケジューラの「task-hub watch」", r.stdout)  # not the Startup folder
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
        # the loop says when it starts task watch (which then fails: the runner's own gh is not logged in)
        log = self.home / ".local/state/task-hub/watch.log"
        end = time.time() + 60
        while time.time() < end and "starting task watch" not in (log.read_text(errors="replace")
                                                                if log.exists() else ""):
            time.sleep(1)
        self.assertIn("starting task watch", log.read_text(errors="replace"))
        self.assertTrue(set(self.watch_loops()) - {bystander.pid})  # the loop itself
        # task update starts the watch again with the new code: a new loop, the bystander left alone
        before = set(self.watch_loops()) - {bystander.pid}
        code = ("import importlib.machinery, importlib.util\n"
                f"loader = importlib.machinery.SourceFileLoader('task_hub_bin', {str(self.home / '.local/lib/task-hub/bin/task')!r})\n"
                "task = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))\n"
                "loader.exec_module(task)\n"
                "print(task.restart_windows_watch())\n")
        r = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True)
        self.assertIn("watch: restarted the scheduled task 'task-hub watch'", r.stdout, r.stderr)
        end = time.time() + 30
        while time.time() < end and not (set(self.watch_loops()) - {bystander.pid} - before):
            time.sleep(1)
        self.assertTrue(set(self.watch_loops()) - {bystander.pid} - before)  # a new loop
        self.assertFalse(before & set(self.watch_loops()))  # the old one is gone
        self.assertIsNone(bystander.poll())
        r = self.ps("-Uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(shim.exists())
        time.sleep(1)
        self.assertEqual(self.watch_loops(), [bystander.pid])
        self.assertIsNone(bystander.poll())
        tasks = subprocess.run(["schtasks", "/Query", "/TN", "task-hub watch"], capture_output=True)
        self.assertNotEqual(tasks.returncode, 0)


@unittest.skipUnless(WINDOWS, "Windows only")
class WindowsBenchTest(test_bench.BenchTest):
    """tests/bench.py --quick on Windows: ctypes (GetProcessMemoryInfo, GetProcessTimes) instead of os.wait4 and ps."""


if __name__ == "__main__":
    unittest.main()
