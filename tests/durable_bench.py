#!/usr/bin/env python3
"""Compare the three ways to resume a run cut short: python3 tests/durable_bench.py [options]
(docs/durable-runs-comparison.md; docs/architecture/designs/durable-runs.md, "比べる実験")

A: pi's own saved conversation (`--session-id {session}` in [agents] and [resume]); B: the Pi Durable runner
(durable/); C: a new session (no {session}, no [resume]). Each trial gives one card the same small Python task (fix
the failing tests, run a slow test, run a release-note script exactly once) and cuts its run short the same way:
T1 during the model's answer, T2 during the slow test, T3 just after the first fix is written, T4 once the whole suite
passed; K1 the agent's process group killed (kill -9), K2 `_run` and the agent killed (the next sync resumes it), K3
everything killed, `task watch` too, which then starts again (a restart, T2 only). Each method gets 3 trials not cut
short + T1-T4 x K1, K2 twice (16) + T2 x K3 twice: 21, 63 in all. One JSON line per trial goes to --out.

Everything runs in a throwaway HOME with a fake GitHub (test_task.py's FAKE_GH) and a local bare repository: the real
config, state and board are never read or written, and GitHub is never called. Only the agents are real: pi (A, C) and
durable/dist/cli.js (B), on the model --model with pi's own login (read, never printed or copied:
$PI_CODING_AGENT_DIR or ~/.pi/agent). The trials use the ChatGPT subscription: a few hundred thousand tokens each.
Not a test (the name does not start with test_): run it by hand, a few trials at a time (--limit), as often as needed;
trials already in --out are skipped, and each trial's log, conversation and diff go to <out>-artifacts/<trial>/.
--report turns --out into the tables of docs/durable-runs-comparison.md.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import site
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
BIN = REPO / "bin" / "task"
DURABLE = REPO / "durable"
sys.path.insert(0, str(TESTS))
from bench import machine  # noqa: E402
from test_task import FAKE_GH, STATUS_OPTIONS  # noqa: E402

METHODS = {"A": "pi-a", "B": "durable", "C": "pi-c"}  # method: the agent's name in [agents]
TIMINGS = ("T1", "T2", "T3", "T4")
MODEL, THINKING = "openai-codex/gpt-6-luna", "medium"  # durable-runs.md, decision 7: the same for A, B and C
T1_DELAY = 2.0  # seconds after the first tool call shows in the log (durable-runs.md: "次のターンの途中のはず")
POLL = 0.25
DONE = ("In review", "Blocked", "Done")
WORK = Path(tempfile.gettempdir()) / "durable-bench"


def trials():
    """The 63 trials, as (id, method, timing, kill, repetition): A, B and C of one cut next to each other."""
    specs = [("none", "", rep) for rep in (1, 2, 3)]
    specs += [(t, k, rep) for t in TIMINGS for k in ("K1", "K2") for rep in (1, 2)]
    specs += [("T2", "K3", rep) for rep in (1, 2)]
    return [(f"{m}-{t}-{k}-{rep}" if k else f"{m}-none-{rep}", m, t if k else "", k, rep)
            for t, k, rep in specs for m in METHODS]


# ---------- the task: a small Python project whose answer pytest checks ----------

GOAL = """The tests of this small Python project fail. Make them pass.

- Run the whole suite with `python3 -m pytest -q` in the repository root. It takes about 20 seconds:
  `tests/test_slow.py` is slow on purpose.
- The bugs are in `calc/`. Do not change the tests.
- Once the whole suite passes, run `python3 scripts/add_changelog.py` exactly once, to add the release note to
  `CHANGELOG.md`. Each run adds the line again, so a second run is a mistake.
- Then write the report as usual."""
CHANGELOG_LINE = "- Fixed mean, median, mode and slug."
SUITE = 8  # tests in the whole suite: .tests-passed is written only when all of them ran and passed

STATS = '''"""Small statistics helpers."""


def mean(values):
    """The arithmetic mean of a non-empty list."""
    return sum(values) / (len(values) + 1)


def median(values):
    """The middle value of a non-empty list; for an even count, the mean of the two middle values."""
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return s[mid]


def mode(values):
    """The most common value; on a tie, the smallest of them."""
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    best = max(counts.values())
    return max(v for v, c in counts.items() if c == best)
'''
TEXT = '''"""Text helpers."""
import re


def slug(title):
    """A URL slug: the words of the title in lower case, joined by single hyphens, without punctuation."""
    return "-".join(re.findall(r"[A-Za-z0-9]+", title))
'''
FIXED = {"calc/stats.py": STATS.replace("(len(values) + 1)", "len(values)")
         .replace("        return s[mid]\n    return s[mid]", "        return s[mid]\n    return (s[mid - 1] + s[mid]) / 2")
         .replace("return max(v for v", "return min(v for v"),
         "calc/text.py": TEXT.replace('"-".join(re.findall(r"[A-Za-z0-9]+", title))',
                                      '"-".join(re.findall(r"[A-Za-z0-9]+", title)).lower()')}


def project(counter):
    """The files of the task's repository. `counter` is a file outside the worktree: the slow test and the release
    note script add a line to it each time they run (start and end, with the pid), whatever the agent does."""
    note = (f"COUNTER = os.environ.get(\"BENCH_COUNTER\", {str(counter)!r})\n\n\n"
            "def note(word):\n    with open(COUNTER, \"a\") as f:\n"
            "        f.write(f\"{word} {os.getpid()} {time.time():.3f}\\n\")\n")
    return {
        "README.md": "# calc\n\nSmall helpers. `python3 -m pytest -q` runs the tests.\n",
        "CHANGELOG.md": "# Changelog\n\n## Unreleased\n\n",
        ".gitignore": "__pycache__/\n.pytest_cache/\n.running\n.tests-passed\n",
        "calc/__init__.py": "",
        "calc/stats.py": STATS,
        "calc/text.py": TEXT,
        "conftest.py": (
            '"""Writes .tests-passed when the whole suite ran and passed."""\nimport pathlib\n\n'
            f"ROOT = pathlib.Path(__file__).resolve().parent\nSUITE = {SUITE}\n\n\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    if exitstatus == 0 and session.testscollected >= SUITE:\n"
            '        (ROOT / ".tests-passed").write_text("ok\\n")\n'),
        "tests/test_stats.py": (
            "from calc.stats import mean, median, mode\n\n\n"
            "def test_mean():\n    assert mean([1, 2, 3, 4]) == 2.5\n\n\n"
            "def test_median_odd():\n    assert median([5, 1, 3]) == 3\n\n\n"
            "def test_median_even():\n    assert median([4, 1, 3, 2]) == 2.5\n\n\n"
            "def test_mode():\n    assert mode([3, 1, 3, 2]) == 3\n\n\n"
            "def test_mode_tie():\n    assert mode([2, 5, 5, 2, 9]) == 2\n"),
        "tests/test_text.py": (
            "from calc.text import slug\n\n\n"
            "def test_slug():\n    assert slug(\"Hello World\") == \"hello-world\"\n\n\n"
            "def test_slug_punctuation():\n    assert slug(\"  Fix: mean, median & mode!  \") == \"fix-mean-median-mode\"\n"),
        "tests/test_slow.py": (
            '"""The slow part of the suite: the totals of a long report (about 20 seconds)."""\n'
            "import os\nimport pathlib\nimport time\n\nfrom calc.stats import mean, median\n\n"
            "ROOT = pathlib.Path(__file__).resolve().parent.parent\n" + note + "\n\n"
            "def test_report_totals():\n    note(\"start\")\n    running = ROOT / \".running\"\n"
            "    running.write_text(str(os.getpid()))\n    try:\n        values = []\n"
            "        for i in range(20):\n            time.sleep(1)\n            values.append(i)\n"
            "        assert mean(values) == 9.5\n        assert median(values) == 9.5\n"
            "    finally:\n        running.unlink(missing_ok=True)\n        note(\"end\")\n"),
        "scripts/add_changelog.py": (
            '"""Adds the release note of this fix to CHANGELOG.md. Run it once, when the whole suite passes:\n'
            'each run adds the line again."""\nimport os\nimport pathlib\nimport time\n\n'
            "ROOT = pathlib.Path(__file__).resolve().parent.parent\n" + note + "\n\n"
            f"LINE = {CHANGELOG_LINE!r}\n\n"
            "note(\"changelog\")\npath = ROOT / \"CHANGELOG.md\"\n"
            "path.write_text(path.read_text() + LINE + \"\\n\")\nprint(\"CHANGELOG.md: added\", LINE)\n"),
    }


# a stand-in for the model (--fake): does the task the same way each time it starts, to try the bench itself
FAKE_SOLVER = r'''#!/usr/bin/env python3
import json, pathlib, subprocess, sys, time
FIXED = json.loads(%r)
def step(what, argv=None):
    print(f"· bash: {what}", flush=True)
    if argv:
        subprocess.run(argv)
    time.sleep(2)
step("python3 -m pytest -q", [sys.executable, "-m", "pytest", "-q"])
for path, text in FIXED.items():
    print(f"· write: {path}", flush=True)
    pathlib.Path(path).write_text(text)
    time.sleep(2)
step("python3 -m pytest -q", [sys.executable, "-m", "pytest", "-q"])
step("python3 scripts/add_changelog.py", [sys.executable, "scripts/add_changelog.py"])
pathlib.Path(".task-report.md").write_text("## Report\n\n### Summary\n\n- Fixed it (fake).\n\n### Details\n\nfake\n\n"
                                           "## Please review\n\n- nothing\n")
print("done")
'''


# ---------- processes ----------

def command_of(pid):
    r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return command_of(pid) == ""  # a zombie still answers kill 0 until its parent reaps it


def processes_in(root):
    """{pid: cwd} of the processes working in root (lsof): the run, the agent, its tools, task watch."""
    r = subprocess.run(["lsof", "-nP", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=60)
    found, pid, prefix = {}, None, str(root)
    for line in r.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid and (line[1:] == prefix or line[1:].startswith(prefix + "/")):
            found[pid] = line[1:]
    found.pop(os.getpid(), None)
    return found


def kill_all(root, also=(), seconds=10.0):
    """kill -9 everything working in root, and `also`, until none is left (at most `seconds`); the pids killed."""
    killed, end = set(), time.monotonic() + seconds
    while time.monotonic() < end:
        pids = (set(processes_in(root)) | {p for p in also if p and not gone(p)}) - {os.getpid()}
        if not pids:
            return killed
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.add(pid)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.2)
    return killed


# ---------- one trial: a throwaway HOME, a fake GitHub, a bare repository ----------

class Box:
    def __init__(self, root, trial, opts):
        self.root, self.trial, self.opts = root, trial, opts
        self.home = root / "home"
        self.state = self.home / ".local" / "state" / "task-hub"
        self.state.mkdir(parents=True)
        self.counter = root / "outside" / "counter.log"
        self.counter.parent.mkdir()
        self.db = root / "gh.json"
        self.db.write_text(json.dumps({
            "issues_repo": "jyoka/tasks", "issues": {}, "items": {}, "prs": {},
            "fields": [{"id": "F_status", "name": "Status", "type": "ProjectV2SingleSelectField",
                        "dataType": "SINGLE_SELECT",
                        "options": [{"id": f"O_{i}", "name": n} for i, n in enumerate(STATUS_OPTIONS)]},
                       {"id": "F_title", "name": "Title", "type": "ProjectV2Field", "dataType": "TITLE"},
                       *({"id": f"F_{n}", "name": n, "type": "ProjectV2Field", "dataType": "TEXT"}
                         for n in ("Target repo", "Agent", "Base branch"))]}))
        fakebin = root / "fakebin"
        fakebin.mkdir()
        for name, src in (("gh", FAKE_GH), ("osascript", "#!/bin/sh\nexit 0\n"),
                          ("terminal-notifier", "#!/bin/sh\nexit 0\n")):
            (fakebin / name).write_text(src)
            (fakebin / name).chmod(0o755)
        self.bare = root / "origins" / "jyoka" / "app.git"
        self.seed_repo()
        self.sessions = root / "pi-sessions"
        self.sessions.mkdir()
        cfg = self.home / ".config" / "task-hub" / "config.ini"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(self.config(), encoding="utf-8")
        # nothing of the caller's task-hub, GitHub, Claude Code or pi settings: they could point outside this HOME
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("TASK_", "XDG_", "CLAUDE_", "GH_", "GITHUB_", "HERDR_", "PI_", "BENCH_"))}
        self.env.update(HOME=str(self.home), TASK_GH=str(fakebin / "gh"), TASK_TEST_GH_DB=str(self.db),
                        TASK_HERDR="0", TASK_NO_UPDATE_NOTIFIER="1", TASK_CHECKS_GRACE_SECONDS="0",
                        TASK_CLONE_URL=f"file://{root}/origins/{{repo}}.git", PATH=f"{fakebin}:{os.environ['PATH']}",
                        GIT_AUTHOR_NAME="bench", GIT_AUTHOR_EMAIL="bench@example.invalid",
                        GIT_COMMITTER_NAME="bench", GIT_COMMITTER_EMAIL="bench@example.invalid",
                        # pi's login and models from its own folder, its sessions here (never in ~/.pi/agent)
                        PI_CODING_AGENT_DIR=str(opts.pi_dir), PI_CODING_AGENT_SESSION_DIR=str(self.sessions),
                        PYTHONDONTWRITEBYTECODE="1",
                        PYTHONUSERBASE=site.USER_BASE)  # the caller's pip --user packages (pytest), as before HOME moved
        self.watch = None
        self.outputs = []  # what the bench's own `task` commands printed

    def seed_repo(self):
        seed = self.root / "seed"
        files = project(self.counter)
        for path, text in files.items():
            (seed / path).parent.mkdir(parents=True, exist_ok=True)
            (seed / path).write_text(text)
        git = lambda *a, cwd=seed: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                                                  env={**os.environ, "GIT_AUTHOR_NAME": "bench",
                                                       "GIT_AUTHOR_EMAIL": "bench@example.invalid",
                                                       "GIT_COMMITTER_NAME": "bench",
                                                       "GIT_COMMITTER_EMAIL": "bench@example.invalid"})
        self.bare.parent.mkdir(parents=True)
        git("init", "-q", "--bare", "-b", "main", str(self.bare), cwd=self.root)
        git("init", "-q", "-b", "main")
        git("add", ".")
        git("commit", "-qm", "calc: helpers and their tests")
        git("push", "-q", str(self.bare), "main")
        self.pristine = self.root / "pristine"
        shutil.move(str(seed), self.pristine)

    def config(self):
        o = self.opts
        if o.fake:
            solver = self.root / "fake-solver"
            solver.write_text(FAKE_SOLVER % json.dumps(FIXED))
            solver.chmod(0o755)
            a = c = b = f"{shlex.quote(sys.executable)} {shlex.quote(str(solver))} {{prompt}}"
        else:
            # the same tools as B's (read, write, edit, bash) and nothing of the user's pi setup
            pi = (f"{shlex.quote(str(o.pi))} -p --mode json --model {o.model} --thinking {o.thinking} --no-extensions"
                  " --no-skills --no-prompt-templates --no-context-files --no-mcp --tools read,bash,edit,write")
            a, c = f"{pi} --session-id {{session}} {{prompt}}", f"{pi} {{prompt}}"
            b = (f"{shlex.quote(o.node)} {shlex.quote(str(DURABLE / 'dist' / 'cli.js'))} --session {{session}}"
                 f" --model {o.model} --thinking {o.thinking} --auth {shlex.quote(str(o.pi_dir / 'auth.json'))}"
                 " {prompt}")
        return ("[board]\nproject = jyoka/2\nissues = jyoka/tasks\n\n"
                f"[runner]\nagent = {METHODS[self.trial['method']]}\nreviewer = off\n\n"
                f"[agents]\npi-a = {a}\npi-c = {c}\ndurable = {b}\n\n"
                f"[resume]\npi-a = {a}\ndurable = {b}\n\n"  # C: no [resume], a new session
                "[notify]\nevents =\n")

    def argv(self, *args):
        return [sys.executable, str(BIN), *args]

    def task(self, *args, timeout=300):
        r = subprocess.run(self.argv(*args), env=self.env, cwd=self.root, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        self.outputs.append(f"$ task {' '.join(args)}  (exit {r.returncode}, {now()})\n{r.stdout}{r.stderr}")
        if r.returncode != 0:
            raise RuntimeError(f"task {' '.join(args)} exited {r.returncode}: {(r.stdout + r.stderr)[-1500:]}")
        return r.stdout

    def start_watch(self):
        log = open(self.root / "watch.log", "ab")
        self.watch = subprocess.Popen(self.argv("watch"), env=self.env, cwd=self.root, stdin=subprocess.DEVNULL,
                                      stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()

    def gh(self):
        import fcntl
        with open(f"{self.db}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return json.loads(self.db.read_text())

    def move(self, tid, status):
        import fcntl
        with open(f"{self.db}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            db = json.loads(self.db.read_text())
            db["items"][f"PVTI_{tid}"]["values"]["status"] = status
            db["clock"] = db.get("clock", 0) + 1
            db["items"][f"PVTI_{tid}"]["updated"] = f"2026-01-01T{db['clock']:08d}Z"
            self.db.write_text(json.dumps(db))
        (self.state / "board-cache.json").unlink(missing_ok=True)

    def status(self, tid):
        return self.gh()["items"][f"PVTI_{tid}"]["values"].get("status")

    def run_state(self, tid):
        try:
            return json.loads((self.state / "runs" / f"{tid}.json").read_text())
        except (OSError, ValueError):
            return {}

    def log(self, tid):
        try:
            return (self.state / "logs" / f"{tid}.log").read_text(errors="replace")
        except OSError:
            return ""

    def run_alive(self, tid):
        pid = self.run_state(tid).get("pid")
        return bool(pid) and bool(re.search(rf"\s_run\s+{tid}\s*$", command_of(int(pid))))

    def counter_lines(self):
        try:
            return [line.split() for line in self.counter.read_text().splitlines() if line.strip()]
        except OSError:
            return []


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


class Cut:
    """Waits for the trial's moment (T1-T4) in the first start of the agent, and cuts the run short there (K1-K3)."""

    def __init__(self, box, tid, timing, kill):
        self.box, self.tid, self.timing, self.kill = box, tid, timing, kill
        self.result = "" if not timing else "waiting"
        self.at = self.stage = self.detail = None
        self.first_step = None
        self.seed_stats = sha(box.pristine / "calc" / "stats.py")

    def due(self, wt):
        if self.timing == "T1":
            if self.first_step is None and "\n· " in "\n" + self.box.log(self.tid):
                self.first_step = time.monotonic()
            return self.first_step is not None and time.monotonic() - self.first_step >= T1_DELAY
        if self.timing == "T2":
            return (wt / ".running").exists()
        if self.timing == "T3":
            now_ = sha(wt / "calc" / "stats.py")
            return now_ is not None and now_ != self.seed_stats
        return (wt / ".tests-passed").exists()

    def poll(self):
        """Fire once the moment comes; "missed" when the agent's first start ended before it."""
        if self.result != "waiting":
            return
        box, tid = self.box, self.tid
        state = box.run_state(tid)
        if state.get("resumes") or box.status(tid) in DONE or "== agent exited with code" in box.log(tid):
            self.result = "missed"
            return
        if state.get("stage") != "agent" or not state.get("agent_pid") or not state.get("worktree"):
            return
        if not self.due(Path(state["worktree"])):
            return
        agent, run = int(state["agent_pid"]), int(state.get("pid") or 0)
        if gone(agent):
            return  # between the agent's end and the log's line: looked at again next time
        self.at = time.monotonic()
        self.stage = "tool" if (Path(state["worktree"]) / ".running").exists() else ""
        tail = [line for line in box.log(tid).splitlines() if line.startswith("· ")]
        self.detail = tail[-1][:120] if tail else ""
        if self.kill == "K1":
            os.killpg(agent, signal.SIGKILL)
        elif self.kill == "K2":
            if run and re.search(rf"\s_run\s+{tid}\s*$", command_of(run)):
                os.kill(run, signal.SIGKILL)
            os.killpg(agent, signal.SIGKILL)
            end = time.monotonic() + 10
            while time.monotonic() < end and not (gone(run) and gone(agent)):
                time.sleep(0.1)
            box.task()  # the next check of the board, as task watch makes every minute
        else:  # K3: a restart: everything goes, task watch too, and task watch starts again
            kill_all(box.root, also=(agent, run, box.watch.pid if box.watch else 0))
            if box.watch:
                box.watch.wait(timeout=10)
            box.start_watch()
        self.result = "cut"


def usage_pi(sessions):
    """pi's assistant messages in all session files: (turns, tokens, timeline), the timeline being
    [(epoch seconds, role, has tool call)] for where a cut fell."""
    turns, tok, timeline = 0, {"input": 0, "output": 0, "cacheRead": 0, "total": 0}, []
    for f in sorted(sessions.glob("**/*.jsonl")):
        for line in f.read_text(errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "message":
                continue
            m = e.get("message") or {}
            stamp = parse_time(e.get("timestamp"))
            calls = any(isinstance(b, dict) and b.get("type") == "toolCall" for b in m.get("content") or [])
            timeline.append((stamp, m.get("role"), calls))
            if m.get("role") == "assistant" and m.get("usage"):
                u = m["usage"]
                turns += 1
                tok["input"] += u.get("input", 0)
                tok["output"] += u.get("output", 0)
                tok["cacheRead"] += u.get("cacheRead", 0)
                tok["total"] += u.get("totalTokens", 0)
    return turns, tok, timeline


def usage_durable(wt):
    """B: (turns, tokens, timeline) from harness.usage() as the runner wrote it and the entries of its SQLite file."""
    turns, tok, timeline = 0, None, []
    d = wt / ".task-durable"
    for f in d.glob("*.usage.json") if d.is_dir() else []:
        tok = {"input": 0, "output": 0, "cacheRead": 0, "total": 0}
        for u in json.loads(f.read_text()).get("models", {}).values():
            tok["input"] += u.get("input", 0)
            tok["output"] += u.get("output", 0)
            tok["cacheRead"] += u.get("cacheRead", 0)
            tok["total"] += u.get("totalTokens", 0)
    for f in d.glob("*.sqlite") if d.is_dir() else []:
        try:
            con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
            for (record,) in con.execute("select record from entries order by commit_seq"):
                for m in json.loads(record).get("model") or []:
                    calls = any(isinstance(b, dict) and b.get("type") == "toolCall" for b in m.get("content") or [])
                    timeline.append(((m.get("timestamp") or 0) / 1000, m.get("role"), calls))
                    turns += m.get("role") == "assistant"
            con.close()
        except sqlite3.Error:
            pass
    return turns, tok, timeline


def parse_time(stamp):
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0.0


def phase(timeline, at):
    """Where the cut fell, from the conversation: "model" (its answer under way: the last message before the cut was
    the user's or a tool's result), "tool" (a tool call under way), or "" when unknown."""
    before = [(t, role, calls) for t, role, calls in timeline if t and t <= at and role in ("user", "assistant",
                                                                                           "toolResult")]
    if not before:
        return ""
    _, role, calls = max(before, key=lambda x: x[0])
    return "tool" if role == "assistant" and calls else "model" if role in ("user", "toolResult") else "answered"


def check_branch(box, tid):
    """The pushed branch, with the original tests put back: (pushed, tests pass, tests changed, compiles, diff
    readable, release note lines)."""
    branch = f"task/{tid}"
    if subprocess.run(["git", "-C", str(box.bare), "rev-parse", "--verify", "-q", branch],
                      capture_output=True).returncode != 0:
        return {"pushed": False, "tests_pass": False}
    check = box.root / "check"
    subprocess.run(["git", "clone", "-q", "-b", branch, str(box.bare), str(check)], check=True, capture_output=True)
    changed = subprocess.run(["git", "-C", str(check), "diff", "--name-only", "origin/main", "HEAD", "--",
                              "tests", "conftest.py"], capture_output=True, text=True).stdout.split()
    diff_ok = subprocess.run(["git", "-C", str(check), "diff", "origin/main", "HEAD"],
                             capture_output=True).returncode == 0
    compiles = True
    for f in check.rglob("*.py"):
        if ".git" in f.parts:
            continue
        try:
            compile(f.read_text(), str(f), "exec")
        except (SyntaxError, ValueError, UnicodeDecodeError):
            compiles = False
    log = check / "CHANGELOG.md"
    notes = log.read_text().splitlines().count(CHANGELOG_LINE) if log.exists() else 0
    for name in ("conftest.py", "tests"):  # the answer is checked against the original tests
        shutil.rmtree(check / name, ignore_errors=True) if (check / name).is_dir() else (check / name).unlink(
            missing_ok=True)
        src = box.pristine / name
        shutil.copytree(src, check / name) if src.is_dir() else shutil.copy(src, check / name)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=check,
                       capture_output=True, text=True, timeout=180,
                       env={**box.env, "BENCH_COUNTER": str(box.root / "check-counter.log")})
    return {"pushed": True, "tests_pass": r.returncode == 0, "tests_changed": changed, "compiles": compiles,
            "diff_ok": diff_ok, "changelog_lines": notes, "pytest_tail": r.stdout.strip().splitlines()[-1:]}


def run_trial(trial, opts, say):
    name, method, timing, kill = trial["id"], trial["method"], trial["timing"], trial["kill"]
    root = (opts.work / name).resolve()
    if root.exists():
        kill_all(root, seconds=5)
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    root = root.resolve()
    row = {"kind": "trial", "id": name, "method": method, "agent": METHODS[method], "timing": timing, "kill": kill,
           "rep": trial["rep"], "fake": bool(opts.fake), "model": opts.model, "thinking": opts.thinking,
           "started": now()}
    box = Box(root, trial, opts)
    began = time.monotonic()
    tid = None
    alive_counts, syncs, last_say = [], 0, began
    try:
        out = box.task("new", "--title", "Fix the failing tests of calc", "--repo", "jyoka/app", "--goal", GOAL,
                       "--agent", METHODS[method])
        tid = re.search(r"id: (\d+)", out).group(1)
        if kill == "K3":
            box.move(tid, "Ready")
            box.start_watch()
        else:
            box.task("start", tid)
        cut = Cut(box, tid, timing, kill)
        dead_since = None
        while True:
            elapsed = time.monotonic() - began
            if elapsed > opts.trial_timeout:
                row["error"] = f"timed out after {opts.trial_timeout} s"
                break
            cut.poll()
            status = box.status(tid)
            alive_tests = [int(p) for w, p, *_ in box.counter_lines() if w == "start"]
            ended = {int(p) for w, p, *_ in box.counter_lines() if w == "end"}
            alive_counts.append(sum(1 for p in alive_tests if p not in ended and not gone(p)))
            if status in DONE and not box.run_alive(tid):
                break
            if status == "In progress" and kill != "K3" and box.run_state(tid).get("pid") and not box.run_alive(tid):
                dead_since = dead_since or time.monotonic()
                if time.monotonic() - dead_since > 20:  # the run is gone and nothing checks the board: as a sync would
                    box.task()
                    syncs += 1
                    dead_since = None
            else:
                dead_since = None
            if time.monotonic() - last_say >= 60:
                last_say = time.monotonic()
                state = box.run_state(tid)
                say(f"  {name}: {elapsed:.0f} s, {status}, stage {state.get('stage') or '-'}, cut {cut.result or '-'}")
            time.sleep(POLL)
        row["seconds"] = round(time.monotonic() - began)
        row["cut"] = cut.result
        row["cut_at"] = round(cut.at - began, 1) if cut.at else None
        row["cut_step"] = cut.detail
        cut_epoch = time.time() - (time.monotonic() - cut.at) if cut.at else None
        state = box.run_state(tid)
        wt = Path(state.get("worktree") or root / "none")
        row["status"] = box.status(tid)
        metrics = [json.loads(line) for line in (box.state / "metrics.jsonl").read_text().splitlines()] \
            if (box.state / "metrics.jsonl").exists() else []
        last = metrics[-1] if metrics else {}
        row["resumed"] = last.get("resumed", [])
        row["interrupted"] = last.get("interrupted", "")
        row["blocked_by"] = last.get("blocked_by", "")
        row["relaunched"] = any("resumed: task" in o for o in box.outputs) or "resumed: task" in (
            (root / "watch.log").read_text(errors="replace") if (root / "watch.log").exists() else "")
        log = box.log(tid)
        row["tool_calls"] = sum(1 for line in log.splitlines() if line.startswith("· "))
        row["resume_line"] = next((line for line in log.splitlines() if line.startswith("== agent, resumed")
                                   or line.startswith("== the agent was killed")), "")
        if method == "B":
            turns, tok, timeline = usage_durable(wt)
        else:
            turns, tok, timeline = usage_pi(box.sessions)
        row["turns"], row["tokens"] = turns, tok
        row["cut_phase"] = phase(timeline, cut_epoch) if cut_epoch else ""
        if cut.stage == "tool":
            row["cut_phase"] = "tool"  # the slow test was running: a tool call, whatever the conversation says
        lines = box.counter_lines()
        row["test_runs"] = sum(1 for w, *_ in lines if w == "start")
        row["test_parallel"] = max([0, *alive_counts])  # slow tests seen alive at once
        row["changelog_runs"] = sum(1 for w, *_ in lines if w == "changelog")
        if box.watch:  # K3: task watch is not working in root, but stop it before looking for leftovers
            os.killpg(box.watch.pid, signal.SIGTERM)
            box.watch.wait(timeout=15)
        time.sleep(1)
        left = processes_in(root)
        row["leftover"] = sorted(command_of(p)[:80] for p in left)
        row.update(check_branch(box, tid))
        comments = box.gh()["issues"][tid]["comments"]
        report = next((c["body"] for c in reversed(comments) if c["body"].startswith("<!-- task-hub report -->")), "")
        row["report"] = bool(report)
        row["resumed_note"] = "Resumed once" in report
        save_artifacts(box, tid, wt, opts, row)
    except Exception as e:  # noqa: BLE001 (one trial's failure is noted in its row; the bench goes on)
        row["error"] = f"{type(e).__name__}: {e}"
        row.setdefault("seconds", round(time.monotonic() - began))
    finally:
        if box.watch and box.watch.poll() is None:
            os.killpg(box.watch.pid, signal.SIGKILL)
            box.watch.wait(timeout=15)
        kill_all(root, seconds=15)
        if tid:
            row["syncs"] = syncs
        if not opts.keep:
            shutil.rmtree(root, ignore_errors=True)
    return row


def save_artifacts(box, tid, wt, opts, row):
    """What a later look needs: the task's log, the counter, the bench's own commands, the conversation files."""
    d = opts.out.with_name(f"{opts.out.stem}-artifacts") / row["id"]  # one folder per results file
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "task.log").write_text(box.log(tid))
    (d / "task-commands.txt").write_text("\n".join(box.outputs))
    if box.counter.exists():
        shutil.copy(box.counter, d / "counter.log")
    if (box.root / "watch.log").exists():
        shutil.copy(box.root / "watch.log", d / "watch.log")
    for f in box.sessions.glob("**/*.jsonl"):
        shutil.copy(f, d / f.name)
    durable = wt / ".task-durable"
    for f in durable.glob("*") if durable.is_dir() else []:
        if f.suffix in (".json", ".sqlite") or f.name.endswith((".sqlite-wal",)):
            shutil.copy(f, d / f.name)
    diff = subprocess.run(["git", "-C", str(box.root / "check"), "diff", "origin/main", "HEAD"], capture_output=True,
                          text=True).stdout if (box.root / "check").exists() else ""
    (d / "branch.diff").write_text(diff)


# ---------- the conditions ----------

def capture(*argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def conditions(opts):
    lock = json.loads((DURABLE / "package-lock.json").read_text()).get("packages", {})
    libs = {n: lock.get(f"node_modules/@earendil-works/{n}", {}).get("version", "")
            for n in ("pi-durable", "pi-ai", "chord", "pi-coding-agent")}
    version = re.search(r'^VERSION = "([^"]+)"', BIN.read_text(), re.M)
    return {"kind": "conditions", "time": now(), "machine": machine(), "model": opts.model, "thinking": opts.thinking,
            "pi": capture(str(opts.pi), "--version") if not opts.fake else "", "node": capture(opts.node, "--version"),
            "durable": libs, "task_hub": version.group(1) if version else "",
            "commit": capture("git", "-C", str(REPO), "rev-parse", "--short", "HEAD"),
            "pytest": capture(sys.executable, "-m", "pytest", "--version"), "python": platform.python_version(),
            "fake": bool(opts.fake), "parallel": opts.jobs}


# ---------- the report: docs/durable-runs-comparison.md's tables ----------

def rows_of(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    trials_ = {}
    for r in rows:
        if r.get("kind") == "trial":
            trials_[r["id"]] = r  # a trial run again counts once, as its last run
    return [r for r in rows if r.get("kind") == "conditions"], trials_


def k(n):
    return "-" if n is None else f"{n / 1000:.0f}k"


def report(path):
    conds, rows = rows_of(path)
    order = {t[0]: i for i, t in enumerate(trials())}
    rows = sorted(rows.values(), key=lambda r: order.get(r["id"], 999))
    out = []
    base = {}
    for m in METHODS:
        mine = [r for r in rows if r["method"] == m and not r["kill"] and not r.get("error")]
        tot = [r["tokens"]["total"] for r in mine if r.get("tokens")]
        base[m] = {"tokens": statistics.median(tot) if tot else None,
                   "seconds": statistics.median([r["seconds"] for r in mine]) if mine else None,
                   "tools": statistics.median([r["tool_calls"] for r in mine]) if mine else None,
                   "tests": statistics.median([r["test_runs"] for r in mine]) if mine else None}
    out += ["| trial | cut | phase | at (s) | status | resumed | tests pass | test runs (at once) | release note runs"
            " (lines) | broken | tool calls | turns | tokens | minutes | left running |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        tok = r.get("tokens") or {}
        broken = "-" if not r.get("pushed") else "no" if r.get("compiles") and r.get("diff_ok") else "yes"
        status = r.get("status", "") + (f" ({r['blocked_by']})" if r.get("blocked_by") else "")
        if r.get("error"):
            status += f" error: {r['error'][:60]}"
        out.append(f"| {r['id']} | {r.get('cut') or '-'} | {r.get('cut_phase') or '-'} | "
                   f"{r.get('cut_at') if r.get('cut_at') is not None else '-'} | {status} | "
                   f"{' '.join(r.get('resumed') or []) or '-'} | {'yes' if r.get('tests_pass') else 'no'}"
                   f"{' (tests changed)' if r.get('tests_changed') else ''} | "
                   f"{r.get('test_runs', '-')} ({r.get('test_parallel', '-')}) | {r.get('changelog_runs', '-')} "
                   f"({r.get('changelog_lines', '-')}) | {broken} | {r.get('tool_calls', '-')} | {r.get('turns', '-')} | "
                   f"{k(tok.get('total'))} | {r.get('seconds', 0) / 60:.1f} | {len(r.get('leftover') or [])} |")
    out += ["", "| method | trials | cut | In review | tests pass (not cut / cut) | release note twice | slow test twice"
            " at once | extra test runs (median) | extra tool calls (median) | extra tokens (median) | extra minutes"
            " (median) | tokens, not cut (median) |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in METHODS:
        mine = [r for r in rows if r["method"] == m]
        cut = [r for r in mine if r.get("cut") == "cut"]
        plain = [r for r in mine if not r["kill"]]
        b = base[m]
        med = lambda xs: statistics.median(xs) if xs else None
        extra = lambda key, get: med([get(r) - b[key] for r in cut if b[key] is not None and get(r) is not None])
        x_tests = extra("tests", lambda r: r.get("test_runs"))
        x_tools = extra("tools", lambda r: r.get("tool_calls"))
        x_tok = extra("tokens", lambda r: (r.get("tokens") or {}).get("total"))
        x_sec = extra("seconds", lambda r: r.get("seconds"))
        fmt = lambda v, f="{:+.0f}": "-" if v is None else f.format(v)
        out.append(f"| {m} | {len(mine)} | {len(cut)} | {sum(r.get('status') == 'In review' for r in mine)} | "
                   f"{sum(bool(r.get('tests_pass')) for r in mine)}/{len(mine)} "
                   f"({sum(bool(r.get('tests_pass')) for r in plain)}/{len(plain)} / "
                   f"{sum(bool(r.get('tests_pass')) for r in cut)}/{len(cut)}) | "
                   f"{sum((r.get('changelog_runs') or 0) > 1 for r in mine)} | "
                   f"{sum((r.get('test_parallel') or 0) > 1 for r in mine)} | {fmt(x_tests)} | {fmt(x_tools)} | "
                   f"{'-' if x_tok is None else f'{x_tok / 1000:+.0f}k'} | {fmt(x_sec and x_sec / 60, '{:+.1f}')} | "
                   f"{k(b['tokens'])} |")
    out += ["", "| method | " + " | ".join(f"{t} {kk}" for t in TIMINGS for kk in ("K1", "K2")) + " | T2 K3 |",
            "|---|" + "---|" * 9]
    for m in METHODS:
        cells = []
        for t, kk in [(t, kk) for t in TIMINGS for kk in ("K1", "K2")] + [("T2", "K3")]:
            mine = [r for r in rows if r["method"] == m and r["timing"] == t and r["kill"] == kk]
            cells.append(f"{sum(bool(r.get('tests_pass')) for r in mine)}/{len(mine)}"
                         + (f" ({sum(r.get('cut') != 'cut' for r in mine)} missed)"
                            if any(r.get('cut') != 'cut' for r in mine) else ""))
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    total = sum((r.get("tokens") or {}).get("total") or 0 for r in rows)
    out += ["", f"trials: {len(rows)}, tokens in all: {total / 1e6:.1f}M"]
    if conds:
        out += ["", "conditions: " + json.dumps({k_: v for k_, v in conds[-1].items() if k_ != "kind"},
                                                ensure_ascii=False)]
    return "\n".join(out)


def main(argv):
    p = argparse.ArgumentParser(prog="tests/durable_bench.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, help=f"the results (default {WORK}/results.jsonl, --fake: fake-results.jsonl)")
    p.add_argument("--only", default="", help="a regular expression: run the trials whose id it finds (A-T2-K1-1 ...)")
    p.add_argument("--limit", type=int, default=0, help="run at most this many trials not in --out yet, then stop")
    p.add_argument("-j", "--jobs", type=int, default=1, help="trials at once (default 1)")
    p.add_argument("--trial-timeout", type=int, default=1500, help="seconds one trial may take (default 1500)")
    p.add_argument("--pi", type=Path, default=Path(shutil.which("pi") or Path.home() / ".pi/agent/bin/pi"))
    p.add_argument("--pi-dir", type=Path, default=Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home()
                                                       / ".pi" / "agent"), help="pi's own folder (its login)")
    p.add_argument("--node", default=shutil.which("node") or "node")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--thinking", default=THINKING)
    p.add_argument("--fake", action="store_true", help="a scripted stand-in for the model: tries the bench itself")
    p.add_argument("--keep", action="store_true", help="keep each trial's throwaway folder")
    p.add_argument("--list", action="store_true", help="list the trials and whether --out has them")
    p.add_argument("--report", action="store_true", help="print the tables of --out")
    opts = p.parse_args(argv)
    opts.work = WORK / ("fake" if opts.fake else "trials")
    opts.out = opts.out or WORK / ("fake-results.jsonl" if opts.fake else "results.jsonl")
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    done = set(rows_of(opts.out)[1]) if opts.out.exists() else set()
    if opts.report:
        print(report(opts.out))
        return 0
    todo = [dict(zip(("id", "method", "timing", "kill", "rep"), t)) for t in trials()
            if re.search(opts.only, t[0])]
    if opts.list:
        for t in todo:
            print(f"{t['id']}{'  (done)' if t['id'] in done else ''}")
        return 0
    todo = [t for t in todo if t["id"] not in done]
    if opts.limit:
        todo = todo[:opts.limit]
    if not opts.fake:
        if not opts.pi.exists():
            p.error(f"pi not found at {opts.pi} (--pi)")
        if not (opts.pi_dir / "auth.json").exists():
            p.error(f"no pi login in {opts.pi_dir} (--pi-dir): sign in with pi first")
        if not (DURABLE / "dist" / "cli.js").exists():
            p.error("durable/ is not built: cd durable && npm ci --ignore-scripts && npm run build")
    lock = threading.Lock()

    def say(line):
        with lock:
            print(line, flush=True)

    def write(row):
        with lock, opts.out.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    write(conditions(opts))
    say(f"durable bench: {len(todo)} trial(s), {opts.jobs} at once, model {opts.model} (thinking {opts.thinking})"
        f"{', fake agent' if opts.fake else ''}; results in {opts.out}")
    began = time.monotonic()

    def one(t):
        say(f"start {t['id']}")
        row = run_trial(t, opts, say)
        write(row)
        tok = (row.get("tokens") or {}).get("total")
        say(f"done  {t['id']}: {row.get('status')}, cut {row.get('cut') or '-'} ({row.get('cut_phase') or '-'}), "
            f"tests {'pass' if row.get('tests_pass') else 'FAIL'}, test runs {row.get('test_runs')}, "
            f"release note runs {row.get('changelog_runs')}, tokens {k(tok)}, {row.get('seconds')} s"
            + (f", error: {row['error']}" if row.get("error") else ""))
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(opts.jobs, 1)) as pool:
        list(pool.map(one, todo))
    say(f"done in {time.monotonic() - began:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
