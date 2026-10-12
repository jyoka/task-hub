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
        """The fake GitHub. Windows refuses to open a file another process is writing, and the fake gh writes it
        without a lock here (fcntl is a no-op shim): read again for a moment instead of failing the test."""
        for attempt in range(50):
            try:
                return json.loads(self.db.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                if attempt == 49:
                    raise
                time.sleep(0.05)

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
if a[:2] == ["python", "find"] and os.path.exists(log + ".installed"):
    print(sys.executable)  # "uv's Python" is this one
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
        self.home = root / "ユーザー"
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
        # task-hub's origin: kiro-v* tags are added by the tests that want them
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
                    "PYTHONPATH": str(fakes)}
        for k in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONHOME", "VIRTUAL_ENV", "GH_TOKEN", "GITHUB_TOKEN",
                  "GIT_CONFIG_GLOBAL"):
            self.env.pop(k, None)

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
                      r"~\.kiro\steering\task-hub.md(コピー)。Kiro を再起動すると読み込まれます)", out)
        self.assertIn("10. 常駐: 飛ばしました(", out)
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
        self.assertEqual(json.loads(self.uv_log.read_text().splitlines()[0]), ["python", "install", "3.12"])
        m = self.manifest()
        self.assertEqual(m["python"], sys.executable)
        self.assertEqual(m["installed"], {
            "git": str(lib / "git"), "git-path": str(lib / "git/cmd"), "uv": str(bindir / "uv.exe"), "uv-python": "3.12",
            "gh": str(bindir / "gh.exe"), "kiro-cli": str(lib / "kiro-cli"), "kiro-cli-path": str(lib / "kiro-cli"),
            "task-hub": str(lib / "task-hub"), "task": str(bindir / "task.cmd"), "task-sh": str(bindir / "task"),
            "user-path": str(bindir), "config": str(self.home / ".config/task-hub/config.ini"),
            "kiro-skill-task": str(kiro / "skills/task"), "kiro-skill-chief": str(kiro / "skills/chief"),
            "kiro-steering": str(kiro / "steering/task-hub.md")})
        self.assertEqual(set(m["sha256"]), {"kiro-steering"})
        self.assertEqual(self.user_path(), [str(bindir), str(lib / "kiro-cli"), str(lib / "git/cmd")])
        self.assertFalse(self.windows.exists())  # no login was needed
        r = subprocess.run([str(bindir / "task.cmd"), "--version"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        self.srv.log.clear()
        out = self.install()
        for line in ("1. 前提の確認: 済み(", f"2. Python: 済み({sys.executable})", r"3. gh: 済み(~\.local\bin\gh.exe)",
                     r"4. kiro-cli: 済み(~\.local\lib\kiro-cli\kiro-cli.exe)", "5. GitHub のログイン: 済み(alice)",
                     "5. kiro-cli のログイン: 済み", r"6. task-hub 本体: 済み(~\.local\lib\task-hub(", "7. ボード: 済み(",
                     "8. 設定: 済み(", "9. Kiro との連携: 済み(スキル、steering)", "すべて済みです。変えたものはありません。",
                     "次にすること: Kiro の新しいチャットで /task を試してください"):
            self.assertIn(line, out)
        self.assertEqual(self.srv.log, ["/", "/"])  # only "does GitHub answer", the installer's and the diagnosis'
        self.assertEqual(self.manifest(), m)

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
        self.tag("kiro-v1", "HEAD~1")
        out = self.install()
        self.assertIn("6. task-hub 本体: 入れました(clone(kiro-v1)", out)
        self.tag("kiro-v2")
        self.tag("kiro-v10", "HEAD~1")  # numbers compared as numbers: v10 is the newest
        out = self.install()
        self.assertIn("6. task-hub 本体: 入れました(kiro-v1 → kiro-v10)", out)

    def test_an_earlier_manual_install_is_taken_over_and_its_branch_kept(self):
        self.ready()
        self.tag("kiro-v1", "HEAD~1")
        lib, shim = self.home / ".local/lib/task-hub", self.home / ".local/bin/task.cmd"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(lib)], check=True, capture_output=True)
        branch = self.lib_git("symbolic-ref", "--short", "HEAD")
        shim.parent.mkdir(parents=True)
        # as docs/windows.md's install wrote it, unmarked: full paths in the code page (an English Windows has no
        # letters for the Japanese folder name: they became ?, which is why it now writes %USERPROFILE%)
        shim.write_text(f'@setlocal\r\n@set PYTHONUTF8=1\r\n@"{sys.executable}" "{lib / "bin/task"}" %*\r\n',
                        encoding="mbcs", errors="replace", newline="")
        out = self.install()
        self.assertEqual(self.lib_git("symbolic-ref", "--short", "HEAD"), branch)  # not switched to kiro-v1
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
                     "○ 9. Kiro との連携: スキル、steering", "○ 10. 常駐: 使っていません"):
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

    def test_scripts_with_japanese_are_saved_with_a_bom(self):
        # Windows PowerShell 5.1 reads a .ps1 without one in the ANSI code page: the Japanese would be garbled
        for f in (REPO / "windows").glob("*.ps1"):
            data = f.read_bytes()
            if any(b > 127 for b in data):
                self.assertTrue(data.startswith(b"\xef\xbb\xbf"), f)


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
