"""task-rs tui, driven the way a person does, in a real terminal (a PTY): `g` (Lazygit in the selected task's worktree)
and the full-screen reader (Enter, d, l).

Each test builds task-rs (cargo, debug) once, then runs `task-rs tui` in a PTY with a temporary HOME: a config, a
local board, runs/<id>.json, logs and real git worktrees. `lazygit` on PATH is a fake that records where and how it ran
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

    def __init__(self, rows=ROWS, cols=COLS):
        self.rows, self.cols = rows, cols
        self.grid = [[" "] * cols for _ in range(rows)]
        self.row = self.col = 0
        self.pending = ""

    def feed(self, data):
        data, self.pending = self.pending + data, ""
        at = 0
        while at < len(data):
            c = data[at]
            if c == "\x1b":
                m = ESCAPE.match(data, at)
                # a sequence cut by the read matches only the catch-all "\x1b.": wait for its end too
                cut = m and m.end() == at + 2 and data[at + 1] in "[]()" and len(data) - at < 64
                if not m or cut:
                    self.pending = data[at:]  # the rest comes in the next read
                    return
                if m.group(3) == "H":
                    nums = [int(n) if n else 1 for n in (m.group(1) or "1;1").split(";")] + [1]
                    self.row, self.col = min(nums[0], self.rows) - 1, min(nums[1], self.cols) - 1
                elif m.group(3) == "J" and m.group(1) in ("2", "3"):
                    self.grid = [[" "] * self.cols for _ in range(self.rows)]
                at = m.end()
                continue
            if c == "\r":
                self.col = 0
            elif c == "\n":
                self.row = min(self.row + 1, self.rows - 1)
            elif c >= " ":
                if self.col < self.cols:
                    self.grid[self.row][self.col] = c
                self.col += 1
            at += 1

    def text(self, rows=None, cols=None):
        rows, cols = rows or (0, self.rows), cols or (0, self.cols)
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
class TuiCase(unittest.TestCase):
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
        # the terminal is closed before the wait: a killed process can hang exiting while its output goes unread
        if self.pid:
            try:
                os.kill(self.pid, 9)
            except ProcessLookupError:
                pass
        if self.fd is not None:
            os.close(self.fd)
        end = time.time() + 10
        while self.pid and time.time() < end:
            try:
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    break
            except ChildProcessError:
                break
            time.sleep(0.1)

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

    def start(self, then_stty=False, rows=ROWS, cols=COLS):
        """task-rs tui in a PTY (40x140 unless told); with then_stty, the terminal's mode is noted after it quits."""
        env = {"HOME": str(self.home), "PATH": self.path, "TERM": "xterm-256color", "LG": str(self.lg),
               "TASK_GH": str(self.tmp / "gh"), "LANG": "en_US.UTF-8", "TMPDIR": str(self.tmp)}
        argv = [str(self.binary), "tui"]
        if then_stty:
            argv = ["/bin/sh", "-c", f'"$0" tui; echo "task-rs exited $?"; stty -a > "{self.lg}/after"; '
                                     f'echo AFTER-STTY', str(self.binary)]
        pid, fd = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                os.execve(argv[0], argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd, self.screen = pid, fd, Screen(rows, cols)
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
                while self.read(0.1):  # the rest of the frame that showed it
                    pass
                shown = where() if where else self.screen.text()
                if text in shown:
                    return shown
            if time.time() > end:
                self.fail(f"{text!r} is not on the screen:\n{self.screen.text()}")
            self.read(0.2)

    def status(self):
        """The last 3 rows, where the keys and the status line are (it wraps when long), joined again."""
        return re.sub(r"\s+", " ", self.screen.text(rows=(self.screen.rows - 3, self.screen.rows)))

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
        """The board takes single keys again (raw mode): l alone, no Enter, opens the selected card's log in the
        reader, and Esc goes back to the board."""
        self.press("l")
        self.wait_screen(f"#{number} ", self.header)
        self.wait_screen("Log", self.header)
        self.press("\x1b")
        self.wait_screen(" Details ")

    def header(self):
        return self.screen.text(rows=(0, 1))


class LazygitHandoffTest(TuiCase):

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


WORDS = " ".join(f"w{n:04}" for n in range(1, 601))  # one logical line, 3600 characters: many rows when wrapped
WHEEL_UP, WHEEL_DOWN = "\x1b[<64;20;10M", "\x1b[<65;20;10M"  # SGR mouse reports, as a terminal sends them
UP, DOWN, LEFT, RIGHT = "\x1b[A", "\x1b[B", "\x1b[D", "\x1b[C"
PGUP, PGDN, HOME, END = "\x1b[5~", "\x1b[6~", "\x1b[H", "\x1b[F"


def with_body(it, body):
    it["content"]["body"] = body
    return it


class ReaderTest(TuiCase):
    """The full-screen reader in a small terminal: Enter, d and l open the selected task's Issue, diff and log over
    the whole screen; arrows, pages, Home, End and the wheel scroll it and never change the task; Esc goes back."""

    SMALL = (20, 80)

    def setUp(self):
        super().setUp()
        self.wt = self.worktree(5)
        self.run_file(5, self.wt)
        self.log = self.state / "logs" / "5.log"
        self.log.parent.mkdir()
        self.issue = f"### Goal\nfirst line of the Issue\n{WORDS} END-OF-LONG-LINE\n\nlast line of the Issue"
        self.write_board(with_body(item(5, "Alpha", "In review"), self.issue), item(6, "Beta", "Blocked"))
        self.before = snapshot(self.state / "runs")

    def body(self):
        """The rows between the header and the footer's 3 rows, as text."""
        return self.screen.text(rows=(1, self.screen.rows - 3))

    def page_through(self, key, until, limit=200):
        """Presses key until `until` is on the screen, collecting each screen it showed (the header says where)."""
        seen = self.screen.text()
        for _ in range(limit):
            if until in self.screen.text():
                return seen
            before = self.header()
            self.press(key)
            end = time.time() + 3
            while self.header() == before and time.time() < end:
                self.read(0.1)
            while self.read(0.1):  # the rest of that frame
                pass
            seen += "\n" + self.screen.text()
        self.fail(f"{until!r} never came on the screen; it shows:\n{self.screen.text()}")

    def resize(self, rows, cols):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.screen = Screen(rows, cols)  # ratatui clears and draws everything again at the new size
        self.settle(1)

    def assert_no_gh_and_read_only(self):
        self.assertFalse(self.gh_calls.exists(), "task-rs called gh")
        self.assertEqual(snapshot(self.state / "runs"), self.before)  # no run file written

    # ---------- the tests ----------

    def test_issue_opens_full_screen_and_every_wrapped_word_is_reachable(self):
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("\r")
        self.wait_screen("Issue", self.header)
        self.settle(0.5)  # the whole screen drawn
        self.assertIn("#5 Alpha", self.header())
        shown = self.screen.text()
        self.assertNotIn(" Board ", shown)  # the board and the events make room for the Issue
        self.assertNotIn(" Events ", shown)
        self.assertIn("Esc back", self.status())
        self.assertIn("first line of the Issue", self.body())
        # paging down shows every word of the long line, then its end and the last line
        seen = self.page_through(PGDN, "last line of the Issue")
        missing = [w for w in WORDS.split() if w not in seen]
        self.assertEqual(missing, [], "words of the wrapped line that paging never showed")
        self.assertIn("END-OF-LONG-LINE", seen)
        # paging up goes back to the top
        self.page_through(PGUP, "first line of the Issue")
        self.press(END)
        self.wait_screen("last line of the Issue")
        self.press(HOME)
        self.wait_screen("first line of the Issue")
        self.assertNotIn("last line of the Issue", self.screen.text())
        self.assert_no_gh_and_read_only()
        self.assertEqual(self.quit(), 0)

    def test_arrows_and_jk_scroll_the_reader_and_never_change_the_task(self):
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("\r")
        self.wait_screen("first line of the Issue")
        for key in (DOWN, "j") * 3:  # past the title, the link and the heading above it
            self.press(key)
            self.settle(0.2)
        self.assertIn("#5 Alpha", self.header())  # still #5, never #6 Beta
        self.assertNotIn("Beta", self.screen.text())
        self.assertNotIn("first line of the Issue", self.screen.text())  # it scrolled instead
        for key in (UP, "k") * 3:
            self.press(key)
            self.settle(0.2)
        self.wait_screen("first line of the Issue")
        self.assertIn("#5 Alpha", self.header())
        # the wheel scrolls too, without changing the task: the terminal reports it in the reader only
        self.assertIn("\x1b[?1000h", self.out)
        for _ in range(4):
            self.press(WHEEL_DOWN)
            self.settle(0.2)
        self.assertNotIn("first line of the Issue", self.screen.text())
        self.assertIn("#5 Alpha", self.header())
        for _ in range(4):
            self.press(WHEEL_UP)
            self.settle(0.2)
        self.wait_screen("first line of the Issue")
        # Esc: the board again, with #5 still selected
        self.press("\x1b")
        self.wait_screen(" Board ")
        self.assertIn("\x1b[?1000l", self.out[self.mark:])  # the board leaves the mouse to the terminal again
        self.assertIn("▶ #5", self.screen.text())
        self.assertIn("⏎ issue", self.status())
        self.assertEqual(self.quit(), 0)

    def test_the_diff_shows_all_lines_and_scrolls_sideways_to_the_end_of_a_wide_line(self):
        (self.wt / "wide.txt").write_text("".join(f"line {n:03}\n" for n in range(1, 200)))
        git(self.wt, "add", "wide.txt")
        git(self.wt, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "committed by the agent")
        (self.wt / "uncommitted.txt").write_text("x" * 250 + " RIGHT-END-MARKER\n")
        git(self.wt, "add", "-N", "uncommitted.txt")  # intent to add: in the diff, staged nothing
        git(self.repo, "update-ref", "refs/remotes/origin/main", "main")
        time.sleep(1.1)
        os.utime(self.wt / "wide.txt")  # newer, same content: git diff would refresh the index and write it
        git_dir = self.repo / ".git" / "worktrees" / "5"
        before = snapshot(self.wt), snapshot(git_dir)
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("d")
        self.wait_screen("Diff", self.header)
        self.assertIn("#5 Alpha", self.header())
        self.assertNotIn(" Board ", self.screen.text())
        self.wait_screen("wide.txt")
        # all lines, committed and not: the end of the committed file (git lists it after the uncommitted one)
        self.press(END)
        self.wait_screen("+line 199")
        self.press(HOME)
        self.wait_screen("uncommitted.txt")
        self.assertNotIn("RIGHT-END-MARKER", self.screen.text())  # the wide line goes past the right edge
        self.page_through(RIGHT, "RIGHT-END-MARKER", limit=80)
        self.assertIn("#5 Alpha", self.header())
        self.page_through(LEFT, "diff --git", limit=80)
        self.assertEqual(self.quit(), 0)
        self.assert_no_gh_and_read_only()
        self.assertEqual((snapshot(self.wt), snapshot(git_dir)), before)  # no git add, no index written, no lock

    def test_the_log_follows_new_output_only_at_the_bottom(self):
        self.log.write_text("".join(f"log line {n:03}\n" for n in range(1, 301)))
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("l")
        self.wait_screen("log line 300")  # it opens at the end
        self.assertIn("Log", self.header())
        with self.log.open("a") as f:
            f.write("log line 301 FOLLOWED\n")
        self.wait_screen("log line 301 FOLLOWED", timeout=5)  # at the bottom, it follows
        # scroll up: following pauses, and new output does not pull the view down
        self.press(PGUP)
        self.settle(0.3)
        self.assertNotIn("FOLLOWED", self.screen.text())
        top = self.body().split("\n")[0]
        with self.log.open("a") as f:
            f.write("log line 302 NOT-PULLED\n")
        self.settle(2)
        self.assertNotIn("NOT-PULLED", self.screen.text())
        self.assertEqual(self.body().split("\n")[0], top, "the view moved while reading older output")
        self.assertIn("paused", self.header())
        # back at the bottom, it follows again
        self.press(END)
        self.wait_screen("log line 302 NOT-PULLED")
        with self.log.open("a") as f:
            f.write("log line 303 FOLLOWED AGAIN\n")
        self.wait_screen("log line 303 FOLLOWED AGAIN", timeout=5)
        self.assertEqual(self.quit(), 0)

    def test_a_reload_then_a_resize_keeps_the_line_at_the_top(self):
        self.log.write_text("".join(f"log line {n:03} " + "x" * 90 + "\n" for n in range(1, 301)))  # 2 rows at 80

        def top_line():
            """The log line on the top row, which may be its second row."""
            rows = self.body().split("\n")
            first = next(i for i, r in enumerate(rows) if r.startswith("log line "))
            return int(rows[first].split()[2]) - (1 if first else 0)

        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("l")
        self.wait_screen("log line 300")
        for _ in range(10):
            self.press(PGUP)
        self.settle(0.5)
        top = top_line()
        self.assertLess(top, 250)
        with self.log.open("a") as f:
            f.write("log line 301 NEW\n")
        self.settle(1)
        self.assertEqual(top_line(), top)  # new output did not move it
        with self.log.open("a") as f:  # read again in the same frame as the resize
            f.write("log line 302 NEW\n")
        self.resize(20, 120)
        self.wait_screen("paused", self.header)
        self.assertEqual(top_line(), top, "the resize moved the reader to another line")
        self.assertTrue(self.body().startswith(f"log line {top:03}"))
        self.assertEqual(self.quit(), 0)

    def test_a_view_resized_away_comes_back_at_the_same_words(self):
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("\r")
        self.wait_screen("first line of the Issue")
        self.press(PGDN)
        self.press(PGDN)
        self.wait_screen("33-48", self.header)
        first = int(self.body().split()[0][1:])  # the first word on the top row, w0352 -> 352
        self.press("l")
        self.wait_screen("Log", self.header)
        self.resize(20, 120)
        self.press("\r")
        self.wait_screen("Issue", self.header)
        now = int(self.body().split()[0][1:])
        # within a long line the place is kept in proportion: up to 2 rows (40 words at 120 columns) off
        self.assertTrue(first - 40 <= now <= first + 20, f"came back at w{now:04}, not near w{first:04}")
        self.assertEqual(self.quit(), 0)

    def test_the_diff_never_writes_the_index_even_when_git_would_refresh_it(self):
        (self.wt / "a.txt").write_text("a\n")
        git(self.wt, "add", "a.txt")
        git(self.wt, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "c")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "task/5")  # nothing committed since the base
        (self.wt / "b.txt").write_text("b\n")
        git(self.wt, "add", "-N", "b.txt")
        time.sleep(1.1)
        os.utime(self.wt / "a.txt")  # same content, newer time: git diff refreshes the index and writes it back
        git_dir = self.repo / ".git" / "worktrees" / "5"
        before = snapshot(git_dir)
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("d")
        self.wait_screen("+b")  # the uncommitted change, read through a copy of the index
        self.assertNotIn("a.txt", self.screen.text())
        self.assertEqual(self.quit(), 0)
        self.assertEqual(snapshot(git_dir), before)
        self.assertEqual([f.name for f in self.tmp.glob("task-rs-*.index*")], [])  # the copy is removed

    def test_enter_d_l_switch_the_reader_and_keep_each_position(self):
        self.log.write_text("".join(f"log line {n:03}\n" for n in range(1, 301)))
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("\r")
        self.wait_screen("first line of the Issue")
        self.press(END)
        self.wait_screen("last line of the Issue")
        self.press("l")
        self.wait_screen("log line 300")
        self.press("d")
        self.wait_screen("Diff", self.header)
        self.press("\r")
        self.wait_screen("Issue", self.header)
        self.wait_screen("last line of the Issue")  # where it was
        self.assertIn("#5 Alpha", self.header())
        self.assertEqual(self.quit(), 0)

    def test_resize_and_shrinking_content_keep_a_valid_position(self):
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("\r")
        self.press(END)
        self.wait_screen("last line of the Issue")
        self.resize(30, 120)
        self.wait_screen("last line of the Issue")
        self.resize(14, 50)
        self.wait_screen("last line of the Issue")
        self.press(PGUP)
        self.settle(0.3)
        self.press(END)
        self.wait_screen("last line of the Issue")
        # the Issue gets much shorter while the end of the old one is shown
        self.write_board(with_body(item(5, "Alpha", "In review"), "### Goal\nshort now"), item(6, "Beta", "Blocked"))
        self.wait_screen("short now", timeout=5)
        self.assertIn("#5 Alpha", self.header())
        self.press(PGUP)
        self.press(PGDN)
        self.press(DOWN)
        self.wait_screen("short now")
        self.assertEqual(self.quit(), 0)

    def test_a_task_that_leaves_the_board_is_not_replaced_by_another(self):
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("\r")
        self.wait_screen("first line of the Issue")
        self.write_board(item(6, "Beta", "Blocked"))  # #5 is Done
        self.wait_screen("no longer on the local board", timeout=5)
        self.assertIn("#5", self.header())
        self.assertNotIn("Beta", self.screen.text())
        self.press(DOWN)
        self.press("l")
        self.settle(0.5)
        self.assertNotIn("Beta", self.screen.text())
        self.press("\x1b")
        self.wait_screen(" Board ")
        self.assertIn("▶ #6", self.screen.text())  # back on the board, a card that is still there
        self.assertEqual(self.quit(), 0)

    def test_no_worktree_no_run_and_no_lazygit_are_explained_in_the_reader(self):
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("j")  # #6 has no run on this machine
        self.press("d")
        self.wait_screen("no worktree for this task on this machine")
        self.assertIn("#6 Beta", self.header())
        self.press("l")
        self.wait_screen("no run of this task on this machine")
        self.press("g")
        self.wait_screen("no worktree recorded for #6", self.status)
        self.assertIn("#6 Beta", self.header())  # still reading #6
        self.press("\x1b")
        self.wait_screen(" Board ")
        self.assertIn("▶ #6", self.screen.text())
        self.press("k")  # #5 has a worktree, but there is no lazygit on PATH
        self.press("\r")
        self.wait_screen("first line of the Issue")
        self.press("gg")
        self.wait_screen("lazygit is not on PATH", self.status)
        self.assertIn("Issue", self.header())
        self.assertIn("#5 Alpha", self.header())
        self.assertNotIn(LEAVE_ALT, self.out)  # the terminal was never handed over
        self.assertEqual(self.quit(), 0)
        self.assert_no_gh_and_read_only()

    def test_g_from_the_reader_comes_back_to_the_same_view_and_position(self):
        self.install_fake()
        self.start(rows=self.SMALL[0], cols=self.SMALL[1])
        self.press("\r")
        self.wait_screen("first line of the Issue")
        self.press(PGDN)
        self.settle(0.3)
        before = self.body()
        self.assertNotIn("first line of the Issue", before)
        self.press("g")
        self.wait_screen("Open Lazygit?")
        self.press("g")
        self.expect("FAKE-LAZYGIT ready")
        self.press("\r")
        self.expect("back from Lazygit in #5")
        self.wait_screen("Issue", self.header)
        self.settle(0.5)
        self.assertEqual(self.body(), before, "the reader did not come back where it was")
        self.assertEqual((self.lg / "cwd").read_text().strip(), str(self.wt.resolve()))
        self.press("\x1b")
        self.wait_screen(" Board ")
        self.assertIn("▶ #5", self.screen.text())
        self.assertEqual(self.quit(), 0)
        self.assert_no_gh_and_read_only()


class HerdrPaneTest(TuiCase):
    """`task-rs tui` started inside herdr with no terminal (by an agent): it opens a herdr pane to the right and runs
    there. `herdr` (HERDR_BIN_PATH) is a fake that notes each call and answers `pane split` with a new pane's id."""

    def setUp(self):
        super().setUp()
        self.write_board(item(1, "one", "Ready"))
        self.herdr_calls = self.tmp / "herdr-calls"
        herdr = self.tmp / "herdr"
        herdr.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{self.herdr_calls}"\n'
                         'case "$1 $2" in\n'
                         '  "pane split") [ -n "$HERDR_FAIL" ] && { echo "no such pane" >&2; exit 3; }\n'
                         '    echo \'{"result":{"pane":{"pane_id":"p9"}}}\' ;;\n'
                         'esac\n')
        herdr.chmod(0o755)
        self.herdr = herdr

    def tui(self, **env):
        return subprocess.run([str(self.binary), "tui"], cwd=self.repo, capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL,
                              env={"HOME": str(self.home), "PATH": self.path, "TASK_GH": str(self.tmp / "gh"),
                                   "HERDR_BIN_PATH": str(self.herdr), **env})

    def calls(self):
        return self.herdr_calls.read_text().splitlines() if self.herdr_calls.exists() else []

    def test_with_no_terminal_it_opens_a_pane_to_the_right_and_runs_the_same_binary_there(self):
        r = self.tui(HERDR_PANE_ID="p1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "tui: opened in herdr pane p9, to the right of p1")
        self.assertEqual(self.calls(), [
            f"pane split --pane p1 --direction right --cwd {os.path.realpath(self.repo)} --focus",
            f"pane run p9 '{self.binary}' tui"])
        self.assertFalse(self.gh_calls.exists())

    def test_task_herdr_0_and_no_herdr_pane_leave_herdr_alone(self):
        for env in ({"HERDR_PANE_ID": "p1", "TASK_HERDR": "0"}, {}):
            with self.subTest(env):
                r = self.tui(**env)
                self.assertNotEqual(r.returncode, 0)  # no terminal to draw on
                self.assertEqual(self.calls(), [])

    def test_a_failing_herdr_is_an_error_not_a_hang(self):
        r = self.tui(HERDR_PANE_ID="p1", HERDR_FAIL="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error: herdr pane split failed: no such pane", r.stdout)  # task-rs says errors on stdout
        self.assertEqual(len(self.calls()), 1)


class ClosedPipeTest(TuiCase):
    """Output into a pipe whose reader is gone (`task-rs list --watch | head -1`, a monitor that stopped): task-rs
    stops quietly, never with a panic and a core dump."""

    def run_into_closed_pipe(self, *args, stream="stdout"):
        r, w = os.pipe()
        os.close(r)
        pipes = {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL, stream: w}
        try:
            return subprocess.run([str(self.binary), *args], cwd=self.tmp, timeout=30, stdin=subprocess.DEVNULL,
                                  env={"HOME": str(self.home), "PATH": self.path, "TASK_GH": str(self.tmp / "gh"),
                                       "TASK_WATCH_ONCE": "1"}, **pipes)
        finally:
            os.close(w)

    def test_every_command_stops_quietly(self):
        self.write_board(item(5, "Alpha", "Ready"))
        (self.state / "events.jsonl").write_text('{"id": 5, "event": "Done", "title": "Alpha"}\n')
        for args, stream, code in [(["list"], "stdout", 0), (["list", "--watch"], "stdout", 0),
                                   (["events"], "stdout", 0), (["--help"], "stdout", 0), (["--version"], "stdout", 0),
                                   (["list"], "stderr", 0), (["nope"], "stdout", 2)]:
            with self.subTest(args=args, stream=stream):
                r = self.run_into_closed_pipe(*args, stream=stream)
                self.assertEqual(r.returncode, code)  # a signal (the panic's abort) would be negative
                if stream == "stderr":  # the note on stderr is lost, never the board on stdout
                    self.assertIn(b"counts: Backlog=0, Ready=1", r.stdout)


if __name__ == "__main__":
    unittest.main()
