#!/usr/bin/env python3
"""Take the README's and the LP's pictures with task-hub itself: python3 tests/media.py [--text] [--check]

Not a test. Run it when a screen changes (docs/media.md). It runs one made-up card through bin/task, against the
tests' fake GitHub (tests/test_task.py FAKE_GH) and a fake agent and reviewer that follow a script: no model, no real
GitHub. Every name, text, and time in the pictures is made up and the same on every run.

- the moving picture (assets/media/flow.gif, .webm, .avif): the card from Ready to merged, in the terminal and on
  the Claude Code mod's board
- 4 screens, dark and light (assets/media/<name>-dark.png, -light.png): `task list`, the Claude Code mod's board,
  the Kiro extension's board, and the review (its first verdict, then `task show --digest`)
- the layers of docs/brand.md section 4 (assets/media/layers/): one screen per layer, for the LP

--text runs the card and prints what the screens show, without Chrome or ffmpeg. --check only looks at the files in
assets/media/ (sizes, and nothing private in them), as tests/test_media.py does.
"""
import argparse
import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
BIN = ROOT / "bin" / "task"
MEDIA = ROOT / "assets" / "media"
sys.path.insert(0, str(TESTS))
from test_task import FAKE_GH, STATUS_OPTIONS  # noqa: E402  the tests' fake GitHub

# The made-up card of docs/brand.md section 4. English, so one set of pictures serves both READMEs.
OWNER, PROJECT, ISSUES, REPO = "you", "you/1", "you/tasks", "you/notes-app"
CARD = "12"
TITLE = "Add a search box to the notes list"
GOAL = """Add a search box above the notes list, so a note is quick to find.

## Acceptance criteria

- The list shows only the notes whose title or body contains the text in the box.
- Upper and lower case do not matter: `milk` finds `Buy Milk`.
- Tests cover both.
"""
# the other cards, so the board looks like one in use: #13 runs beside the story's card, #14 stops to ask you
# something (Blocked), #15 stays in Backlog
OTHERS = ["Export a note as Markdown", "Sync notes between two devices", "Pin a note to the top of the list"]
DONE_BEFORE = 11  # cards closed before this story: the card is #12, as in docs/brand.md
# earlier runs on this machine (metrics.jsonl): the mod and the Kiro view show "usually 9 min" from them
EARLIER_RUNS = [480, 540, 540, 600, 660]

# The fake agent: writes the change and the report the way a real one would, and waits at a gate so the driver can
# take its pictures while the run is at that stage. First round: a search that minds the case; after the review's
# feedback: one that does not.
MEDIA_AGENT = r'''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
prompt = sys.argv[-1]
gates = Path(os.environ["TASK_MEDIA_GATES"])
def hold(name):  # the driver takes its pictures while the run waits here, and lets it go on
    (gates / f"{name}.waiting").write_text("")
    end = time.time() + 60
    while not (gates / f"{name}.go").exists():
        if time.time() > end:
            sys.exit(f"the media driver never let {name} go on")
        time.sleep(0.05)
if "adversarial reviewer of one completed task-hub run" in prompt or "# Goldfish review" in prompt:
    sys.exit("this agent only implements")
if "Sync notes between two devices" in prompt:  # a card that needs your decision
    print("Reading notes/store.py", flush=True)
    Path(".task-report.md").write_text("## Blocked\n\nWhich service should keep the notes in sync: iCloud Drive or "
                                       "Dropbox?\n\n## Report\n\n### Summary\n\n- Changed nothing yet.\n")
    sys.exit(0)
if "Export a note as Markdown" in prompt:  # a card that runs beside the story's, until the driver ends
    Path("notes").mkdir(exist_ok=True)
    Path("notes/export.py").write_text("def to_markdown(note):\n    return f\"# {note.title}\\n\\n{note.body}\\n\"\n")
    print("Writing notes/export.py", flush=True)
    hold("export")
    Path(".task-report.md").write_text("## Report\n\n### Summary\n\n- Added `notes/export.py`.\n")
    sys.exit(0)
retry = "# Automated review feedback" in prompt
Path("notes").mkdir(exist_ok=True)
Path("tests").mkdir(exist_ok=True)
compare = ("    needle = text.casefold()\n"
           "    return [n for n in notes if needle in n.title.casefold() or needle in n.body.casefold()]\n") if retry else \
          "    return [n for n in notes if text in n.title or text in n.body]\n"
Path("notes/search.py").write_text('def search(notes, text):\n    """The notes whose title or body contains text."""\n'
                                   + compare)
tests = ["title", "body", "none", "empty"] + (["case"] if retry else [])
Path("tests/test_search.py").write_text("".join(f"def test_{t}():\n    ...\n\n" for t in tests))
print("Reading notes/list.py and notes/store.py", flush=True)
print("Writing notes/search.py and tests/test_search.py", flush=True)
print(f"python3 -m unittest: {len(tests) + 2} passed", flush=True)
what = ("Made the search ignore upper and lower case: both sides go through `casefold()`. "
        "Added `test_case`: `milk` finds `Buy Milk`." if retry else
        "Added a search box above the notes list. `notes/search.py` `search()` keeps the notes whose title or "
        "body contains the text; `notes/list.py` calls it on each key.")
Path(".task-report.md").write_text(f"""## Report

### Summary

- {what.split(". ")[0]}.
- The tests pass: {len(tests) + 2} passed.

### Details

{what}
Ran `python3 -m unittest`: {len(tests) + 2} passed.

## Please review

- `notes/search.py` `search`: how it compares the text
""")
hold("agent-2" if retry else "agent-1")
'''

MEDIA_REVIEWER = r'''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
gates = Path(os.environ["TASK_MEDIA_GATES"])
def hold(name):
    (gates / f"{name}.waiting").write_text("")
    end = time.time() + 60
    while not (gates / f"{name}.go").exists():
        if time.time() > end:
            sys.exit(f"the media driver never let {name} go on")
        time.sleep(0.05)
if not Path("notes/search.py").exists():  # the card that runs beside the story's
    Path(".task-review.md").write_text("## Verdict\n\npass\n\n## Review\n\nThe export is met.\n")
    sys.exit(0)
fixed = "casefold" in Path("notes/search.py").read_text()
print("Checking each acceptance criterion against notes/search.py", flush=True)
case = ("met. `search(notes, \"milk\")` finds `Buy Milk` (`tests/test_search.py` `test_case`)." if fixed else
        "not met. `search(notes, \"milk\")` misses the note `Buy Milk`: `notes/search.py:3` compares as is.")
body = f"""## Verdict

{"pass" if fixed else "needs changes"}

## Review

{"All three criteria are met." if fixed else "The search minds upper and lower case."}

- Title or body: met. `notes/search.py:3` looks in both.
- Upper and lower case: {case}
- Tests: {"met. 7 passed." if fixed else "not met. No test searches in another case."}
"""
if not fixed:
    body += """
## Please fix

- `notes/search.py:3`: `milk` misses `Buy Milk`. Compare both sides with `casefold()`, and add a test for it.
"""
Path(".task-review.md").write_text(body)
hold("review-2" if fixed else "review-1")
'''


def run(argv, timeout=60, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kw)


class World:
    """A HOME of its own, the fake GitHub with the made-up board, and the notes app as a local bare repo."""

    def __init__(self, root):
        self.root = root
        self.db = root / "gh.json"
        self.gates = root / "gates"
        self.gates.mkdir()
        self.event_minutes = []  # the story's minute of each line of events.jsonl, as it first saw the line
        bins = {"gh": FAKE_GH, "agent": MEDIA_AGENT, "reviewer": MEDIA_REVIEWER}
        for name, src in bins.items():
            (root / name).write_text(src)
            (root / name).chmod(0o755)
        options = [*STATUS_OPTIONS[:4], "wait for merge", *STATUS_OPTIONS[4:]]
        issues = {str(n): {"title": f"Earlier card {n}", "body": "", "state": "CLOSED", "comments": []}
                  for n in range(1, DONE_BEFORE + 1)}
        self.save({"issues_repo": ISSUES, "owners": {OWNER: "User"}, "projects": [PROJECT], "issues": issues,
                   "items": {}, "prs": {},
                   "fields": [{"id": "F_status", "name": "Status", "type": "ProjectV2SingleSelectField",
                               "dataType": "SINGLE_SELECT",
                               "options": [{"id": f"O_{i}", "name": n} for i, n in enumerate(options)]},
                              {"id": "F_title", "name": "Title", "type": "ProjectV2Field", "dataType": "TITLE"},
                              {"id": "F_repo", "name": "Target repo", "type": "ProjectV2Field", "dataType": "TEXT"},
                              {"id": "F_agent", "name": "Agent", "type": "ProjectV2Field", "dataType": "TEXT"},
                              {"id": "F_base", "name": "Base branch", "type": "ProjectV2Field", "dataType": "TEXT"},
                              {"id": "F_review", "name": "Review", "type": "ProjectV2SingleSelectField",
                               "dataType": "SINGLE_SELECT",
                               "options": [{"id": f"R_{i}", "name": n}
                                           for i, n in enumerate(("pass", "needs changes", "blocked"))]}]})
        git_id = {"GIT_AUTHOR_NAME": "you", "GIT_AUTHOR_EMAIL": "you@example.invalid", "GIT_COMMITTER_NAME": "you",
                  "GIT_COMMITTER_EMAIL": "you@example.invalid", "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
                  "GIT_CONFIG_NOSYSTEM": "1"}
        keep = ("PATH", "LANG", "LC_ALL", "TMPDIR", "USER", "LOGNAME", "SHELL")
        self.env = {**{k: os.environ[k] for k in keep if k in os.environ}, **git_id, "HOME": str(root),
                    "TZ": "UTC", "TASK_GH": str(root / "gh"), "TASK_HERDR": "0", "TASK_TEST_GH_DB": str(self.db),
                    "TASK_CLONE_URL": f"file://{root}/origins/{{repo}}.git", "TASK_MEDIA_GATES": str(self.gates),
                    "TASK_NO_UPDATE_NOTIFIER": "1",
                    "TASK_CHECKS_GRACE_SECONDS": "0"}
        fakebin = root / "fakebin"  # notifications and launchd stay inside this HOME
        fakebin.mkdir()
        for name in ("osascript", "launchctl", "terminal-notifier", "notify-send"):
            (fakebin / name).write_text("#!/bin/sh\nexit 0\n")
            (fakebin / name).chmod(0o755)
        self.env["PATH"] = f"{fakebin}:{self.env.get('PATH', '/usr/bin:/bin')}"
        (root / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
        cfg = root / ".config" / "task-hub" / "config.ini"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(f"[board]\nproject = {PROJECT}\nissues = {ISSUES}\n\n[runner]\nagent = claude\n"
                       f"reviewer = codex\n\n[agents]\nclaude = {root}/agent {{prompt}}\n"
                       f"codex = {root}/reviewer {{prompt}}\n\n[merge]\nqueue = on\n")
        state = root / ".local" / "state" / "task-hub"
        state.mkdir(parents=True)
        (state / "metrics.jsonl").write_text("".join(
            json.dumps({"id": str(n), "agent": "claude", "seconds": s, "status": "In review"}) + "\n"
            for n, s in enumerate(EARLIER_RUNS, 6)))
        self.seed_repo()

    def seed_repo(self):
        bare = self.root / "origins" / f"{REPO}.git"
        seed = self.root / "seed"
        run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], env=self.env, check=True)
        run(["git", "clone", "-q", str(bare), str(seed)], env=self.env, check=True)
        files = {"README.md": "# notes-app\n\nA small notes app.\n",
                 "notes/store.py": "class Note:\n    def __init__(self, title, body):\n"
                                   "        self.title, self.body = title, body\n",
                 "notes/list.py": "def show(notes):\n    for n in notes:\n        print(n.title)\n",
                 "tests/test_list.py": "def test_show():\n    ...\n"}
        for name, text in files.items():
            (seed / name).parent.mkdir(parents=True, exist_ok=True)
            (seed / name).write_text(text)
        run(["git", "-C", str(seed), "add", "."], env=self.env, check=True)
        run(["git", "-C", str(seed), "commit", "-qm", "The notes list"], env=self.env, check=True)
        run(["git", "-C", str(seed), "push", "-q", "origin", "main"], env=self.env, check=True)
        shutil.rmtree(seed)

    def save(self, db):
        with open(f"{self.db}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.db.write_text(json.dumps(db))

    def gh(self):
        with open(f"{self.db}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return json.loads(self.db.read_text())

    def task(self, *args):
        r = run([str(BIN), *args], env=self.env, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise SystemExit(f"task {' '.join(args)} failed ({r.returncode}):\n{r.stdout}{r.stderr}")
        return r.stdout

    def move(self, tid, status):
        """What you do by dragging the card on GitHub."""
        with open(f"{self.db}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            db = json.loads(self.db.read_text())
            db["items"][f"PVTI_{tid}"]["values"]["status"] = status
            db["clock"] = db.get("clock", 0) + 1
            db["items"][f"PVTI_{tid}"]["updated"] = f"2026-01-01T{db['clock']:08d}Z"
            self.db.write_text(json.dumps(db))
        (self.root / ".local/state/task-hub/board-cache.json").unlink(missing_ok=True)

    def status(self, tid):
        return self.gh()["items"][f"PVTI_{tid}"]["values"].get("status")

    def until(self, check, what, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return
            time.sleep(0.05)
        raise SystemExit(f"timed out after {timeout}s waiting for {what}")

    def at_gate(self, name):
        self.until(lambda: (self.gates / f"{name}.waiting").exists(), f"the run to reach {name}")

    def open_gate(self, name):
        (self.gates / f"{name}.go").write_text("")

    def state(self, name):
        f = self.root / ".local/state/task-hub" / name
        return f.read_text() if f.exists() else ""

    def board(self, minute):
        """What the boards read at this minute of the story: `task list`, and events.jsonl, metrics.jsonl and the
        config as the Claude Code mod and the Kiro view read them. The events' times are the story's clock (a made-up
        morning), not this machine's: the boards show how long a run has gone from them."""
        events = self.seen(minute)
        for e, at in zip(events, self.event_minutes):
            e["time"] = clock(at)
        return {"list": self.task("list"), "events": "".join(json.dumps(e) + "\n" for e in events),
                "metrics": self.state("metrics.jsonl"), "ini": (self.root / ".config/task-hub/config.ini").read_text(),
                "now": clock(minute, 30)}

    def run_ended(self, tid):
        """Whether the card's run process is gone (its record keeps the pid after the card moved)."""
        record = json.loads(self.state(f"runs/{tid}.json") or "{}")
        return not record.get("pid") or run(["ps", "-p", str(record["pid"])]).returncode != 0

    def seen(self, minute):
        """events.jsonl, its new lines dated at this minute of the story."""
        events = [json.loads(line) for line in self.state("events.jsonl").splitlines() if line.strip()]
        self.event_minutes += [minute] * (len(events) - len(self.event_minutes))
        return events

    def worktree(self, tid):
        return json.loads(self.state(f"runs/{tid}.json"))["worktree"]

    def sh(self, command, cwd):
        """A shell command in the card's worktree, as you would type it there."""
        r = run(["/bin/sh", "-c", command], env=self.env, cwd=cwd)
        if r.returncode:
            raise SystemExit(f"{command} failed ({r.returncode}):\n{r.stdout}{r.stderr}")
        return r.stdout


STORY_START = 9 * 60  # the made-up morning the story's clock starts at, in minutes after midnight (UTC)
# the story's clock at each board, in minutes: card 12 starts at 1, card 13 at 9 (the boards show the minutes since)
MINUTES = {"ready": 0, "agent": 4, "review": 6, "retry": 7, "in review": 11, "queued": 12, "merged": 13}


def clock(minute, second=None):
    """The story's clock as the boards read it: an ISO time for events.jsonl, or with `second`, milliseconds for the
    boards' `now`. A made-up day: only the minutes between two times ever show."""
    at = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(
        minutes=STORY_START + minute, seconds=second or 0)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ") if second is None else int(at.timestamp() * 1000)


def story(w):
    """Run card #12 from Ready to merged, beside three other cards, and keep what each picture shows: the boards'
    inputs at each step (boards) and what the terminal printed (said: command -> output)."""
    boards, said = {}, {}

    def say(name, command, output):
        said[name] = (command, output)

    goal = w.root / "goal.md"
    goal.write_text(GOAL)
    w.task("new", "--title", TITLE, "--repo", REPO, "--goal-file", str(goal))
    for title in OTHERS:
        goal.write_text(f"{title}.\n")
        w.task("new", "--title", title, "--repo", REPO, "--goal-file", str(goal))
    w.task("start", "14")  # the card that needs your decision: Blocked before the story starts
    w.until(lambda: w.status("14") == "Blocked", "card 14 to stop as Blocked")
    w.until(lambda: w.run_ended("14"), "card 14's run to end")

    w.move(CARD, "Ready")  # you
    boards["ready"] = w.board(MINUTES["ready"])
    say("ready", "task list", boards["ready"]["list"])

    w.task()  # what `task watch` does each minute: card 12 starts in a worktree of its own
    w.seen(1)
    w.at_gate("agent-1")
    boards["agent"] = w.board(MINUTES["agent"])
    say("agent", "task list", boards["agent"]["list"])
    tree = w.worktree(CARD)
    say("branch", "git branch --show-current", w.sh("git branch --show-current", tree))
    say("status", "git status --short", w.sh("git status --short", tree))
    say("report", "cat .task-report.md", w.sh("cat .task-report.md", tree))
    w.open_gate("agent-1")

    w.at_gate("review-1")
    boards["review"] = w.board(MINUTES["review"])
    say("review", "task list", boards["review"]["list"])
    say("findings", "cat .task-review.md", w.sh("cat .task-review.md", tree))
    w.open_gate("review-1")

    w.at_gate("agent-2")
    boards["retry"] = w.board(MINUTES["retry"])
    say("retry", "task list", boards["retry"]["list"])
    w.open_gate("agent-2")
    w.at_gate("review-2")
    w.open_gate("review-2")
    w.until(lambda: w.status(CARD) == "In review", "card 12 to reach In review")
    w.until(lambda: "In review" in w.state("events.jsonl"), "the In review event")
    where, header, log = w.task("log", CARD).split("\n", 2)  # the log's file, then its header: the date and time
    if not where.startswith("log: ") or not header.startswith(f"== task {CARD}: "):
        raise SystemExit(f"task log {CARD} no longer starts with the log's file and its header:\n{where}\n{header}")
    say("log", f"task log {CARD} | tail -n +3", log)

    w.seen(MINUTES["in review"] - 3)
    w.task("start", "13")  # you approve another card: it runs beside the story's
    w.seen(MINUTES["in review"] - 2)
    w.at_gate("export")
    boards["in review"] = w.board(MINUTES["in review"])
    say("in review", "task list", boards["in review"]["list"])
    say("digest", "task show 12 --digest", w.task("show", CARD, "--digest"))
    say("show", "task show 12", w.task("show", CARD))

    say("merge", "task merge 12", w.task("merge", CARD))  # you approve the PR
    boards["queued"] = w.board(MINUTES["queued"])
    say("queued", "task list", boards["queued"]["list"])
    w.task()  # `task watch` again: the merge queue merges it
    w.until(lambda: w.status(CARD) == "Done", "card 12 to be Done")
    boards["merged"] = w.board(MINUTES["merged"])
    say("merged", "task list", boards["merged"]["list"])
    events = w.task("events").splitlines()
    say("events", "task events | tail -n 3", "".join(line + "\n" for line in events[-3:]))

    w.open_gate("export")  # let the other card end, so nothing is left running
    w.until(lambda: w.status("13") == "In review", "card 13 to reach In review")
    w.until(lambda: w.run_ended("13"), "card 13's run to end")
    return boards, said


# --- the boards' own code: the Claude Code mod (through `claude plugin test`) and the Kiro view (through node) ---

MOD = ROOT / "claude" / "task-board"
KIRO = ROOT / "kiro" / "board-extension"
MOD_HOME = "/home/you"  # the HOME the mod is told it has: its file reads are answered from the story
# The mod's pane, once per board: mounted in the mod's own test kit, with `task list` and the files answered from the
# story, and printed as its tree of Box, Text, and Raster (the ship) elements.
MOD_TEST = r"""import { mock, test } from 'claude-code/testing'
const SHOTS: Record<string, { list: string; events: string; metrics: string; ini: string; now: number; columns: number }> = %s
const HOME = %s
for (const [name, s] of Object.entries(SHOTS)) test(name, async ($, on) => {
  mock.env(on, { HOME })
  mock.clock(on, { now: s.now })
  on('process.run', async () => ({
    value: { exitCode: 0, stdout: s.list, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  const files: Record<string, string> = {
    [`${HOME}/.local/state/task-hub/events.jsonl`]: s.events,
    [`${HOME}/.local/state/task-hub/metrics.jsonl`]: s.metrics,
    [`${HOME}/.config/task-hub/config.ini`]: s.ini,
  }
  on('fs.read', async ($, e) => {
    const text = files[e.path]
    if (text === undefined) throw new Error(`ENOENT: no such file or directory, open '${e.path}'`)
    return { value: text }
  })
  const ui = await $.ui.mount({ plugin: 'task-board', surface: 'terminal', component: 'Pane', requestId: 'task-board',
    props: { title: 'task-hub', isFocused: false, bodyColumns: s.columns, placement: 'dock',
             scroll: { offset: 0, bodyRows: 60 }, view: {} } })
  await ui.press({ key: 'refresh' })
  const [root] = await ui.findAll({})
  console.log(`TASK-HUB-MEDIA ${JSON.stringify({ name, root })}`)
  await ui.unmount()
})
"""
KIRO_SCRIPT = r"""import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const { toBoard, detailsOf, tree, statusBar } = await import(pathToFileURL(process.argv[2]).href)
const out = {}
for (const [name, s] of Object.entries(JSON.parse(readFileSync(0, 'utf8')))) {
  const board = toBoard({ exitCode: 0, stdout: s.list, stderr: '' }, '')
  out[name] = { tree: tree(board, detailsOf(board, { events: s.events, metrics: s.metrics, ini: s.ini }, s.now)),
                bar: statusBar(board) }
}
process.stdout.write(JSON.stringify(out))
"""


def mod_panes(boards, columns, work):
    """{name: the pane's element tree} for each board, drawn by the mod's own code."""
    mod = work / "task-board"
    shutil.copytree(MOD, mod, ignore=shutil.ignore_patterns("*.test.ts", "*.test.tsx"))
    shots = {name: {**b, "columns": columns} for name, b in boards.items()}
    (mod / "hooks" / "media.test.tsx").write_text(MOD_TEST % (json.dumps(shots), json.dumps(MOD_HOME)))
    r = run([tool("claude"), "plugin", "test", str(mod)], timeout=120)
    panes = {}
    for line in (r.stdout + "\n" + r.stderr).splitlines():  # the kit prints what a test logs on stderr
        if line.startswith("TASK-HUB-MEDIA "):
            shot = json.loads(line.removeprefix("TASK-HUB-MEDIA "))
            panes[shot["name"]] = shot["root"]
    if r.returncode or set(panes) != set(boards):
        raise SystemExit(f"claude plugin test did not draw the mod's pane ({r.returncode}):\n{r.stdout[-3000:]}"
                         f"{r.stderr[-3000:]}")
    return panes


def kiro_views(boards, work):
    """{name: {tree, bar}}: the Kiro view's nodes and status bar for each board, from the extension's own code."""
    script = work / "kiro-board.mjs"
    script.write_text(KIRO_SCRIPT)
    r = run([tool("node"), "--disable-warning=ExperimentalWarning", "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON",
             "--import", (KIRO / "test" / "resolve.mjs").as_uri(), str(script), str(KIRO / "src" / "board.ts")],
            input=json.dumps(boards), timeout=60)
    if r.returncode:
        raise SystemExit(f"node could not draw the Kiro view ({r.returncode}):\n{r.stderr}")
    return json.loads(r.stdout)


# --- the pages Chrome takes the pictures of: assets/brand/tokens.css and the system's own fonts, nothing from outside

TOKENS = ROOT / "assets" / "brand" / "tokens.css"
# the mod's color names and the Kiro view's theme colors, as the colors of assets/brand/tokens.css
NAMED = {"red": "var(--error)", "yellow": "var(--warn)", "green": "var(--ok)", "cyan": "var(--cyan)",
         "blue": "var(--accent)", "magenta": "var(--violet)", "gray": "var(--muted)", "grey": "var(--muted)",
         "white": "var(--text)", "black": "var(--bg)"}
THEMED = {"charts.red": "var(--error)", "charts.yellow": "var(--warn)", "charts.green": "var(--ok)",
          "terminal.ansiCyan": "var(--cyan)", "list.warningForeground": "var(--warn)",
          "list.errorForeground": "var(--error)"}
ACTORS = {"you": ("You", "var(--actor-you)"), "task-hub": ("task-hub", "var(--actor-task-hub)"),
          "agent": ("Agent", "var(--actor-agent)")}
CSS = """
* { box-sizing: border-box; margin: 0; }
body { background: var(--bg); color: var(--text); font: 15px/1.5 var(--font-sans); }
main { display: flex; flex-direction: column; gap: 16px; padding: 24px; }
.window { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.bar { display: flex; align-items: center; gap: 8px; padding: 9px 14px; border-bottom: 1px solid var(--line);
       color: var(--muted); font-size: 13px; }
.dot { width: 11px; height: 11px; border-radius: 50%; background: var(--line); }
.bar .name { margin-left: 8px; }
.mono { font: 14px/1.5 var(--font-mono); }
.term { padding: 12px 16px 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
.ps { color: var(--accent); font-weight: 700; }
.cmd { font-weight: 700; }
.pane { padding: 8px 10px 10px; white-space: pre; }
.pane .row { display: flex; }
.pane .col { display: flex; flex-direction: column; }
.pane .box { border: 1.5px solid; border-radius: 7px; margin: 3px 0; padding-top: 2px; padding-bottom: 2px; }
.pane .button { border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; margin-right: 1ch; }
.pane .link { color: var(--accent); text-decoration: underline; }
.raster { display: flex; flex-direction: column; margin-bottom: 4px; }
.raster div { display: flex; height: 1.5em; }
.raster span { display: inline-block; width: 1ch; height: 1.5em; text-align: center; }
.kiro { font: 13px/22px var(--font-sans); }
.kiro .title { padding: 6px 12px; font-size: 11px; font-weight: 700; letter-spacing: .06em; color: var(--muted); }
.kiro .section { display: flex; gap: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700;
                 border-top: 1px solid var(--line); text-transform: uppercase; }
.kiro .node { display: flex; align-items: center; gap: 6px; white-space: nowrap; overflow: hidden; padding-right: 12px; }
.kiro .twist { width: 12px; color: var(--muted); text-align: center; flex: none; }
.kiro svg { width: 16px; height: 16px; flex: none; }
.kiro .desc { color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; }
.kiro .status { display: flex; gap: 6px; align-items: center; padding: 3px 12px; font-size: 12px;
                background: var(--accent); color: var(--on-accent); }
.kiro .status svg { width: 14px; height: 14px; }
.step { display: flex; align-items: center; gap: 12px; font-size: 22px; font-weight: 600; min-height: 34px; }
.chip { font-size: 14px; font-weight: 700; padding: 2px 10px; border-radius: 999px; border: 2px solid; }
.duo { display: grid; grid-template-columns: 1fr 470px; gap: 16px; align-items: stretch; }
.duo .window { height: 560px; display: flex; flex-direction: column; }
.duo .term { flex: 1; overflow: hidden; }
.progress { display: flex; gap: 8px; }
.progress span { flex: 1; height: 6px; border-radius: 999px; background: var(--line); }
"""


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def page(main, theme, width):
    """A whole page: tokens.css, then the pictures' own rules, fixed to `width` CSS pixels. Its script writes the
    height `main` needs into the page, for the second look that takes the picture at that size."""
    return (f'<!DOCTYPE html><html lang="en" data-theme="{theme}"><head><meta charset="utf-8">'
            f"<style>{TOKENS.read_text(encoding='utf-8')}{CSS} body {{ width: {width}px; }}</style></head>"
            f"<body><main>{main}</main><script>document.documentElement.dataset.height = "
            "Math.ceil(document.querySelector('main').getBoundingClientRect().height)</script></body></html>")


def window(name, body, cls=""):
    return (f'<div class="window {cls}"><div class="bar"><span class="dot"></span><span class="dot"></span>'
            f'<span class="dot"></span><span class="name">{esc(name)}</span></div>{body}</div>')


def terminal(said, names, title="Terminal"):
    """The commands you typed and what they printed, one after the other, as in a terminal."""
    parts = []
    for name in names:
        command, output = said[name]
        parts.append(f'<span class="ps">$</span> <span class="cmd">{esc(command)}</span>\n{esc(output)}')
    return window(title, f'<div class="mono term">{"".join(parts).rstrip()}</div>')


def color(value):
    return NAMED.get(value, value if re.fullmatch(r"#[0-9a-fA-F]{6}", value or "") else "var(--text)")


def raster(props):
    """The ship: cells of [code point, foreground, background], u32 little-endian, base64 (claude/task-board/hooks/
    ship.ts cells()). A half block is two pixels of a cell, the top one and the bottom one."""
    import base64
    data = base64.b64decode(props["cells"])
    none = 0x01000000  # ship.ts NONE: no color, the pane's own background shows
    rows = []
    for r in range(props["rows"]):
        cells = []
        for x in range(props["columns"]):
            cp, fg, bg = (int.from_bytes(data[at:at + 4], "little")
                          for at in range((r * props["columns"] + x) * 12, (r * props["columns"] + x + 1) * 12, 4))
            hexes = [None if c == none else f"#{c:06x}" for c in (fg, bg)]
            if cp in (0x2580, 0x2584, 0x20):  # ▀ top in fg, ▄ bottom in fg, a space in bg
                top, bottom = {0x2580: hexes, 0x2584: hexes[::-1], 0x20: [hexes[1]] * 2}[cp]
                style = (f"background: linear-gradient({top or 'transparent'} 50%, {bottom or 'transparent'} 50%)"
                         if top or bottom else "")
                cells.append(f'<span style="{style}"></span>')
            else:
                cells.append(f'<span style="color: {hexes[0] or "var(--text)"}; background: {hexes[1] or "transparent"}">'
                             f"{esc(chr(cp))}</span>")
        rows.append(f"<div>{''.join(cells)}</div>")
    return f'<div class="raster">{"".join(rows)}</div>'


def element(node):
    """One element of the mod's tree as HTML, the way the terminal draws it: Box as a flex box (a row unless it says
    column), a round border as a thin rounded line, Text with its color, bold, dim, and inverse."""
    if isinstance(node, str):
        return esc(node)
    kind, props = node["type"], node.get("props", {})
    if props.get("display") == "none" or props.get("position") == "absolute":  # tooltips, shown on hover only
        return ""
    inner = "".join(element(c) for c in node.get("children", []))
    if kind == "Raster":
        return raster(props)
    if kind == "Text":
        fg = color(props["color"]) if props.get("color") else ""
        style = []
        if props.get("inverse"):
            style += [f"background: {fg or 'var(--text)'}", "color: var(--panel)"]
        elif fg:
            style.append(f"color: {fg}")
        if props.get("dimColor") and not fg:
            style.append("color: var(--muted)")
        if props.get("bold"):
            style.append("font-weight: 700")
        return f'<span style="{"; ".join(style)}">{inner}</span>'
    if kind == "Button":
        label = esc(props.get("label", ""))
        return f'<span style="color: var(--muted)">{label}</span>' if props.get("plain") else \
            f'<span class="button">{label}</span>'
    if kind == "Link":
        return f'<span class="link">{esc(props.get("label", ""))}</span>'
    style = []
    if props.get("borderStyle"):
        style.append(f"border-color: {color(props.get('borderColor', 'gray'))}")
    if props.get("paddingX"):
        style.append(f"padding-left: {props['paddingX']}ch; padding-right: {props['paddingX']}ch")
    if props.get("marginRight"):
        style.append(f"margin-right: {props['marginRight']}ch")
    if props.get("marginTop"):
        style.append(f"margin-top: {props['marginTop'] * 1.5}em")
    if props.get("flexWrap") == "wrap":
        style.append("flex-wrap: wrap")
    if props.get("alignItems") == "center":
        style.append("align-items: center")
    cls = ("col" if props.get("flexDirection") == "column" else "row") + (" box" if props.get("borderStyle") else "")
    return f'<div class="{cls}" style="{"; ".join(style)}">{inner}</div>'


def pane(tree, minute):
    """The Claude Code mod's pane. Its last line says when the board was read, in the machine's own time zone (the
    test kit's child does not take TZ): it is set to the story's clock, so the picture is the same on every machine."""
    def story_time(node):
        if isinstance(node, dict):
            kids = node.get("children", [])
            if node.get("type") == "Text" and len(kids) >= 2 and kids[1] == " 時点 · 1 分ごとに更新 ":
                kids[0] = clock(minute)[11:16]
            for kid in kids:
                story_time(kid)
    story_time(tree)
    return window("task-hub", f'<div class="mono pane">{element(tree)}</div>')


ICONS = {  # simple shapes of our own for the codicons the Kiro view names (VS Code draws them from its font)
    "error": '<circle cx="8" cy="8" r="6" fill="none" stroke-width="1.6"/><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke-width="1.6"/>',
    "eye": '<path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" fill="none" stroke-width="1.4"/><circle cx="8" cy="8" r="2" fill="none" stroke-width="1.4"/>',
    "git-merge": '<circle cx="4.5" cy="3.5" r="1.8" fill="none" stroke-width="1.4"/><circle cx="4.5" cy="12.5" r="1.8" fill="none" stroke-width="1.4"/><circle cx="11.5" cy="9" r="1.8" fill="none" stroke-width="1.4"/><path d="M4.5 5.3v5.4M4.5 6c0 2.5 2.5 3 5.2 3" fill="none" stroke-width="1.4"/>',
    "sync": '<path d="M13 8a5 5 0 0 1-9 3M3 8a5 5 0 0 1 9-3" fill="none" stroke-width="1.5"/><path d="M12 2.5V5H9.5M4 13.5V11h2.5" fill="none" stroke-width="1.5"/>',
    "play": '<path d="M5 3.5l7 4.5-7 4.5z" fill="none" stroke-width="1.4" stroke-linejoin="round"/>',
    "circle-outline": '<circle cx="8" cy="8" r="5.5" fill="none" stroke-width="1.4"/>',
    "pass": '<circle cx="8" cy="8" r="6" fill="none" stroke-width="1.5"/><path d="M5.2 8.2l2 2 3.8-4" fill="none" stroke-width="1.6"/>',
    "request-changes": '<path d="M3 13l1-3.5 6.5-6.5 2.5 2.5L6.5 12z" fill="none" stroke-width="1.4" stroke-linejoin="round"/>',
    "info": '<circle cx="8" cy="8" r="6" fill="none" stroke-width="1.4"/><path d="M8 7.2v4M8 4.6v.1" stroke-width="1.6" stroke-linecap="round"/>',
    "git-pull-request": '<circle cx="4.5" cy="3.5" r="1.8" fill="none" stroke-width="1.4"/><circle cx="4.5" cy="12.5" r="1.8" fill="none" stroke-width="1.4"/><circle cx="11.5" cy="12.5" r="1.8" fill="none" stroke-width="1.4"/><path d="M4.5 5.3v5.4M11.5 10.7V6.5c0-1.5-1-2.5-2.5-2.5H7" fill="none" stroke-width="1.4"/>',
    "check": '<path d="M3.5 8.5l3 3 6-6.5" fill="none" stroke-width="1.6"/>',
    "checklist": '<path d="M2.5 4.5l1.3 1.3L6 3.5M2.5 10.5l1.3 1.3L6 9.5M8 4.5h5.5M8 10.5h5.5" fill="none" stroke-width="1.4"/>',
}


def icon(name, paint):
    shape = ICONS.get(name, "")
    return f'<svg viewBox="0 0 16 16" stroke="{paint}" fill="{paint}">{shape}</svg>' if shape else \
        '<svg viewBox="0 0 16 16"></svg>'


def kiro(view):
    """The Kiro extension's side bar: its view's nodes (kiro/board-extension/src/board.ts tree()), drawn as VS Code
    draws a tree, and its status bar item."""
    rows = []

    def node(n, depth):
        kids = n.get("children")
        twist = ("▾" if n.get("open") else "▸") if kids else ""
        paint = THEMED.get(n.get("color", ""), "var(--muted)")
        desc = f'<span class="desc">{esc(n["description"])}</span>' if n.get("description") else ""
        heading = ' style="font-weight: 700"' if n["id"].startswith("group/") else ""
        rows.append(f'<div class="node" style="padding-left: {8 + 14 * depth}px"><span class="twist">{twist}</span>'
                    f'{icon(n["icon"], paint) if n.get("icon") else ""}<span{heading}>{esc(n["label"])}</span>{desc}</div>')
        for kid in kids or [] if n.get("open") else []:
            node(kid, depth + 1)

    for n in view["tree"]:
        node(n, 0)
    bar = view["bar"]["text"].replace("$(checklist) ", "")
    return window("Kiro", '<div class="kiro"><div class="title">TASK-HUB</div>'
                          '<div class="section"><span>▸</span>船</div><div class="section"><span>▾</span>ボード</div>'
                          f'{"".join(rows)}<div style="height: 10px"></div>'
                          f'<div class="status">{icon("checklist", "var(--on-accent)")}{esc(bar)}</div></div>')


# --- what each picture shows ---

# The 4 screens (docs/media.md says which feature card of docs/brand.md each one goes with): the board at the moment
# card 12 waits in review, card 13 runs, and card 14 waits for your answer.
SCREENS = {
    "list": lambda s: (terminal(s.said, ["in review"]), 900),
    "claude-board": lambda s: (s.pane("in review"), 510),
    "kiro-board": lambda s: (s.kiro("in review"), 520),
    "review": lambda s: (terminal(s.said, ["findings", "digest"]), 900),
}
# The layers of docs/brand.md section 4, in its order: one screen each, for the LP's layer picture
LAYERS = {
    "1-card": lambda s: (s.pane("ready"), 510),
    "2-runner": lambda s: (terminal(s.said, ["agent"]), 900),
    "3-worktree": lambda s: (terminal(s.said, ["branch", "status"], "notes-app (task/12)"), 900),
    "4-agent": lambda s: (terminal(s.said, ["report"], "notes-app (task/12)"), 900),
    "5-review": lambda s: (terminal(s.said, ["log"]), 900),
    "6-pr": lambda s: (terminal(s.said, ["digest"]), 900),
    "7-merge-queue": lambda s: (terminal(s.said, ["merge", "queued"]), 900),
    "8-merge": lambda s: (terminal(s.said, ["events"]), 900),
}
# The moving picture: (seconds, who acts, what happens, the terminal's commands, the board's moment)
FLOW = [
    (1.8, "you", "You move card #12 to Ready.", ["ready"], "ready"),
    (1.8, "task-hub", "task watch starts it on branch task/12, in a worktree of its own.", ["branch", "status"],
     "agent"),
    (1.8, "agent", "Your local agent writes the change, runs the tests, and writes a report.", ["report"], "agent"),
    (2.0, "agent", "Another agent checks each acceptance criterion and sends it back.", ["findings"], "review"),
    (1.8, "agent", "The agent fixes it. The second review says pass.", ["log"], "retry"),
    (1.8, "task-hub", "task-hub opens the PR and writes the report on the Issue.", ["digest"], "in review"),
    (1.6, "you", "You approve the PR for the merge queue.", ["merge"], "queued"),
    (2.6, "task-hub", "The merge queue merges it. The Issue closes, and the card is Done.", ["events"], "merged"),
]
FLOW_WIDTH = 1200
# The largest each file may be: the README and the LP load them on every visit
LIMITS = {".gif": 5_000_000, ".webm": 2_000_000, ".avif": 2_000_000, ".png": 700_000}


class Shown:
    """The story's text and the boards as drawn by their own code, for the pages."""

    def __init__(self, boards, said, panes, views):
        self.boards, self.said, self.panes, self.views = boards, said, panes, views

    def pane(self, name):
        return pane(json.loads(json.dumps(self.panes[name])), MINUTES[name])

    def kiro(self, name):
        return kiro(self.views[name])

    def frame(self, i):
        seconds, actor, what, commands, board = FLOW[i]
        label, paint = ACTORS[actor]
        steps = "".join(f'<span style="background: {ACTORS[a][1] if n <= i else "var(--line)"}"></span>'
                        for n, (_, a, *_) in enumerate(FLOW))
        return (f'<div class="step"><span class="chip" style="color: {paint}; border-color: {paint}">{label}</span>'
                f"{esc(what)}</div>"
                f'<div class="duo">{terminal(self.said, commands)}{self.pane(board)}</div>'
                f'<div class="progress">{steps}</div>')


def pictures(shown):
    """{file name: (the page's main, its width)} for every still picture, in both themes."""
    out = {}
    for theme in ("dark", "light"):
        for name, make in SCREENS.items():
            out[f"{name}-{theme}.png"] = (*make(shown), theme)
        for name, make in LAYERS.items():
            out[f"layers/{name}-{theme}.png"] = (*make(shown), theme)
    return out


# --- what must never show: the owner's own board and work, this machine, a date, an e-mail address ---

PRIVATE = re.compile(r"jyoka|aica|AIprogramming|ai-CA_RA|task-sandbox", re.I)
DATES = [re.compile(p) for p in (
    r"\b(?:19|20)\d\d\s*[-/.年:]\s*(?:0?[1-9]|1[0-2])\s*[-/.月:]\s*(?:0?[1-9]|[12]\d|3[01])(?!\d)",  # 2026-10-29
    r"\b(?:19|20)\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\b",  # 20261029
    r"(?:^|\D)(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日")]  # 10月29日
EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")
PATHS = re.compile(r"/Users/|/home/|/var/folders/|/private/|/tmp/|[A-Za-z]:\\Users\\", re.I)
COMMON_NAMES = {"runner", "user", "admin", "you", "root"}  # login names that are also everyday words


def this_machine():
    """The strings that name this machine and its user: the home folder, the temp folder, the login name, the git
    e-mail address."""
    names = {str(Path.home()), tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())}
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    if len(user) >= 4 and user.lower() not in COMMON_NAMES:
        names.add(user)
    email = run(["git", "config", "--get", "user.email"]).stdout.strip() if shutil.which("git") else ""
    return {n for n in names | ({email} if email else set()) if len(n) > 1}


def leaks(text, machine=None):
    """What in the text must not be in a picture: [(kind, match)], or []."""
    found = [("private name", m.group()) for m in PRIVATE.finditer(text)]
    found += [("date", m.group().strip()) for p in DATES for m in p.finditer(text)]
    found += [("e-mail address", m.group()) for m in EMAIL.finditer(text)]
    found += [("local path", m.group()) for m in PATHS.finditer(text)]
    found += [("this machine", name) for name in sorted(machine if machine is not None else this_machine())
              if name in text]
    return found


def leaks_in_bytes(data, machine=None, today=None):
    """The same in a file's bytes (its metadata), where a pattern would match the compressed data by chance: only
    fixed strings, today's date, and the date and path forms written as text."""
    text = data.decode("latin-1")
    today = today or datetime.date.today()
    found = [("date", form) for form in (today.strftime("%Y-%m-%d"), today.strftime("%Y:%m:%d"),
                                         today.strftime("%Y/%m/%d"), today.strftime("%Y%m%d")) if form in text]
    found += [("private name", m.group()) for m in re.finditer(r"jyoka|aica|AIprogramming", text)]
    found += [("local path", m.group()) for m in re.finditer(r"/Users/|/home/|/var/folders/|/private/var/", text)]
    found += [("this machine", name) for name in sorted(machine if machine is not None else this_machine())
              if name in text]
    found += [("metadata", chunk) for chunk in png_chunks(data) if chunk in ("tEXt", "iTXt", "zTXt", "tIME", "eXIf")]
    return found


def png_chunks(data):
    """The chunk types of a PNG, in order ([] for any other file)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return []
    out, at = [], 8
    while at + 8 <= len(data):
        size = int.from_bytes(data[at:at + 4], "big")
        out.append(data[at + 4:at + 8].decode("latin-1"))
        at += 12 + size
    return out


def visible(html):
    """The text a page shows: no style, no script, no tags."""
    import html as markup
    text = re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.S)
    return markup.unescape(re.sub(r"<[^>]+>", "", text))


# --- the tools on this Mac: Chrome takes the pictures, ffmpeg writes the moving picture. Neither is in the repo ---

CHROMES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium", "google-chrome", "chromium", "chromium-browser"]
NEEDS = {
    "chrome": "Google Chrome or Chromium takes the pictures (macOS: brew install --cask google-chrome). "
              "TASK_MEDIA_CHROME names another one",
    "ffmpeg": "ffmpeg writes the GIF, the WebM (VP9), and the AVIF (AV1) (macOS: brew install ffmpeg)",
    "node": "Node.js 22.18 or later draws the Kiro view with its own code (macOS: brew install node)",
    "claude": "Claude Code's CLI draws the mod's pane with `claude plugin test` (https://claude.com/claude-code)",
}


def tool(name):
    if name == "chrome":
        for candidate in [os.environ.get("TASK_MEDIA_CHROME", ""), *CHROMES]:
            found = candidate and (candidate if Path(candidate).is_file() else shutil.which(candidate))
            if found:
                return found
        return None
    return shutil.which(name)


def missing_tools():
    """[(tool, why and how to get it)] for each tool that is not here or cannot do its part."""
    missing = [(name, why) for name, why in NEEDS.items() if not tool(name)]
    if tool("ffmpeg"):
        encoders = run([tool("ffmpeg"), "-hide_banner", "-encoders"]).stdout
        muxers = run([tool("ffmpeg"), "-hide_banner", "-muxers"]).stdout
        lacks = [e for e in ("gif", "libvpx-vp9", "libsvtav1") if not re.search(rf"\s{e}\s", encoders)]
        lacks += [] if re.search(r"\savif\s", muxers) else ["avif"]
        if lacks:
            missing.append(("ffmpeg", f"this ffmpeg cannot write {', '.join(lacks)}: {NEEDS['ffmpeg']}"))
    if tool("node"):
        version = run([tool("node"), "--version"]).stdout.strip().lstrip("v").split(".")
        if [int(v) for v in version[:2] if v.isdigit()] < [22, 18]:
            missing.append(("node", f"node is {'.'.join(version)}: {NEEDS['node']}"))
    return missing


def shoot(html, out, width, work, scale=2):
    """Chrome without a window, with a profile of its own: once to measure the page, once to take it at that size."""
    f = work / "page.html"
    f.write_text(html, encoding="utf-8")
    chrome = [tool("chrome"), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
              "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--force-color-profile=srgb",
              "--font-render-hinting=none", f"--user-data-dir={work / 'chrome-profile'}"]
    dom = run([*chrome, f"--window-size={width},600", "--dump-dom", f.as_uri()], timeout=60)
    height = re.search(r'data-height="(\d+)"', dom.stdout)
    if not height:
        raise SystemExit(f"Chrome did not measure the page ({dom.returncode}):\n{dom.stderr[-2000:]}")
    shot = work / "shot.png"
    shot.unlink(missing_ok=True)
    r = run([*chrome, f"--window-size={width},{height[1]}", f"--force-device-scale-factor={scale}",
             f"--screenshot={shot}", f.as_uri()], timeout=60)
    if not shot.exists():
        raise SystemExit(f"Chrome took no picture ({r.returncode}):\n{r.stderr[-2000:]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(shot), "-pred", "mixed", "-compression_level", "9", str(out))  # smaller, and no metadata


NO_METADATA = ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact"]  # no dates, no tool versions


def ffmpeg(*args):
    r = run([tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args[:-1], *NO_METADATA, args[-1]],
            timeout=300)
    if r.returncode:
        raise SystemExit(f"ffmpeg failed ({r.returncode}): {' '.join(args)}\n{r.stderr}")


def encode(frames, seconds, out):
    """The frames, each shown for its seconds, as a GIF (each frame once, with its own delay), a WebM (VP9), and an
    AVIF (AV1), all without sound or metadata."""
    listing = frames[0].parent / "frames.ffconcat"
    lines = ["ffconcat version 1.0"]
    for frame, s in zip(frames, seconds):
        lines += [f"file '{frame.name}'", f"duration {s:.3f}"]
    # the last frame once more, briefly: concat and the GIF give a frame its length from the next one's start
    lines += [f"file '{frames[-1].name}'", "duration 0.100", f"file '{frames[-1].name}'"]
    listing.write_text("\n".join(lines) + "\n")
    concat = ["-f", "concat", "-safe", "0", "-i", str(listing), "-t", f"{sum(seconds) + 0.1:.3f}"]
    width = FLOW_WIDTH
    ffmpeg(*concat, "-vf", f"scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=full[p];"
                           "[b][p]paletteuse=dither=none", "-fps_mode", "vfr", "-loop", "0", str(out.with_suffix(".gif")))
    video = ["-vf", f"fps=10,scale={width * 2}:-2:flags=lanczos,format=yuv420p", "-an"]
    ffmpeg(*concat, *video, "-c:v", "libvpx-vp9", "-crf", "38", "-b:v", "0", "-row-mt", "1",
           str(out.with_suffix(".webm")))
    ffmpeg(*concat, *video, "-c:v", "libsvtav1", "-crf", "40", "-preset", "6", "-f", "avif",
           str(out.with_suffix(".avif")))


# --- the whole run ---

PANE_COLUMNS = 52  # the mod's pane, as wide as the board's half of the moving picture
TEXTS = "text.json"  # what each picture shows, as text: tests/test_media.py checks it without reading the pictures


def expected_files():
    """Every file `python3 tests/media.py` writes in assets/media/, by its path there."""
    stills = [f"{n}-{t}.png" for t in ("dark", "light") for n in SCREENS]
    layers = [f"layers/{n}-{t}.png" for t in ("dark", "light") for n in LAYERS]
    return sorted(["flow.gif", "flow.webm", "flow.avif", *stills, *layers, TEXTS])


def problems(folder, texts):
    """What is wrong with the files in folder: a missing or extra file, one over its size limit, or a picture whose
    text or bytes show something private. [] when all is well."""
    found = []
    have = sorted(str(f.relative_to(folder)) for f in folder.rglob("*") if f.is_file() and f.name != ".DS_Store")
    found += [f"missing: {name}" for name in expected_files() if name not in have]
    found += [f"not written by tests/media.py: {name}" for name in have if name not in expected_files()]
    machine = this_machine()
    for name in have:
        f = folder / name
        limit = LIMITS.get(f.suffix)
        if limit and f.stat().st_size > limit:
            found.append(f"{name}: {f.stat().st_size} bytes, over the limit of {limit}")
        found += [f"{name}: shows a {kind}: {match}" for kind, match in leaks_in_bytes(f.read_bytes(), machine)]
        if name != TEXTS:
            if name not in texts:
                found.append(f"{name}: not in {TEXTS}")
            found += [f"{name}: shows a {kind}: {match}" for kind, match in leaks(texts.get(name, ""), machine)]
    return found


def take(work):
    world_root = work / "home"
    world_root.mkdir()
    print("running card #12 through bin/task, against the fake GitHub ...", flush=True)
    boards, said = story(World(world_root))
    print("drawing the boards with the mod's and the Kiro extension's own code ...", flush=True)
    shown = Shown(boards, said, mod_panes(boards, PANE_COLUMNS, work), kiro_views(boards, work))
    out = work / "media"
    texts = {}
    pages = {name: (page(main, theme, width), width) for name, (main, width, theme) in pictures(shown).items()}
    frames = [page(shown.frame(i), "dark", FLOW_WIDTH) for i in range(len(FLOW))]
    for name, (html, _) in pages.items():
        texts[name] = visible(html)
    texts["flow.gif"] = texts["flow.webm"] = texts["flow.avif"] = "\n".join(visible(html) for html in frames)
    machine = this_machine()
    bad = [f"{name}: shows a {kind}: {match}" for name, text in texts.items() for kind, match in leaks(text, machine)]
    if bad:  # before Chrome takes anything
        raise SystemExit("the pictures would show what they must not:\n" + "\n".join(bad))
    for name, (html, width) in pages.items():
        print(f"  {name}", flush=True)
        shoot(html, out / name, width, work)
    for i, html in enumerate(frames):
        print(f"  flow frame {i + 1}/{len(frames)}", flush=True)
        shoot(html, work / "frames" / f"frame-{i:02d}.png", FLOW_WIDTH, work)
    print("  flow.gif, flow.webm, flow.avif", flush=True)
    encode(sorted((work / "frames").glob("frame-*.png")), [f[0] for f in FLOW], out / "flow")
    (out / TEXTS).write_text(json.dumps(dict(sorted(texts.items())), ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    bad = problems(out, texts)
    if bad:
        raise SystemExit("not written to assets/media/:\n" + "\n".join(bad))
    for name in expected_files():  # only now: a failed run leaves the pictures as they were
        (MEDIA / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / name, MEDIA / name)
    for f in MEDIA.rglob("*"):
        if f.is_file() and str(f.relative_to(MEDIA)) not in expected_files():
            f.unlink()
    print(f"wrote {len(expected_files())} files to assets/media/")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--text", action="store_true", help="run the card and print what the screens show")
    parser.add_argument("--check", action="store_true", help="only check the files in assets/media/")
    a = parser.parse_args()
    if a.check:
        texts = json.loads((MEDIA / TEXTS).read_text(encoding="utf-8")) if (MEDIA / TEXTS).exists() else {}
        bad = problems(MEDIA, texts)
        print("\n".join(bad) or f"assets/media/: {len(expected_files())} files, all within limits, nothing private")
        return 1 if bad else 0
    with tempfile.TemporaryDirectory(prefix="task-hub-media-") as work:
        work = Path(work)
        if a.text:
            (work / "home").mkdir()
            boards, said = story(World(work / "home"))
            for name, (command, output) in said.items():
                print(f"--- {name}\n$ {command}\n{output}")
            bad = [f"{name}: {kind}: {m}" for name, (c, o) in said.items() for kind, m in leaks(c + "\n" + o)]
            print("\n".join(bad) or "nothing private in the text")
            return 1 if bad else 0
        missing = missing_tools()
        if missing:
            print("tests/media.py needs these tools, and writes nothing without them (docs/media.md):", file=sys.stderr)
            for name, why in missing:
                print(f"- {name}: {why}", file=sys.stderr)
            return 2
        take(work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
