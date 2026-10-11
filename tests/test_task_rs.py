"""task-rs tui's `g`: Lazygit in the selected task's worktree, driven the way a person does, in a real terminal (a PTY).

Each test builds task-rs (cargo, debug) once, then runs `task-rs tui` in a PTY with a temporary HOME: a config, a
local board, runs/<id>.json and real git worktrees. `lazygit` on PATH is a fake that records where and how it ran
(working directory, arguments, whether its stdin and stdout are a terminal, the terminal's mode), talks to the
person through the terminal, and can change the board or exit with a code meanwhile. `gh` (TASK_GH) notes any call.
Skipped without cargo, and on Windows (no PTY).
"""
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUST = ROOT / "rust"
WINDOWS = os.name == "nt"
if not WINDOWS:
    import fcntl
    import pty
    import struct
    import termios

ENTER_ALT, LEAVE_ALT, SHOW_CURSOR = "\x1b[?1049h", "\x1b[?1049l", "\x1b[?25h"
ROWS, COLS = 40, 140
POPUP = (9, 31, 25, 115)  # the confirmation with its border: rows and columns, from tui.rs's size for 40x140
ESCAPE = re.compile(r"\x1b\[([0-9;?]*)([ -/]*)([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b.", re.S)
_built = None


class Screen:
    """Just enough of a terminal to see what ratatui drew: it moves the cursor, clears, and prints."""

    def __init__(self):
        self.grid = [[" "] * COLS for _ in range(ROWS)]
        self.row = self.col = 0
        self.pending = ""

    def feed(self, data):
        data, self.pending = self.pending + data, ""
        at = 0
        while at < len(data):
            c = data[at]
            if c == "\x1b":
                m = ESCAPE.match(data, at)
                if not m:
                    self.pending = data[at:]  # the rest comes in the next read
                    return
                if m.group(3) == "H":
                    nums = [int(n) if n else 1 for n in (m.group(1) or "1;1").split(";")] + [1]
                    self.row, self.col = min(nums[0], ROWS) - 1, min(nums[1], COLS) - 1
                elif m.group(3) == "J" and m.group(1) in ("2", "3"):
                    self.grid = [[" "] * COLS for _ in range(ROWS)]
                at = m.end()
                continue
            if c == "\r":
                self.col = 0
            elif c == "\n":
                self.row = min(self.row + 1, ROWS - 1)
            elif c >= " ":
                if self.col < COLS:
                    self.grid[self.row][self.col] = c
                self.col += 1
            at += 1

    def text(self, rows=(0, ROWS), cols=(0, COLS)):
        return "\n".join("".join(self.grid[r][cols[0]:cols[1]]) for r in range(*rows))

FAKE_LAZYGIT = r"""#!/bin/sh
# a fake lazygit: notes how it ran, talks through the terminal, then does what $LG/do says
pwd -P > "$LG/cwd"
printf '%s\n' "$#" "$@" > "$LG/args"
if [ -t 0 ] && [ -t 1 ]; then echo yes > "$LG/tty"; fi
stty -a > "$LG/stty" 2>&1
echo "FAKE-LAZYGIT ready in $(pwd -P)"
IFS= read -r line
echo "$line" > "$LG/input"
echo "FAKE-LAZYGIT got: $line" >&2
if [ -f "$LG/board" ]; then cp "$LG/board" "$LG/../home/.local/state/task-hub/board-cache.json"; rm "$LG/board"; fi
if [ -f "$LG/raw" ]; then stty raw -echo; rm "$LG/raw"; fi
code=0
if [ -f "$LG/exit" ]; then code=$(cat "$LG/exit"); rm "$LG/exit"; fi
exit "$code"
"""


def build():
    """The task-rs binary, built once per process (cargo is quick when nothing changed)."""
    global _built
    if _built is None:
        env = {**os.environ, "CARGO_TARGET_DIR": str(RUST / "target")}
        r = subprocess.run(["cargo", "build", "--locked", "--quiet"], cwd=RUST, env=env, capture_output=True,
                           text=True, timeout=900, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise AssertionError("cargo build failed:\n" + r.stdout + r.stderr)
        _built = RUST / "target" / "debug" / "task-rs"
    return _built


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, stdin=subprocess.DEVNULL)


def item(number, title, status, repo="someone/app"):
    return {"id": f"item{number}", "updatedAt": f"2026-10-0{number % 9 + 1}T00:00:00Z",
            "content": {"number": number, "title": title, "url": f"https://github.com/someone/tasks/issues/{number}",
                        "body": "### Goal\nsomething", "state": "OPEN", "repository": {"nameWithOwner": "someone/tasks"},
                        "blockedBy": {"nodes": []}},
            "status": {"name": status}, "repo": {"text": repo}, "agent": {"text": ""}, "base": {"text": "main"}}


def snapshot(root):
    seen = {}
    for parent, dirs, files in os.walk(root):
        for f in files:
            path = Path(parent, f)
            seen[os.path.relpath(path, root)] = (path.stat().st_mtime_ns, path.read_bytes())
    return seen


@unittest.skipIf(WINDOWS, "needs a PTY")
@unittest.skipUnless(shutil.which("cargo"), "needs cargo to build task-rs")
class LazygitHandoffTest(unittest.TestCase):
    def setUp(self):
        self.binary = build()
        self.tmp = Path(tempfile.mkdtemp(prefix="task-rs-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home, self.lg = self.tmp / "home", self.tmp / "lg"
        self.lg.mkdir()
        config = self.home / ".config" / "task-hub" / "config.ini"
        config.parent.mkdir(parents=True)
        config.write_text("[board]\nproject = someone/7\nissues = someone/tasks\n")
        self.state = self.home / ".local" / "state" / "task-hub"
        (self.state / "runs").mkdir(parents=True)
        (self.state / "events.jsonl").write_text("")
        # the repository and one worktree per task, as task-hub makes them
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "base")
        self.worktrees = self.tmp / "worktrees"
        # a PATH with the fake lazygit and the tools task-rs and the fake need, but never a real lazygit
        self.bin, tools = self.tmp / "bin", self.tmp / "tools"
        self.bin.mkdir()
        tools.mkdir()
        for tool in ("git", "ps", "date", "sh", "stty", "cat", "cp", "rm", "pwd", "printf", "sleep"):
            found = shutil.which(tool)
            if found:
                (tools / tool).symlink_to(found)
        self.path = f"{self.bin}{os.pathsep}{tools}"
        self.gh_calls = self.tmp / "gh-calls"
        gh = self.tmp / "gh"
        gh.write_text(f'#!/bin/sh\necho "$@" >> "{self.gh_calls}"\nexit 1\n')
        gh.chmod(0o755)
        self.out, self.pid, self.fd, self.mark, self.screen = "", None, None, 0, Screen()

    def tearDown(self):
        if self.pid:
            try:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        if self.fd is not None:
            os.close(self.fd)

    # ---------- the board, the runs, the fake ----------

    def board(self, *items):
        return {"key": ["someone", "7", "someone/tasks"], "fetched_at": time.time(), "items": list(items)}

    def write_board(self, *items):
        (self.state / "board-cache.json").write_text(json.dumps(self.board(*items)))

    def worktree(self, number):
        wt = self.worktrees / str(number)
        git(self.repo, "worktree", "add", "-q", "-b", f"task/{number}", str(wt))
        return wt

    def run_file(self, number, worktree, **extra):
        run = {"repo": "someone/app", "worktree": str(worktree), "branch": f"task/{number}",
               "log": str(self.state / "logs" / f"{number}.log"), "started": "2026-10-01T00:00:00Z", "pid": 0, **extra}
        (self.state / "runs" / f"{number}.json").write_text(json.dumps(run))

    def install_fake(self):
        fake = self.bin / "lazygit"
        fake.write_text(FAKE_LAZYGIT)
        fake.chmod(0o755)

    def fake_ran(self):
        return (self.lg / "cwd").exists()

    def reset_fake(self):
        for f in self.lg.iterdir():
            f.unlink()

    # ---------- the terminal ----------

    def start(self, then_stty=False):
        """task-rs tui in a 40x140 PTY; with then_stty, the terminal's mode is noted after it quits."""
        env = {"HOME": str(self.home), "PATH": self.path, "TERM": "xterm-256color", "LG": str(self.lg),
               "TASK_GH": str(self.tmp / "gh"), "LANG": "en_US.UTF-8", "TMPDIR": str(self.tmp)}
        argv = [str(self.binary), "tui"]
        if then_stty:
            argv = ["/bin/sh", "-c", f'"$0" tui; echo "task-rs exited $?"; stty -a > "{self.lg}/after"; '
                                     f'echo AFTER-STTY', str(self.binary)]
        pid, fd = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
                os.execve(argv[0], argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.wait_screen("needs you")

    def read(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.fd], [], [], max(0.0, end - time.time()))
            if not ready:
                break
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace")
            self.out += text
            self.screen.feed(text)
            return True
        return False

    def expect(self, text, timeout=15):
        """Waits until text prints after the last key press (escape sequences aside); returns that raw output.
        For what is printed in one piece: the fake's lines, and the status line drawn again after a full redraw."""
        end = time.time() + timeout
        while text not in self.plain(self.out[self.mark:]):
            if time.time() > end:
                self.fail(f"{text!r} did not print in time; output since the key:\n{self.plain(self.out[self.mark:])}")
            self.read(0.2)
        return self.out[self.mark:]

    def wait_screen(self, text, where=None, timeout=15):
        """Waits until text is on the screen (in a region: the status line, the confirmation); returns that text."""
        end = time.time() + timeout
        while True:
            shown = where() if where else self.screen.text()
            if text in shown:
                return shown
            if time.time() > end:
                self.fail(f"{text!r} is not on the screen:\n{self.screen.text()}")
            self.read(0.2)

    def status(self):
        """The last 3 rows, where the keys and the status line are (it wraps when long), joined again."""
        return re.sub(r"\s+", " ", self.screen.text(rows=(ROWS - 3, ROWS)))

    def popup(self):
        """The confirmation's text and its border's titles, its wrapped lines joined again."""
        text = re.sub(r"[│─┌┐└┘]", " ", self.screen.text(rows=POPUP[:2], cols=POPUP[2:]))
        return re.sub(r"\s+", " ", text).strip()

    def settle(self, seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            self.read(0.1)

    def press(self, keys):
        self.mark = len(self.out)
        os.write(self.fd, keys.encode())

    @staticmethod
    def plain(s):
        return ESCAPE.sub("", s)

    def wait_exit(self, timeout=15):
        """The exit code, reading the terminal meanwhile: a full PTY would block the last writes."""
        end = time.time() + timeout
        while time.time() < end:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.read(0.3)
                self.pid = None
                return os.waitstatus_to_exitcode(status)
            self.read(0.1)
        self.fail(f"task-rs did not exit; the screen:\n{self.screen.text()}")

    def quit(self):
        self.press("q")
        return self.wait_exit()

    def assert_responsive(self, number):
        """The board takes single keys again (raw mode): l alone, no Enter, shows the selected card's log, and l
        again goes back."""
        self.press("l")
        self.wait_screen(f" Log #{number} ")
        self.press("l")
        self.wait_screen(" Details ")

    # ---------- the tests ----------

    def test_g_confirms_then_lends_the_terminal_to_lazygit_in_the_worktree_and_comes_back(self):
        wt5, wt6 = self.worktree(5), self.worktree(6)
        self.run_file(5, wt5)
        self.run_file(6, wt6)
        self.write_board(item(5, "Alpha", "In progress"), item(6, "Beta", "In review"))
        self.install_fake()
        before_runs, before_wt = snapshot(self.state / "runs"), snapshot(wt6)
        self.start()

        self.press("g")  # In review first: #6 is selected
        self.wait_screen("Open Lazygit? It can change Git")
        shown = self.wait_screen("Quit Lazygit to come back to the board.", self.popup)
        for words in ("task #6 Beta", "repo someone/app", "branch task/6", f"worktree {wt6}",
                      "The board stays read only. Lazygit is not: it can stage, commit, reset, check out, rebase and "
                      "push. This note does not stop it.", "d shows all the task changed since its base",
                      "g or ⏎ open Lazygit · any other key cancels"):
            self.assertIn(words, shown)
        self.assertNotIn("An agent is running", shown)
        self.assertFalse(self.fake_ran(), "it opened Lazygit before the confirmation")

        # meanwhile the board changes: a new card above #6, so its row moves
        (self.lg / "board").write_text(json.dumps(self.board(
            item(7, "Gamma", "In review"), item(5, "Alpha", "In progress"), item(6, "Beta", "In review"))))
        self.press("g")
        handed = self.expect("FAKE-LAZYGIT ready")
        self.assertIn(SHOW_CURSOR, handed)
        self.assertIn(LEAVE_ALT, handed)  # the board's screen is released before Lazygit starts
        self.assertIn("task-rs: Lazygit in #6", handed)
        self.press("hello there\r")  # typed into Lazygit, through the terminal
        back = self.expect("back from Lazygit in #6")
        self.assertIn("FAKE-LAZYGIT got: hello there", back)  # its stderr reaches the terminal too
        self.assertIn(ENTER_ALT, back)

        self.assertEqual((self.lg / "cwd").read_text().strip(), str(wt6.resolve()))
        self.assertEqual((self.lg / "args").read_text().split("\n")[0], "0")  # no arguments, no shell string
        self.assertEqual((self.lg / "tty").read_text().strip(), "yes")
        flags = (self.lg / "stty").read_text().split()
        self.assertIn("icanon", flags)  # task-rs's raw mode was off while Lazygit ran
        self.assertIn("echo", flags)
        self.assertEqual((self.lg / "input").read_text().strip(), "hello there")

        # the board is back in raw mode with #6 still selected: a second g goes to #6's worktree, not the new top card
        self.wait_screen("Gamma")
        self.assert_responsive("6")
        self.reset_fake()
        self.press("g")
        self.wait_screen("task #6 Beta", self.popup)
        self.press("g")
        self.expect("FAKE-LAZYGIT ready")
        self.press("\r")
        self.expect("back from Lazygit in #6")
        self.assertEqual((self.lg / "cwd").read_text().strip(), str(wt6.resolve()))

        self.assertEqual(self.quit(), 0)
        self.assertEqual(snapshot(self.state / "runs"), before_runs)  # no run file written
        self.assertEqual(snapshot(wt6), before_wt)  # task-rs ran no Git command that writes
        self.assertFalse(self.gh_calls.exists(), "task-rs called gh")

    def test_an_agent_running_in_the_worktree_is_a_warning_not_a_block(self):
        wt = self.worktree(5)
        agent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "_run"])
        self.addCleanup(lambda: (agent.kill(), agent.wait()))
        self.run_file(5, wt, pid=agent.pid, stage="agent")
        self.write_board(item(5, "Alpha", "In progress"))
        self.install_fake()
        self.start()
        self.press("g")
        shown = self.wait_screen("Quit Lazygit to come back to the board.", self.popup)
        self.assertIn("An agent is running in this worktree (agent). Inspect only: staging, committing, reset, "
                      "checkout and rebase can interfere with it.", shown)
        self.assertIn("This note does not stop it", shown)
        self.press("g")
        self.expect("FAKE-LAZYGIT ready")
        self.press("\r")
        self.expect("back from Lazygit in #5")
        self.assertEqual((self.lg / "cwd").read_text().strip(), str(wt.resolve()))
        self.assertIsNone(agent.poll(), "the agent was stopped")
        self.assertEqual(self.quit(), 0)

    def test_any_other_key_cancels(self):
        self.run_file(5, self.worktree(5))
        self.write_board(item(5, "Alpha", "In progress"))
        self.install_fake()
        self.start()
        self.press("g")
        self.wait_screen("Open Lazygit?")
        self.press("x")
        self.wait_screen("Lazygit not opened", self.status)
        self.assertNotIn("Open Lazygit?", self.screen.text())
        self.press("g")
        self.wait_screen("Open Lazygit?")
        self.press("\x1b")
        self.settle(1)
        self.assertNotIn("Open Lazygit?", self.screen.text())
        self.assertFalse(self.fake_ran())
        self.assertEqual(self.quit(), 0)

    def test_nonzero_exit_and_a_crash_in_raw_mode_leave_a_usable_board_and_terminal(self):
        self.run_file(5, self.worktree(5))
        self.write_board(item(5, "Alpha", "In progress"))
        self.install_fake()
        self.start(then_stty=True)
        (self.lg / "exit").write_text("3")
        (self.lg / "raw").write_text("")  # it leaves the terminal in raw mode without echo, as a crash would
        self.press("gg")
        self.expect("FAKE-LAZYGIT ready")
        self.press("\r")
        self.expect("FAKE-LAZYGIT got:")  # what it printed stays on the screen until Enter
        self.expect("Lazygit did not end normally (see above). Press Enter to return to the board.")
        self.settle(0.5)
        self.assertNotIn(ENTER_ALT, self.out[self.mark:])
        self.press("\r")
        back = self.expect("Lazygit exited with code 3 in #5")
        self.assertIn(ENTER_ALT, back)
        self.assert_responsive("5")
        self.press("q")
        self.expect("AFTER-STTY")
        after = self.out[self.mark:]
        self.assertIn("task-rs exited 0", after)
        self.assertIn(LEAVE_ALT, after)
        flags = (self.lg / "after").read_text().split()
        self.assertIn("icanon", flags)  # the shell gets back the terminal as it was before the TUI
        self.assertIn("echo", flags)
        self.assertEqual(self.wait_exit(), 0)

    def test_lazygit_that_cannot_start(self):
        self.run_file(5, self.worktree(5))
        self.write_board(item(5, "Alpha", "In progress"))
        broken = self.bin / "lazygit"
        broken.write_text("#!/nonexistent/interpreter\n")
        broken.chmod(0o755)
        self.start()
        self.press("gg")
        back = self.expect("cannot start Lazygit")
        self.assertIn(ENTER_ALT, back)
        self.assert_responsive("5")
        self.assertEqual(self.quit(), 0)

    def test_missing_lazygit_is_explained_and_nothing_is_handed_over(self):
        self.run_file(5, self.worktree(5))
        self.write_board(item(5, "Alpha", "In progress"))
        self.start()
        self.press("gg")
        self.wait_screen("lazygit is not on PATH: install it (brew install lazygit, see rust/README.md). Nothing opened",
                         self.status)
        self.assertNotIn(LEAVE_ALT, self.out)
        self.assert_responsive("5")
        self.assertEqual(self.quit(), 0)

    def test_no_worktree_never_opens_another_checkout(self):
        removed = self.worktree(5)
        self.run_file(5, removed)
        git(self.repo, "worktree", "remove", str(removed))  # task watch removed it when the task was Done
        inside = self.repo / "sub"  # a directory inside the main checkout, not a worktree of its own
        inside.mkdir()
        self.run_file(6, inside)
        plain_dir = self.tmp / "plain"  # not Git at all
        plain_dir.mkdir()
        self.run_file(7, plain_dir)
        # #8 has no run on this machine
        self.run_file(9, self.repo)  # the repository's main checkout
        self.write_board(item(5, "Alpha", "In review"), item(6, "Beta", "Blocked"),
                         item(7, "Gamma", "In progress"), item(8, "Delta", "Ready"), item(9, "Echo", "wait for merge"))
        self.install_fake()
        self.start()
        for expected in ("the worktree of #5 is gone", "is inside another checkout", "is not a Git worktree",
                         "no worktree recorded for #8", "is a main checkout, not a task worktree"):
            self.press("g")
            self.wait_screen(expected, self.status)
            self.assertNotIn("Open Lazygit?", self.screen.text())
            self.press("j")
        self.assertFalse(self.fake_ran(), "Lazygit opened somewhere")
        self.assertEqual(self.quit(), 0)

    def test_the_worktree_is_checked_again_after_the_confirmation(self):
        wt = self.worktree(5)
        self.run_file(5, wt)
        self.write_board(item(5, "Alpha", "In progress"))
        self.install_fake()
        self.start()
        self.press("g")
        self.wait_screen("Open Lazygit?")
        git(self.repo, "worktree", "remove", str(wt))  # removed while the confirmation is up
        self.press("g")
        self.wait_screen("the worktree of #5 is gone", self.status)
        self.assertFalse(self.fake_ran())
        self.assertEqual(self.quit(), 0)

    def test_coming_back_when_the_task_is_gone_or_the_board_is_empty(self):
        wt5, wt6 = self.worktree(5), self.worktree(6)
        self.run_file(5, wt5)
        self.run_file(6, wt6)
        self.write_board(item(5, "Alpha", "In progress"), item(6, "Beta", "In review"))
        self.install_fake()
        self.start()
        (self.lg / "board").write_text(json.dumps(self.board(item(5, "Alpha", "In progress"))))  # #6 is Done
        self.press("gg")
        self.expect("FAKE-LAZYGIT ready")
        self.press("\r")
        self.expect("back from Lazygit in #6")
        self.reset_fake()
        self.press("g")  # the remaining card is selected
        self.wait_screen("task #5 Alpha", self.popup)
        (self.lg / "board").write_text(json.dumps(self.board()))  # and then nothing is open
        self.press("g")
        self.expect("FAKE-LAZYGIT ready")
        self.press("\r")
        self.expect("back from Lazygit in #5")
        self.wait_screen("no open cards")
        self.press("g")
        self.wait_screen("no card selected: Lazygit not opened", self.status)
        self.assertEqual(self.quit(), 0)


if __name__ == "__main__":
    unittest.main()
