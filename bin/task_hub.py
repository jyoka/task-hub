"""task - run coding agents on the tasks of a GitHub Project board. bin/task starts this module (see its docstring).

The board is a GitHub Project. Each task is an Issue in a (private) issues repo; the Project's
Status column says where it is, and its Target repo / Agent / Base branch fields say where, by whom, and
from which branch it is worked on.
Move a card to Ready (or run `task start`) and task-hub runs it on this machine: a git worktree on
branch `task/<number>`, a herdr workspace (or a background process without herdr), and the agent
CLI of your choice (claude, codex, pi, kiro, ...). The agent only edits files and writes
`.task-report.md`; task-hub commits, pushes, opens the PR, comments the report on the Issue, and
moves the card. At most [runner] parallel tasks (5 by default) are In progress at once.

Board: Backlog -> Ready -> In progress -> In review -> Done   (or Blocked)
An optional "wait for merge" column between In review and Done holds reviewed cards
whose PR is approved but not merged yet; the merged PR moves them to Done as usual.
With [merge] queue = on, an approved PR (`task merge`, or that column) is kept up to date with its base, its
conflicts fixed by an agent, and merged once its checks pass: one PR at a time per repo.
"""
import configparser
import contextlib
import datetime
from functools import cache
import json
import os
import re
import shlex
import signal
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlencode


class Lazy:
    """A standard module imported where it is first used, not at every start: `task list` and the other quick commands
    often need neither subprocess nor shutil (about 20 ms on an efficiency core, docs/benchmark.md). Modules used in
    a function or two are imported in it instead."""

    def __init__(self, name):
        self.name = name

    def __getattr__(self, attr):
        module = globals()[self.name] = __import__(self.name)
        return getattr(module, attr)


subprocess, shutil = Lazy("subprocess"), Lazy("shutil")

BIN = Path(__file__).resolve().parent / "task"  # the launcher: `task` runs it, and so do the runs task-hub starts


def launcher_version(launcher):
    """The VERSION line of a bin/task, or "unknown". The release's version is written there (docs/release.md), so the
    `task update` of a release from before task_hub.py reads the new one too. Read without a regex: it runs at every
    start."""
    try:
        text = launcher.read_text(errors="replace")
    except OSError:
        return "unknown"
    for line in text.splitlines():
        if line.startswith('VERSION = "'):
            version, closed, _ = line[len('VERSION = "'):].partition('"')
            if version and closed:
                return version
    return "unknown"


VERSION = launcher_version(BIN)
PARALLEL = 5  # [runner] parallel by default: tasks In progress at once
REVIEW_RETRIES = 2  # [runner] review_retries by default: how many times the reviewer may send the work back
MAX_CARDS = 100  # over this many cards on the Project, the Done ones moved longest ago are archived (their Issues stay)
# the column names of GitHub's Kanban template, plus Blocked and wait for merge; matched without regard to case
BACKLOG, READY, IN_PROGRESS, IN_REVIEW, WAIT_FOR_MERGE, BLOCKED, DONE = \
    ["Backlog", "Ready", "In progress", "In review", "wait for merge", "Blocked", "Done"]
TEXT_FIELDS = ["Target repo", "Agent", "Base branch"]  # "Repo" is a reserved field name on GitHub
REPORT_FILE = ".task-report.md"
REVIEW_FILE = ".task-review.md"
# never committed: our own files, and Python bytecode that test runs leave in repos without a .gitignore
# (it reached a PR in jyoka/tasks#43)
REPLAN_FILE = ".task-replan.md"
READINESS_FILE = ".task-readiness.md"  # what each Goldfish of `task check` writes, in a worktree of its own
NEVER_COMMIT = [REPORT_FILE, REVIEW_FILE, REPLAN_FILE, READINESS_FILE, "__pycache__/", "*.pyc"]
REPORT_MARK = "<!-- task-hub report -->"
REPLAN_MARK = "<!-- task-hub replan -->"
READINESS_MARK = "<!-- task-hub readiness -->"  # `task check`'s verdict on the Goal; the last one counts
MERGE_MARK = "<!-- task-hub merge -->"  # the merge queue's notes on the Issue: never the task's report
LINK_MARK = "<!-- task-hub link -->"  # a comment on the personal Issue: where `task share` put the task's copy
SHARED_MARK = "<!-- task-hub shared -->"  # the first line of the copy's body
SHARE_NOTICE = "> task-hub overwrites this body from a personal task board. Please write in the comments instead."
# the team's column for a personal Status, when [share] names none and the team has no column of the same name
SHARE_STATUS = {BACKLOG: "Todo", READY: IN_PROGRESS, IN_PROGRESS: IN_PROGRESS, IN_REVIEW: IN_PROGRESS,
                WAIT_FOR_MERGE: IN_PROGRESS, BLOCKED: IN_PROGRESS, DONE: DONE}
READINESS_FIELD = "Readiness"  # the Project's single-select field `task check` fills (made when missing)
READINESS_VERDICTS = ["GO", "NO-GO"]  # its options; a blocked check clears it
READINESS_MODES = ("off", "warn", "require")  # [runner] readiness: what starting a Ready card asks of its Goal
REVIEW_FIELD = "Review"  # the Project's single-select field a run's last automated review fills (made when missing)
REVIEW_VERDICTS = ["pass", "needs changes", "blocked"]  # its options; a run without a review clears it
REVIEW_MODES = ("agent", "goldfish")  # [runner] review_mode: what the reviewer is given (build_review_prompt)
REVIEW_LINE = "<!-- task-hub review: "  # the machine-readable line of the report's Automated review (review_line)
RESEARCH_LABEL = "research"  # on the Issue: the deliverable is the agent's report, so no file change is fine
MAX_REPLAN_ANSWERS = 2  # per task; after that a Blocked task always waits for the human
WATCH_SECONDS = 60
# [notify] events: which events show a notification; empty = none. "update": a new task-hub release (`task watch`);
# "conflict": an In review PR that conflicts with its base now ([merge] queue = on);
# "autopilot": a card [autopilot] moved to Ready or queued for merge in the human's place;
# "over budget": a run used more than its budget (over_budget)
NOTIFY_EVENTS = "In review, Blocked, replan, Done, slow, update, conflict, autopilot, over budget"
# a line of the Goal that keeps [autopilot] off this one card, both its start and its merge (a note, a PRD, a step
# only a human can do). Also as a list item, in emphasis or code, with a period: a miss would start the card.
# Patterns like this one are kept as strings for re.search and the like, which compile one the first time it is used
# and keep it: compiling them all at every start took about 10 ms on an efficiency core (docs/benchmark.md)
AUTOPILOT_OFF = r"(?im)^[ \t]*(?:[-*+][ \t]+)?[*_`]*autopilot[*_`]*:[*_`]*[ \t]*[*_`]*off[*_`]*\.?[*_`]*[ \t]*$"
# a live run is "slow" once it runs SLOW_TIMES the median of its agent's finished runs, at least SLOW_FLOOR;
# with fewer than SLOW_MIN_RUNS finished runs, after SLOW_DEFAULT. Constants on purpose: nothing to configure
SLOW_TIMES, SLOW_FLOOR, SLOW_DEFAULT, SLOW_MIN_RUNS = 3, 15 * 60, 30 * 60, 3
# a run is "over budget" once what its launches used passes the Goal's Budget; without one, BUDGET_TIMES the median
# of its agent's finished runs, at least BUDGET_FLOOR; with fewer than BUDGET_MIN_RUNS of them, BUDGET_DEFAULT.
# Per measure: seconds, tokens (Claude Code, pi), cost in USD (pi) and credits (Kiro). Only an event, for now
BUDGET_TIMES = {"seconds": 10, "tokens": 5, "cost": 5, "credits": 5}
BUDGET_FLOOR = {"seconds": 3600, "tokens": 2_000_000, "cost": 1.0, "credits": 5.0}
BUDGET_DEFAULT = {"seconds": 3 * 3600, "tokens": 20_000_000, "cost": 10.0, "credits": 20.0}
BUDGET_MIN_RUNS = 10
AGENT_NEVER_RAN = ("start", "setup", "balance")  # a run's blocked_by when its agent never started: no usual time
# how long one [balance] check may take before the run is Blocked without starting the agent
BALANCE_SECONDS = int(os.environ.get("TASK_BALANCE_SECONDS") or 60)  # tests: a hanging check fails in a second
# how long a herdr pane gets to begin the run, twice (the second time after one more Enter)
HERDR_START_SECONDS = float(os.environ.get("TASK_HERDR_START_SECONDS") or 8)  # tests: a dead pane fails in seconds
CLAUDE_P = ("env CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 BASH_DEFAULT_TIMEOUT_MS=1800000 BASH_MAX_TIMEOUT_MS=1800000"
            " claude -p --dangerously-skip-permissions --output-format stream-json --verbose")
# pi's bash tool through worker/group-shell (command_groups_env): -e loads it, with --no-extensions too
PI_GROUPS = Path(__file__).resolve().parent.parent / "pi" / "task-groups.ts"
# {session}: a new UUID for each launch (claude wants a UUID); a resume passes the one of the launch it goes on with
DEFAULT_AGENTS = {
    "claude": f"{CLAUDE_P} --session-id {{session}} {{prompt}}",
    "codex": "codex exec -s workspace-write --json {prompt}",
    "pi": f"pi -p --mode json -e {shlex.quote(str(PI_GROUPS))} --session-id {{session}} {{prompt}}",
    "kiro": "kiro-cli chat --no-interactive --trust-all-tools --output-format stream-json {prompt}",
}
# [resume] <name> by default, while [agents] <name> is the built-in one (resume_command): it goes on with the
# conversation saved under {session}. pi's --session-id makes the session when it is missing and goes on with it when
# it is there (checked on pi 1.4.0); claude's --session-id refuses a session that is there, and --resume one that is not
DEFAULT_RESUME = {
    "claude": f"{CLAUDE_P} --resume {{session}} {{prompt}}",
    "pi": DEFAULT_AGENTS["pi"],
}
LOG_LINE_MAX = 200  # a step of an agent's JSON output, as one log line (docs/operations.md)
# [sandbox] mode = user (docs/sandbox.md): the agent, and every git command and file task-hub touches in the shared
# clones and worktrees, run as this Linux user, which cannot read your HOME (decision 28)
SANDBOX_USER = "task-agent"
SANDBOX_GROUP = "task-agents"  # what workenv_setting's setup_agent_user.sh gives the shared folders' ACLs to
RULES_FILE = ".claude/settings.local.json"  # the Goal's Rules, as Claude Code permissions (docs/task-format.md)
RULE_LEVELS = {"can": "allow", "ask": "ask", "never": "deny"}
CI_MINUTES = 60  # [merge] ci_minutes by default: how long the merge queue waits for a PR's checks before it blocks the card

WORKER_PROMPT = BIN.parent.parent / "worker" / "PROMPT.md"
WORKER_REVIEW = BIN.parent.parent / "worker" / "REVIEW.md"
WORKER_REPLAN = BIN.parent.parent / "worker" / "REPLAN.md"
WORKER_CONFLICT = BIN.parent.parent / "worker" / "CONFLICT.md"
WORKER_READINESS = BIN.parent.parent / "worker" / "READINESS.md"
WORKER_DRIFT = BIN.parent.parent / "worker" / "DRIFT.md"
GROUP_SHELL = BIN.parent.parent / "worker" / "group-shell"  # what the agents' tool commands run in (command_groups_env)
CONFIG = Path.home() / ".config" / "task-hub" / "config.ini"
DATA = Path.home() / ".local" / "share" / "task-hub"
# mode = user has run here: until repos/ and worktrees/ are gone, mode = off must not trust what the agent left there
SANDBOX_USED = DATA / "sandbox-used"
STATE = Path.home() / ".local" / "state" / "task-hub"
LOGS = STATE / "logs"
RUNS = STATE / "runs"  # what this machine knows about each run: never on GitHub
METRICS = STATE / "metrics.jsonl"  # one line per finished run on this machine, for `task stats`
REVIEW_TRIALS = STATE / "review-trials.jsonl"  # one line per `task review --no-write`, never in METRICS either
CHECKS = STATE / "checks.jsonl"  # one line per `task check`, for `task stats`: never in METRICS, whose readers count runs
READINESS = STATE / "readiness.json"  # the last readiness verdict read of each card, so a check of the board reads
#                                       an Issue's comments only when its Goal or card changed (readiness_gate)
# one line per status change task-hub makes, and per Done GitHub makes on a card this machine ran,
# for whatever watches (see docs/operations.md)
EVENTS = STATE / "events.jsonl"
ASKED = STATE / "asked"  # the herdr workspace each task was asked for in, so its tab opens there
LIB = BIN.parent.parent  # the clone `task` runs from (~/.local/lib/task-hub, docs/setup.md)
UPDATE = STATE / "update.json"  # the newest v* tag seen on origin, when origin was asked, and which one was notified
# origin is asked at most once a day (again after an hour when it could not be reached), for at most UPDATE_TIMEOUT
UPDATE_EVERY, UPDATE_RETRY, UPDATE_TIMEOUT = 24 * 3600, 3600, 5
EASY_SETUP_FIRST = (0, 12, 0)  # the first release the easy setup's installers put their clone on (docs/release.md)
WATCH_LABEL = "com.task-hub.watch"  # the launchd job of docs/setup.md
# Kiro reads these only as copies, never links (docs/kiro-ide.md): `task update` copies them again
KIRO_COPIES = {"kiro-hook": ("kiro/hooks/task-hub-events.json", ".kiro/hooks/task-hub-events.json"),
               "kiro-workflow": ("kiro/workflows/task-hub-events.workflow.json",
                                 ".kiro/workflows/task-hub-events.workflow.json")}
# [triggers] (docs/triggers.md): what they made a card for, so each CI run, Issue, and period gets one card
TRIGGERS = STATE / "triggers.json"
TRIGGER_SECONDS = float(os.environ.get("TASK_TRIGGER_SECONDS") or 300)  # `task watch` checks them at most this often
INSTALL_MANIFEST = STATE / "install-manifest.json"  # kiro/install.sh's record of the copies it owns
RUN_KEYS = ["repo", "title", "agent", "base", "branch", "started", "pid", "workspace", "tab", "worktree", "log", "pr",
            "research", "stage", "link", "link_project", "agent_pid", "agent_started", "head", "snap", "review_attempt",
            "interrupted", "resumes", "resumed", "resume_stage", "resumed_at", "session", "session_role", "budget",
            "paid_api", "over_budget"]
# stage: where the run is (docs/design.md); never on GitHub or in EVENTS.
# link: the team's Issue (`task share`) as launch read it, so finish adds its Closes without asking GitHub again.
# agent_pid, agent_started: the agent running now (its own process group, agent_process), so what is left of it can be
# stopped. head: HEAD before the agent's launch. snap: `<tree> <HEAD>` while a reviewer or replanner runs, so a run
# that dies before restore leaves the next launch something to restore. review_attempt: which review is running
# (0 to [runner] review_retries), and during a retry that retry's number (review_loop).
# interrupted: why the run or its agent last stopped (SIGHUP, SIGTERM, SIGINT, "the agent was killed (SIGKILL)",
# "silent" when the Watchdog stopped the agent, "the run process is gone"). resumes: how often this run was resumed
# (MAX_RESUMES), resumed: the stages it was resumed at, space-separated. resume_stage: where relaunch tells the next
# `_run` to go on from (it reads and empties it), resumed_at: when relaunch started it again. session: the {session}
# of the task's agent's last launch, session_role: that launch's stage (agent, retry), so a resume there goes on with
# its conversation. launch empties them all (RUN_FRESH).
# budget: the Goal's Budget limits as launch read them ({"tokens": 3000000, ...}), paid_api: the paid APIs it names,
# space-separated (check_balance). over_budget: the measures this run has had an `over budget` event for
RUN_FRESH = ("agent_pid", "agent_started", "head", "snap", "review_attempt", "interrupted", "resumes", "resumed",
             "resume_stage", "resumed_at", "session", "session_role", "over_budget")
MAX_RESUMES = 1  # a run that stops unexpectedly is resumed this often, then Blocked (decision 7); no setting
RESUME_STAGES = ("preparing", "setup", "agent", "review", "retry", "finishing")  # the stages a run can go on from
GH = os.environ.get("TASK_GH", "gh")
# the last open cards read from GitHub (raw items), so `task list` in every pane shares one read (docs/operations.md).
# A board change task-hub makes stamps BOARD_STALE; a cache read before that stamp is never used
BOARD_CACHE = STATE / "board-cache.json"
BOARD_STALE = STATE / "board-cache.stale"
BOARD_FETCHING = STATE / "board-cache.fetching"  # held by the one `task list` reading GitHub for the others
# `task watch` writes the cache every WATCH_SECONDS plus a sync; at 60 a pane would miss just before it about once a minute
LIST_MAX_AGE = 90
BOARD_META = STATE / "board-meta.json"  # the Project's id and field ids from board(), kept for META_MAX_AGE
META_MAX_AGE = 3600
# task feedback: a new Issue on task-hub's own repository, from a form in .github/ISSUE_TEMPLATE (not the board)
FEEDBACK_FORMS = {"bug": "bug_report.yml", "feature": "feature_request.yml"}
WINDOWS = os.name == "nt"  # docs/windows.md: no ps, env, sh or osascript, and batch files cut arguments at line breaks
# a process that outlives the command starting it: its own session; on Windows its own process group and a console
# without a window, which the programs it starts (git, the agent) share instead of each opening one
DETACHED = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if WINDOWS \
    else {"start_new_session": True}
# the agent and what it starts, as one group the run can stop: its own session (a closed pane's SIGHUP and Ctrl-C reach
# only the run, which stops the group), on Windows its own process group in the run's console (taskkill /T stops it)
AGENT_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
AGENT_STOP_SECONDS = 10  # how long a stopped agent has to exit before it is killed
# the watchdog (Watchdog, decision 19): an agent with no output for SILENT_SECONDS (claude's Bash may wait 30 minutes)
# whose descendants used no CPU since the last check gets those descendants stopped; still silent SILENT_GRACE
# later, the agent too. ps runs every SILENT_CHECK while it is that silent. Tests make them seconds
SILENT_SECONDS = float(os.environ.get("TASK_SILENT_SECONDS") or 45 * 60)
SILENT_GRACE = float(os.environ.get("TASK_SILENT_GRACE_SECONDS") or 10 * 60)
SILENT_CHECK = min(60.0, SILENT_SECONDS / 4)


# ---------- output (TOON) ----------

def q(v):
    if isinstance(v, int) and not isinstance(v, bool):  # a count is a number; a string that looks like one is quoted
        return str(v)
    s = "" if v is None else str(v)
    if s == "" or s != s.strip() or re.search(r'[,:"\\\[\]{}\n#]', s) or s in ("true", "false", "null") \
            or re.fullmatch(r"-?\d+(\.\d+)?", s):
        return json.dumps(s, ensure_ascii=False)
    return s


def out(*lines):
    print("\n".join(lines), flush=True)


def table(name, rows, cols):
    lines = [f"{name}[{len(rows)}]{{{','.join(cols)}}}:"]
    lines += ["  " + ",".join(q(r.get(c)) for c in cols) for r in rows]
    return lines


def fail(msg, help_=None, code=1):
    out(f"error: {msg}", *([f"help: {help_}"] if help_ else []))
    sys.exit(code)


def home(p):
    return str(p).replace(str(Path.home()), "~")


def run(*cmd, cwd=None, check=False):
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True)
    # not text=True: its universal newlines split a line git redraws with \r, which git_said keeps whole
    r.stdout, r.stderr = (b.decode(errors="replace").replace("\r\n", "\n") for b in (r.stdout, r.stderr))
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd[:3]))} failed: {git_said(r)}")
    return r


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_now():
    """The time in the machine's own zone, for a person reading a pane (`task list --watch`)."""
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def section(body, name):
    """Text under '## name' up to the next '## ' heading, or ''."""
    m = re.search(rf"(?m)^## {re.escape(name)}[ \t]*\n(.*?)(?=^## |\Z)", body, re.S)
    return m.group(1).strip() if m else ""


class StatusLifecycle:
    """Status policy for the task board lifecycle."""
    all = [BACKLOG, READY, IN_PROGRESS, IN_REVIEW, WAIT_FOR_MERGE, BLOCKED, DONE]
    optional = {WAIT_FOR_MERGE}
    startable_by_human = {BACKLOG, BLOCKED}
    startable_explicitly = {BACKLOG, BLOCKED, READY}
    watched_for_merge = {IN_REVIEW, WAIT_FOR_MERGE}
    needs_user = {BACKLOG, IN_REVIEW, BLOCKED}
    # (from, to) of every move task-hub itself makes; None = not on the board yet. A human's drag on GitHub and
    # GitHub's workflows are not in it: task-hub never makes them. docs/design.md draws it; keep the two in step.
    transitions = {
        (None, BACKLOG),  # cmd_new
        *{(s, READY) for s in startable_explicitly},  # cmd_start; Ready -> Ready changes only the Agent field
        (READY, IN_PROGRESS),  # launch
        (READY, BLOCKED), (IN_PROGRESS, BLOCKED),  # sync: launch failed; cmd_run: setup failed, finish raised; pid gone
        (IN_PROGRESS, IN_REVIEW),  # finish
        (IN_REVIEW, WAIT_FOR_MERGE), (BLOCKED, WAIT_FOR_MERGE), (BLOCKED, IN_REVIEW),  # cmd_merge: approved
        (WAIT_FOR_MERGE, IN_REVIEW),  # cmd_merge --cancel
        (IN_REVIEW, BLOCKED), (WAIT_FOR_MERGE, BLOCKED),  # the merge queue: a conflict or a check it cannot get past
        *{(s, DONE) for s in watched_for_merge},  # sync: the PR was merged
        *{(s, DONE) for s in all if s != DONE},  # cmd_done
    }

    @classmethod
    def expected(cls, before, after):
        return (before, after) in cls.transitions

    @classmethod
    def required(cls):
        return [s for s in cls.all if s not in cls.optional]

    @classmethod
    def canonical(cls, status):
        return next((s for s in cls.all if s.lower() == (status or "").lower()), status or BACKLOG)

    @classmethod
    def missing_required_options(cls, options):
        return [f'Status option "{s}"' for s in cls.required() if s.lower() not in options]

    @classmethod
    def needs_merge_watch(cls, t):
        # every card, not only Base branch ones: GitHub's "Closes ..." left a merged default-branch PR's Issue open
        # (jyoka/tasks#81), and nothing else would have moved that card to Done
        return t.get("status") in cls.watched_for_merge and re.fullmatch(r"[\w.-]+/[\w.-]+", t.get("repo") or "")

    @classmethod
    def needs_user_count(cls, counts):
        return sum(counts[s] for s in cls.needs_user)


STATUSES = StatusLifecycle.all



class ReviewResult:
    """Automated review verdict and feedback. Please fix holds the blocking findings, Known issues the minor ones: a
    review with only minor ones passes, and they go into the PR as known issues.
    mode: [runner] review_mode it was made in; attempt: which review of the run it is (1: the first), for review_line."""
    def __init__(self, markdown="", mode="agent", attempt=1):
        self.markdown = markdown or ""
        self.mode, self.attempt = mode, attempt
        # models often decorate the word: **Pass**, `pass`, Pass.
        self.verdict = (section(self.markdown, "Verdict").splitlines() or [""])[0].strip(" *`_.").lower()
        self.review = section(self.markdown, "Review")
        self.fix = section(self.markdown, "Please fix")
        self.minor = section(self.markdown, "Known issues")
        if self.verdict == "needs changes" and not self.fix and self.minor:  # nothing blocking: what it lists can wait
            self.verdict = "pass"

    @property
    def passed(self):
        return self.verdict == "pass"

    @property
    def needs_changes(self):
        return self.verdict == "needs changes"

    @property
    def findings(self):
        """The blocking findings, one per top-level list item of Please fix (the whole section when it has no list)."""
        return list_items(self.fix)

    def repeated(self, sent):
        """The findings that were already sent back once: marked (again), as worker/REVIEW.md asks, or word for word."""
        earlier = {finding_key(f) for f in sent}
        return [f for f in self.findings if re.match(AGAIN, finding_text(f)) or finding_key(f) in earlier]

    def blocked_line(self, stop=""):
        """One line for the card's Blocked reason: what happened (stop: why sending back stopped) and the reviewer's
        own first line."""
        first = ((self.review or self.fix).splitlines() or ["no details"])[0]
        return f"{stop or 'automated review: ' + (self.verdict or 'no verdict')}: {first}"

    @property
    def field_verdict(self):
        """The verdict as the Review field and review_line give it: pass, needs changes, or blocked (also for a
        review without a verdict, which blocks the card as blocked does)."""
        return self.verdict if self.verdict in REVIEW_VERDICTS else "blocked"

    def review_line(self):
        """The one line a program reads the review from (digest): an HTML comment, which GitHub does not show."""
        return REVIEW_LINE + json.dumps({"verdict": self.field_verdict, "blocking": len(self.findings) if self.fix else 0,
                                         "minor": len(list_items(self.minor)), "mode": self.mode,
                                         "attempt": self.attempt}) + " -->"

    def issue_section(self):
        verdict = self.verdict or "missing verdict"
        body = self.review or self.markdown.strip() or "reviewer produced no details"
        body += f"\n\n### Please fix\n\n{self.fix}" * bool(self.fix)
        body += f"\n\n### Known issues\n\nMinor findings, left for later: they did not stop the review.\n\n" \
                f"{self.minor}" * bool(self.minor)
        return f"## Automated review\n\n{self.review_line()}\nVerdict: {verdict}\n\n{body}"

    def suggested_instructions(self, stop, sent):
        """The draft of the next run's instructions, for the human to check before moving the card to Ready again."""
        repeated = self.repeated(sent)
        again = " (it came back after a retry)"
        items = "\n".join(f"{n}. {re.sub(AGAIN, '', finding_text(f), count=1)}" + again * (f in repeated)
                          for n, f in enumerate(self.findings, 1))
        return "\n\n".join([
            "## Suggested instructions",
            "A draft for the next run, made from the automated review above. Check it, then move the card to Ready: "
            "the next run reads this report, these instructions included. To change them, edit this comment or add "
            "one of your own.",
            f"The automated review stopped sending the work back: {stop}.",
            "Fix these findings of the automated review, then check every acceptance criterion again:",
            items or self.fix,
            "Fix the cause, not only the cases the review names: where the review proposes a change, take it as a "
            "hint, and add a test for each case it names. A finding you think is wrong: leave the code as it is and "
            "say why in your report. The Known issues can wait."])


def combine_reviews(found):
    """One ReviewResult from each Goldfish auditor's ({name: ReviewResult}, in the order they ran): blocked when any
    is blocked or wrote no verdict, else needs changes when any has a blocking finding, else pass (minor findings
    only pass, as one reviewer's do). A finding more than one auditor made counts once: the same words (finding_key),
    or the same place (finding_place) from another auditor, whose words are kept below the first as "Also". A minor
    one that is also blocking counts as blocking."""
    fix, minor = [], []
    for kind in ("fix", "minor"):
        for name, r in found.items():
            for f in (r.findings if r.fix else []) if kind == "fix" else list_items(r.minor):
                key, place = finding_key(f), finding_place(f)
                same = next((e for e in fix + minor if e["key"] == key or place and e["place"] == place
                             and name not in e["by"]), None)
                if same is None:
                    (fix if kind == "fix" else minor).append({"key": key, "place": place, "by": [name],
                                                              "text": finding_text(f), "also": []})
                elif same["key"] != key and name not in same["by"]:
                    same["by"].append(name)
                    same["also"].append(f"Also {name}: " + finding_text(f).replace("\n", "\n    "))
    shown = lambda items: "\n".join("- " + e["text"] + "".join(f"\n  - {a}" for a in e["also"]) for e in items)
    first = lambda r: ((r.review or r.fix).splitlines() or ["no details"])[0]
    stuck = [(n, r) for n, r in found.items() if r.verdict not in ("pass", "needs changes")]
    needs = [(n, r) for n, r in found.items() if r.needs_changes]
    if stuck:
        verdict, lead = "blocked", "; ".join(
            f"{n}: {first(r)}" if r.verdict == "blocked" else f"{n} wrote no verdict pass, needs changes or blocked "
            f"(it wrote {r.verdict or 'none'})" for n, r in stuck)
    elif needs:
        verdict, lead = "needs changes", "; ".join(f"{n}: {first(r)}" for n, r in needs)
    else:
        verdict, lead = "pass", f"{' and '.join(found)} passed it."
    about = (f"Goldfish review: {plural(len(found), 'auditor', 'auditors')}, each in a fresh context, read the Goal "
             "and the code, not the agent's report.")
    parts = [f"## Verdict\n\n{verdict}", f"## Review\n\n{lead}\n\n{about}",
             *(f"### {n}: {r.verdict or 'no verdict'}\n\n{r.review or 'no details'}" for n, r in found.items())]
    parts += ["## Please fix\n\n" + shown(fix)] * bool(fix)
    parts += ["## Known issues\n\n" + shown(minor)] * bool(minor)
    return ReviewResult("\n\n".join(parts), mode="goldfish")


AGAIN = r"(?i)\(again\)\s*"


def list_items(text):
    """One string per top-level list item of text (the whole text when it has no list)."""
    items = []
    for line in text.splitlines():
        if re.match(r"([-*+]|\d+[.)])\s+", line):
            items.append(line)
        elif items and line.strip():
            items[-1] += "\n" + line
        elif line.strip():
            items.append(line)
    return [i.strip() for i in items]


def finding_text(finding):
    return re.sub(r"^([-*+]|\d+[.)])\s+", "", finding.strip())


def finding_place(finding):
    """Where a finding says it is, when it starts with it as worker/REVIEW.md asks (`path:line`, maybe bold), or ""."""
    m = re.match(r"[*_]*`([^`\s]+:\d+)", finding_text(finding))
    return m[1] if m else ""


def finding_key(finding):
    """A finding as review_loop compares it with the ones sent back: without its list mark, (again), markdown
    decoration, case and spacing."""
    return " ".join(re.sub(r"[*`_]", "", re.sub(AGAIN, "", finding_text(finding), count=1)).lower().split())


class AgentReport:
    """Agent report parsing and rendering."""
    def __init__(self, markdown="", *, blocked=None, report=None, review=None, auto_review=None):
        self.markdown = markdown or ""
        if blocked is None and report is None and review is None:
            self.blocked = (section(self.markdown, "Blocked").splitlines() or [""])[0]
            self.report = section(self.markdown, "Report")
            self.review = section(self.markdown, "Please review")
            self.auto_review = auto_review or ""  # only task-hub's reviewer writes this, never the agent's report
        else:
            self.blocked = blocked or ""
            self.report = report or ""
            self.review = review or ""
            self.auto_review = auto_review or ""

    def issue_comment(self, pr="", resumed=""):
        """resumed: resumed_line's, for a run that was resumed."""
        parts = [REPORT_MARK]
        parts += [f"## Blocked\n\n{self.blocked}"] * bool(self.blocked)
        parts += [f"## Report\n\n{self.report}"] * bool(self.report)
        parts += [f"## Please review\n\n{self.review}"] * bool(self.review)
        parts += [self.auto_review] * bool(self.auto_review)
        parts += [resumed] * bool(resumed)
        parts += [f"PR: {pr}"] * bool(pr)
        return "\n\n".join(parts)

    def pr_body(self, t):
        return "\n\n".join([f"## Blocked\n\n{self.blocked}"] * bool(self.blocked) +
                           [f"## Report\n\n{self.report}", f"## Please review\n\n{self.review}"] +
                           ([self.auto_review] if self.auto_review else []) +
                           [f"Closes {board()['issues']}#{t['id']}"] +
                           ([f"Closes {t['link']}"] if t.get("link") else []) +
                           [f"<sub>task-hub | agent: {t['agent']}</sub>"])


DIGEST_KEYS = ["verdict", "findings", "reason", "report", "review", "decision", "question", "answer", "goal_change", "pr"]
DIGEST_ITEM, DIGEST_TEXT, DIGEST_REVIEW_ITEMS = 120, 240, 3  # the caps keep one digest under ~1000 chars


def clip(text, limit):
    """One line of at most limit chars: what a human needs to decide, not the whole text."""
    s = " ".join((text or "").split())
    return s if len(s) <= limit else s[:limit - 3].rstrip() + "..."


def subsection(body, name):
    """The first paragraph under '### name', or '' (what follows it in a replan comment is task-hub's own advice)."""
    m = re.search(rf"(?m)^### {re.escape(name)}[ \t]*\n(.*?)(?=^##|\Z)", body, re.S)
    return m.group(1).strip().split("\n\n")[0] if m else ""


def summary(report):
    """The head of a Report: the bullets under its first '### ' heading (worker/PROMPT.md asks for '### Summary'),
    or, in a report without one, everything before its first '### ' heading. Bullet marks dropped, one line."""
    m = re.match(r"\s*### [^\n]*\n(.*?)(?=^### |\Z)", report, re.S | re.M)
    head = m.group(1) if m else re.split(r"(?m)^### ", report)[0]
    return " ".join(re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", l).strip() for l in head.splitlines() if l.strip())


def digest(report="", replan=""):
    """The short summary a human decides from, built from the report and replan comments task-hub writes on the
    Issue. The run builds it from the text it is about to post, so writing an event reads nothing from GitHub."""
    d = {}
    if report:
        m = re.search(r"\n\nPR: (\S+)\s*\Z", report)  # only the last line task-hub appends, not the agent's text
        pr, report = (m.group(1), report[:m.start()]) if m else ("", report)
        auto = section(report, "Automated review")
        read = parse_review_line(auto)  # a report written before the line: its Verdict line only
        d["verdict"] = clip(read.get("verdict") or (re.findall(r"(?m)^Verdict: (.+)$", auto) or [""])[0], 40)
        if read.get("blocking") or read.get("minor"):  # a clean pass needs no line of its own
            d["findings"] = f"{read['blocking']} blocking, {read['minor']} minor ({read['mode']}, attempt {read['attempt']})"
        d["reason"] = clip(section(report, "Blocked"), DIGEST_TEXT)
        lines = [l for l in section(report, "Please review").splitlines() if l.strip()]
        items = [l.strip() for l in lines if re.match(r"([-*+]|\d+[.)])\s", l)] or [l.strip() for l in lines]
        d["review"] = [clip(re.sub(r"^([-*+]|\d+[.)])\s+", "", l), DIGEST_ITEM) for l in items[:DIGEST_REVIEW_ITEMS]]
        if len(items) > DIGEST_REVIEW_ITEMS:
            d["review"].append(f"(+{len(items) - DIGEST_REVIEW_ITEMS} more)")
        d["pr"] = pr
        if not pr and not d["reason"]:  # In review without a PR is a research task: its report is the result
            d["report"] = clip(summary(section(report, "Report")), DIGEST_TEXT)
    if replan:
        d["decision"] = clip((re.findall(r"(?m)^Decision: (.+)$", replan) or [""])[0], 40)
        d["question"] = clip(subsection(replan, "Question for you"), DIGEST_TEXT)
        d["answer"] = clip(subsection(replan, "Answer"), DIGEST_TEXT)
        d["goal_change"] = clip(subsection(replan, "Proposed goal change"), DIGEST_TEXT)
    return {k: d[k] for k in DIGEST_KEYS if d.get(k)}


def parse_review_line(text):
    """{verdict, blocking, minor, mode, attempt} from the last review line (ReviewResult.review_line) in text, or {}
    when there is none or it does not read."""
    found = re.findall(rf"(?m)^{re.escape(REVIEW_LINE)}(\{{.*\}}) -->[ \t]*$", text)
    try:
        read = json.loads(found[-1]) if found else {}
    except ValueError:
        return {}
    ok = isinstance(read, dict) and read.get("verdict") in REVIEW_VERDICTS and read.get("mode") in REVIEW_MODES \
        and all(isinstance(read.get(k), int) for k in ("blocking", "minor", "attempt"))
    return {k: read[k] for k in ("verdict", "blocking", "minor", "mode", "attempt")} if ok else {}


def digest_lines(d, skip=()):
    """The digest as indented `key: value` lines, one per Please review item."""
    return [f"  {k}: {q(v)}" for k in DIGEST_KEYS if k not in skip
            for v in (d.get(k) if isinstance(d.get(k), list) else [d.get(k)]) if v]


# ---------- config ----------

@cache
def config():
    c = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    c.read_dict({"runner": {"agent": "claude", "reviewer": "", "replanner": "", "pass_env": "",
                            "parallel": str(PARALLEL), "review_retries": str(REVIEW_RETRIES),
                            "readiness": "off", "checker": "", "review_mode": "agent"},
                 "agents": DEFAULT_AGENTS, "check": {}, "board": {}, "share": {},
                 "merge": {"queue": "off", "prefix": "off", "checks": "all", "ci_minutes": str(CI_MINUTES)},
                 "ide": {"open": ""}, "notify": {"events": NOTIFY_EVENTS, "ntfy": "", "ntfy_token": ""},
                 "sandbox": {"mode": "off", "user": ""}, "autopilot": {"repos": ""}})
    try:
        c.read(CONFIG, encoding="utf-8-sig")  # Windows: Notepad may save it with a BOM
    except UnicodeDecodeError:
        fail(f"{home(CONFIG)} is not saved as UTF-8",
             "open it in Notepad and save it with Encoding: UTF-8 (PowerShell's > and Out-File write UTF-16)")
    except configparser.Error as e:  # a section or a name given twice, a line with no `=`
        why = str(e).splitlines()[0]
        if isinstance(e, configparser.MissingSectionHeaderError):
            why = f"line {e.lineno} comes before any [section]"
        elif isinstance(e, configparser.ParsingError) and getattr(e, "errors", None):  # its first line names no line
            why = f"line {e.errors[0][0]} is not `name = value`"
        fail(f"{home(CONFIG)} cannot be read: {why}",
             "fix that line: each [section] once, each name once in it, and every line `name = value`")
    return c


def board_config():
    b = config()["board"]
    project, issues = b.get("project", ""), b.get("issues", "")
    if not re.fullmatch(r"[\w.-]+/\d+", project) or not re.fullmatch(r"[\w.-]+/[\w.-]+", issues):
        fail(f"the board is not configured in {home(CONFIG)}",
             "add:  [board]  project = <owner>/<project number>  issues = <owner>/<issues repo>  (see docs/setup.md)")
    owner, number = project.split("/")
    return owner, number, issues


def agent_command(name, prompt, resume=False, session=""):
    """The agent's command line, with prompt for {prompt} and session for {session}, each as one argument.
    resume: the resume command when there is one (it goes on with the agent's own saved conversation), else
    [agents] <name>, a new session that has only the prompt to go on from."""
    c = config()
    if not c.has_option("agents", name):
        fail(f"unknown agent {name!r}", f"agents: {', '.join(c['agents'])} (add more in {home(CONFIG)})", 2)
    command = resume_command(name) if resume else None
    section = "resume" if command else "agents"
    try:
        parts = shlex.split(command or c["agents"][name])
    except ValueError as e:  # a quote left open, or cut by a ; or # that starts a comment
        raise RuntimeError(f"[{section}] {name} in {home(CONFIG)} cannot be read: {e}") from None
    if sandbox_mode() != "off" and str(PI_GROUPS) in parts:  # its user cannot read this clone (command_groups_env)
        i = parts.index(str(PI_GROUPS))
        if i and parts[i - 1] in ("-e", "--extension"):
            del parts[i - 1:i + 1]
    return [{"{prompt}": prompt, "{session}": session}.get(part, part) for part in parts]


def resume_command(name):
    """[resume] <name> (empty: none), else the built-in one (DEFAULT_RESUME) while [agents] <name> is the built-in one
    too: an agent command of your own goes on in a new session unless [resume] names how it goes on. None: none."""
    c = config()
    if c.has_option("resume", name):
        return c["resume"][name].strip() or None
    if name in DEFAULT_RESUME and c["agents"].get(name) == DEFAULT_AGENTS[name]:
        return DEFAULT_RESUME[name]
    return None


def has_resume_command(name):
    return resume_command(name) is not None


def new_session():
    import uuid
    return str(uuid.uuid4())


def windows_command(argv):
    """argv and the variables to add, as Windows can run them: a leading `env NAME=value ...` (as in the built-in
    claude) becomes variables, and an npm .cmd shim runs its script with node, since a batch file cuts its
    arguments at the first line break and the prompt has many. Elsewhere argv is returned as it is."""
    env = {}
    if not WINDOWS:
        return argv, env
    if argv and argv[0] == "env":
        argv = argv[1:]
        while argv and re.fullmatch(r"\w+=.*", argv[0], re.S):
            k, v = argv.pop(0).split("=", 1)
            env[k] = v
    path = shutil.which(argv[0]) if argv else None
    if not path:
        return argv, env
    if path.lower().endswith((".cmd", ".bat")):
        script = re.search(r'"%~?dp0%?\\([^"]+)"\s+%\*', Path(path).read_text(errors="replace"))
        if not script:
            raise RuntimeError(f"{path} is a batch file, which cannot take a prompt of several lines: "
                               "point [agents] at the program it runs (an .exe, or node with its script)")
        target = Path(path).parent / script[1]
        if target.suffix.lower() == ".exe":
            return [str(target), *argv[1:]], env
        if target.suffix.lower() not in (".js", ".cjs", ".mjs"):
            raise RuntimeError(f"{path} runs {target.name}, which task-hub cannot start without it: "
                               "point [agents] at the program it runs")
        node = Path(path).parent / "node.exe"
        return [str(node) if node.exists() else shutil.which("node") or "node", str(target), *argv[1:]], env
    return [path, *argv[1:]], env


def helper_agent(t, key):
    """The agent for [runner] reviewer or replanner: "" = off, "agent" = the task's own agent, else that name."""
    name = config()["runner"].get(key, "").strip()
    return t["agent"] if name == "agent" else name


def parallel():
    """[runner] parallel: how many tasks may be In progress at once; fewer on a PC short of memory."""
    value = config()["runner"].get("parallel", "").strip() or str(PARALLEL)
    if not re.fullmatch(r"\d+", value) or int(value) < 1:
        fail(f"[runner] parallel must be a whole number, 1 or more; got {value!r}",
             f"set  [runner]  parallel = <number>  in {home(CONFIG)} (default {PARALLEL}; 1 or 2 on a slow PC)")
    return int(value)


def review_retries():
    """[runner] review_retries: how many times a "needs changes" review sends the work back to the agent (0: never)."""
    value = config()["runner"].get("review_retries", "").strip() or str(REVIEW_RETRIES)
    if not re.fullmatch(r"\d+", value):
        raise RuntimeError(f"[runner] review_retries in {home(CONFIG)} must be a whole number, 0 or more; "
                           f"got {value!r}")
    return int(value)


def review_mode():
    """[runner] review_mode: agent (the default: one reviewer reads the Goal, the agent's report, and the diff) or
    goldfish (each auditor of worker/REVIEW.md reads the Goal and the code only, never the report)."""
    mode = config()["runner"].get("review_mode", "").strip().lower() or "agent"
    if mode not in REVIEW_MODES:
        raise RuntimeError(f"[runner] review_mode in {home(CONFIG)} must be agent or goldfish; got {mode!r}")
    return mode


def pass_env():
    """[runner] pass_env: names of variables (API keys and the like) a run in a herdr pane gets too."""
    return [n for n in re.split(r"[\s,]+", config()["runner"].get("pass_env", "")) if n]


def check_ready(name):
    """Run [check] <name>, if set (exit 0 = ready); raise with its last lines when the agent cannot be used now."""
    cmd = config()["check"].get(name, "").strip()
    if not cmd:
        return
    try:
        argv, env = windows_command(shlex.split(cmd))
        r = subprocess.run(as_agent(argv, keep=pass_env()), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                           env={**os.environ, **env})
        result, output = f"exited {r.returncode}", r.stdout + r.stderr
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        r, result, output = None, "failed", str(e)
    if r and r.returncode == 0:
        return
    for k in pass_env():  # a key the check prints never reaches the comment or the events
        if os.environ.get(k):
            output = output.replace(os.environ[k], "***")
    tail = " | ".join(line.strip() for line in output.strip().splitlines()[-3:])
    raise RuntimeError(f'agent "{name}" is not ready: `{cmd}` {result}: {tail[-200:]}')


def sandbox_mode():
    """[sandbox] mode: "off" (the default) or "user" (Linux: the agent runs as another user, docs/sandbox.md)."""
    mode = config()["sandbox"].get("mode", "").strip().lower() or "off"
    if mode not in ("off", "user"):
        raise RuntimeError(f"[sandbox] mode must be off or user; got {mode!r} in {home(CONFIG)}")
    return mode


def sandbox_user():
    return config()["sandbox"].get("user", "").strip() or SANDBOX_USER


def agent_acl(d):
    """True when folder d has an ACL entry, access or default, for the sandbox user or group (Linux only)."""
    if not hasattr(os, "getxattr"):
        return False
    import grp, pwd  # Unix only
    try:
        uid = pwd.getpwnam(sandbox_user()).pw_uid
    except KeyError:
        uid = None
    gids = set()
    for name in (SANDBOX_GROUP, sandbox_user()):
        try:
            gids.add(grp.getgrnam(name).gr_gid)
        except KeyError:
            pass
    for attr in ("system.posix_acl_access", "system.posix_acl_default"):
        try:
            data = os.getxattr(d, attr)
        except OSError:  # no such folder, no ACL of that kind, or a file system without ACLs
            continue
        # a 4-byte version, then 8-byte entries: tag (2 = a named user, 8 = a named group), permissions, id
        for i in range(4, len(data) - 7, 8):
            tag, id_ = int.from_bytes(data[i:i + 2], "little"), int.from_bytes(data[i + 4:i + 8], "little")
            if (tag == 2 and id_ == uid) or (tag == 8 and id_ in gids):
                return True
    return False


def mark_sandbox_used():
    if not SANDBOX_USED.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        SANDBOX_USED.touch()


def refuse_after_user():
    """Raise when mode = off would run your git on clones or worktrees the agent's user wrote: its core.fsmonitor or
    hooks would run as you. That is while it still has an ACL on them (the setup of mode = user is not undone), and,
    after mode = user ran here, until both folders are deleted: undoing the setup, or emptying them, leaves what the
    agent planted or lets it write what comes next. Only reads: check_sandbox writes and clears the marker."""
    dirs, user = (DATA / "repos", DATA / "worktrees"), sandbox_user()
    steps = "then stop its processes, save work, delete repos and worktrees (not just empty them): docs/sandbox.md"
    for d in dirs:
        if agent_acl(d):
            raise RuntimeError(f"[sandbox] mode = off, but {user} still has an ACL on {home(d)}: your git would run "
                               "what it planted. For you, not task-hub: sudo scripts/setup_agent_user.sh "
                               f"uninstall, {steps}")
    if SANDBOX_USED.exists():
        for d in dirs:
            if os.path.lexists(d):
                raise RuntimeError(f"[sandbox] mode = off, but {home(d)} is still there after mode = user ran here: "
                                   f"your git would run what {user} planted. For you, not task-hub: {steps}")


def check_sandbox():
    """Raise when [sandbox] asks for a sandbox this machine cannot give: at launch, before any credit is spent."""
    if sandbox_mode() == "off":
        if any(agent_acl(d) for d in (DATA / "repos", DATA / "worktrees")):
            mark_sandbox_used()  # mode = user ran here, maybe before the marker existed: it outlives the ACLs
        refuse_after_user()
        SANDBOX_USED.unlink(missing_ok=True)  # both folders gone, no ACL: what off mode makes there next is yours
        return
    if not sys.platform.startswith("linux"):
        raise RuntimeError(f"[sandbox] mode = user works on Linux only; set mode = off in {home(CONFIG)}")
    import pwd  # Unix only
    user = sandbox_user()
    try:
        if pwd.getpwnam(user).pw_uid == os.getuid():
            raise RuntimeError(f"[sandbox] user {user} is you; it must be a user of its own (docs/sandbox.md)")
    except KeyError:
        raise RuntimeError(f"[sandbox] user {user} does not exist on this machine; create it (docs/sandbox.md)") from None
    mark_sandbox_used()  # before anything runs as that user: going back to off then needs both folders deleted
    for d in (DATA / "repos", DATA / "worktrees"):
        r = run(*as_agent(["test", "-d", d, "-a", "-w", d]))
        if r.returncode != 0:  # no NOPASSWD rule (sudo asks for a password, -n refuses), or no shared folder
            raise RuntimeError(f"[sandbox] cannot use folder {home(d)} as user {user}: "
                               f"{(r.stderr.strip() or 'it is missing or not writable for that user')[-200:]} "
                               "(docs/sandbox.md)")


def as_agent(argv, cwd="/", keep=()):
    """argv as [sandbox] runs it: unchanged when off; else as the sandbox user, in cwd, with its own HOME (its own
    sign-ins and git config) and of this environment only the variables named in keep."""
    if sandbox_mode() == "off":
        return argv
    return ["sudo", "-n", "-u", sandbox_user(), "-H", "-D", str(cwd),
            *([f"--preserve-env={','.join(keep)}"] if keep else []), "--", *map(str, argv)]


def git_shared(d, *args, check=False):
    """git on one of task-hub's clones or worktrees. With [sandbox] on, the agent can write those, config and hooks
    included, so git runs as the agent's user: what it set up runs with no more rights than the agent had."""
    if sandbox_mode() == "off":
        refuse_after_user()
        return run("git", "-C", d, *args, check=check)
    return run(*as_agent(["git", "-C", d, *args]), check=check)


def shared_read(path):
    """A file of a clone or worktree as bytes, or None when there is none. With [sandbox] on, read as the agent's
    user: a link the agent put there leads only to what it could read itself."""
    if sandbox_mode() == "off":
        refuse_after_user()
        return path.read_bytes() if path.is_file() else None
    r = subprocess.run(as_agent(["sh", "-c", 'test -f "$1" && exec cat -- "$1"', "sh", path]), capture_output=True)
    return r.stdout if r.returncode == 0 else None


def shared_write(path, text):
    """Write a file of a clone or worktree (made anew, with its folders). With [sandbox] on, as the agent's user: a
    link the agent put there never makes task-hub write over one of your files."""
    if sandbox_mode() == "off":
        refuse_after_user()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)  # an earlier run's copy of a read-only file cannot be written over
        path.write_bytes(text.encode() if isinstance(text, str) else text)
        return
    run_input(as_agent(["sh", "-c", 'mkdir -p -- "$(dirname -- "$1")" && rm -f -- "$1" && cat > "$1"', "sh", path]),
              text.encode() if isinstance(text, str) else text)


def shared_unlink(path):
    if sandbox_mode() == "off":
        refuse_after_user()
        path.unlink(missing_ok=True)
    else:
        run(*as_agent(["rm", "-f", "--", path]), check=True)


def run_input(argv, data):
    r = subprocess.run(argv, input=data, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[-3:])} failed: {r.stderr.decode(errors='replace').strip()[-300:]}")


def check_agent(name):
    if name and not config().has_option("agents", name):
        fail(f"unknown agent {name!r}", f"agents: {', '.join(config()['agents'])} (add more in {home(CONFIG)})", 2)


# ---------- the board: a GitHub Project of Issues ----------

BOARD_CHANGES = {("project", "item-edit"), ("project", "item-add"), ("project", "item-delete"),
                 ("project", "item-archive"), ("issue", "create"), ("issue", "edit"), ("issue", "close"),
                 ("issue", "reopen"), ("issue", "delete")}


def gh(*args):
    try:
        r = run(GH, *args)
    except FileNotFoundError:
        raise RuntimeError(f"gh not found ({GH})") from None
    finally:  # every board change goes through here; stamped even on a failure, which may have changed it anyway
        if tuple(args[:2]) in BOARD_CHANGES or (tuple(args[:2]) == ("api", "graphql") and len(args) > 3
                                                 and str(args[3]).startswith("query=mutation")):
            write_cache(BOARD_STALE, str(max(time.time(), read_json_number(BOARD_STALE))))  # never backwards
    if r.returncode != 0:
        raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or ["gh failed"])[-1])
    return r.stdout


def gh_json(*args):
    return json.loads(gh(*args) or "null")


ADD_BLOCKED_BY = """mutation($issue: ID!, $blocker: ID!) {
  addBlockedBy(input: {issueId: $issue, blockingIssueId: $blocker}) { issue { number } } }"""
ARCHIVE_ITEM = """mutation($project: ID!, $item: ID!) {
  archiveProjectV2Item(input: {projectId: $project, itemId: $item}) { item { id } } }"""
# no afterId: the first place, so the top of the card's column in a board view that is not sorted by a field
MOVE_TO_TOP = """mutation($project: ID!, $item: ID!) {
  updateProjectV2ItemPosition(input: {projectId: $project, itemId: $item}) { clientMutationId } }"""
# the Project's id, url, and fields in one call (1 point), whether a user or an organization owns it;
# `gh project view` cost 2 points (the owner's type, then the Project) and a fields query 1 more
PROJECT_QUERY = """query($owner: String!, $number: Int!) { repositoryOwner(login: $owner) { ... on ProjectV2Owner {
  projectV2(number: $number) { id url fields(first: 50) { nodes {
    ... on ProjectV2FieldCommon { id name dataType } ... on ProjectV2SingleSelectField { options { id name } } } } } } } }"""
# the card of a team's Issue (`task share`) on each Project, with the Project's single-select fields and the card's
# values: which column it is in now, so an unchanged column costs no mutation (1 point)
TEAM_CARD_QUERY = """query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) {
  issue(number: $number) { projectItems(first: 20) { nodes { id
    project { id url fields(first: 50) { nodes { ... on ProjectV2SingleSelectField { id name options { id name } } } } }
    fieldValues(first: 50) { nodes { ... on ProjectV2ItemFieldSingleSelectValue {
      name field { ... on ProjectV2FieldCommon { id } } } } } } } } } }"""
# "@<field>" is replaced by the field's name as spelled on the board (we match names without regard to case)
ITEMS_QUERY = """query($id: ID!, $q: String!, $after: String) { node(id: $id) { ... on ProjectV2 {
  items(first: 100, after: $after, query: $q) { pageInfo { hasNextPage endCursor } nodes { id updatedAt
    content { ... on Issue { number title url body state repository { nameWithOwner }
      blockedBy(first: 50) { nodes { number title state stateReason repository { nameWithOwner } } } } }
    status: fieldValueByName(name: "@Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    repo: fieldValueByName(name: "@Target repo") { ... on ProjectV2ItemFieldTextValue { text } }
    agent: fieldValueByName(name: "@Agent") { ... on ProjectV2ItemFieldTextValue { text } }
    base: fieldValueByName(name: "@Base branch") { ... on ProjectV2ItemFieldTextValue { text } }@review } } } } }"""
# the optional Review field, in ITEMS_QUERY only when the Project has it
ITEMS_REVIEW = """
    review: fieldValueByName(name: "@Review") { ... on ProjectV2ItemFieldSingleSelectValue { name } }"""


def graphql(query, **variables):
    # -F sends an int as a number (an Int! variable); -f sends a string as it is
    return gh_json("api", "graphql", "-f", f"query={query}",
                   *(a for k, v in variables.items() for a in ("-F" if isinstance(v, int) else "-f", f"{k}={v}")))["data"]


_board = {}


def board(saved_ok=False):
    """Project id and the ids of the Status options and the text fields (checked once per command).

    saved_ok: BOARD_META will do (read-only `task list`). A command that moves cards reads the Project again, so an
    option remade on the board since then can never send a card to the wrong column; its read refreshes BOARD_META."""
    owner, number, issues = board_config()
    if _board and (_board.get("owner"), _board.get("number"), _board.get("issues")) == (owner, number, issues):
        return _board
    _board.clear()  # `task watch` reads the config again at every check: [board] may name another Project now
    saved = read_json(BOARD_META) if saved_ok else {}
    at = saved.get("at")
    if saved.get("key") == [owner, number, issues] and isinstance(at, (int, float)) \
            and 0 <= time.time() - at < META_MAX_AGE and isinstance(saved.get("board"), dict):
        _board.update(saved["board"])
        return _board
    try:
        project = (graphql(PROJECT_QUERY, owner=owner, number=int(number))["repositoryOwner"] or {}).get("projectV2")
        if not project:  # no user or organization of that login (gh errors on a missing number itself)
            raise RuntimeError("unknown owner type")  # what `gh project view` said
        fields = project["fields"]["nodes"]
    except RuntimeError as e:  # raised, not fail(): a finishing run must still keep its report and block the card
        raise RuntimeError(f"cannot read GitHub Project {owner}/{number}: {e}")
    by_name = {f["name"].lower(): f for f in fields if f}
    status = by_name.get("status", {})
    options = {o["name"].lower(): o["id"] for o in status.get("options", [])}
    missing = StatusLifecycle.missing_required_options(options)
    missing += [f'text field "{n}"' + (f" (it is {by_name[n.lower()]['dataType']}, make it TEXT)"
                                        if n.lower() in by_name else "")
                for n in TEXT_FIELDS if by_name.get(n.lower(), {}).get("dataType") != "TEXT"]
    if missing:
        fail(f"the Project is missing: {', '.join(missing)}",
             f"add them in the Project's settings ({project.get('url', '')}); see docs/setup.md")
    # optional: `task check` makes Readiness when it is missing, a run's review Review
    selects = {key: by_name.get(name.lower()) for key, name in (("readiness", READINESS_FIELD), ("review", REVIEW_FIELD))}
    _board.update(owner=owner, number=number, issues=issues, id=project["id"], url=project.get("url", ""),
                  status_field=status["id"], status_options=options,
                  text_fields={n: by_name[n.lower()]["id"] for n in TEXT_FIELDS},
                  names={n: by_name[n.lower()]["name"] for n in ["Status", *TEXT_FIELDS]},
                  **{key: {"id": f["id"], "type": f.get("dataType", ""), "name": f["name"],
                           "options": {o["name"].lower(): o["id"] for o in f.get("options") or []}}
                     if f else None for key, f in selects.items()})
    write_cache(BOARD_META, json.dumps({"key": [owner, number, issues], "at": time.time(), "board": _board}))
    return _board


def write_cache(path, text):
    """A cache that cannot be written is only a cache: never the reason a command or a run fails."""
    with contextlib.suppress(OSError):
        write_atomic(path, text)


def forget_board():
    """After a GitHub call that used board()'s ids failed: they may be stale (a field renamed, an option remade)."""
    _board.clear()
    with contextlib.suppress(OSError):  # Windows: a pane may have it open for a moment
        BOARD_META.unlink(missing_ok=True)


def read_json(path):
    """A cache file as a dict; missing, half-written by an older version, or unreadable reads as {}."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def cached_items(max_age):
    """The raw open items of BOARD_CACHE and when they were read from GitHub, when that was less than max_age seconds
    ago and after the last board change, else None."""
    data, stale = read_json(BOARD_CACHE), read_json_number(BOARD_STALE)
    at = data.get("fetched_at")
    if data.get("key") != list(board_config()) or not isinstance(at, (int, float)) or not isinstance(
            data.get("items"), list) or at <= stale or not 0 <= time.time() - at < max_age:
        return None
    return data["items"], at


def read_json_number(path):
    try:
        return float(path.read_text())
    except (OSError, ValueError):
        return 0.0


def fetch_items(include_done, saved_ok=False):
    """The raw items from GitHub and when the read began; the open ones are kept in BOARD_CACHE for `task list` in
    other panes."""
    b = board(saved_ok)
    query = ITEMS_QUERY
    for n, spelled in b["names"].items():
        query = query.replace(f'"@{n}"', json.dumps(spelled))
    query = query.replace("@review", ITEMS_REVIEW.replace('"@Review"', json.dumps(b["review"]["name"]))
                          if b.get("review") else "")  # a Project without the field is asked nothing of it
    fetched_at = time.time()  # before the read: a board change during it makes this read stale
    items, after = [], None
    try:
        while True:
            page = graphql(query, id=b["id"], q="" if include_done else "-status:Done",
                           **({"after": after} if after else {}))["node"]["items"]
            items += page["nodes"]
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
    except (RuntimeError, TypeError):  # TypeError: the node is null, e.g. the Project was deleted
        forget_board()
        raise
    if not include_done and fetched_at > read_json_number(BOARD_STALE):  # else readers would never use it
        write_cache(BOARD_CACHE, json.dumps({"key": list(board_config()), "fetched_at": fetched_at, "items": items}))
    return items, fetched_at


def shared_items(max_age):
    """The open items for `task list`, and when they were read: from BOARD_CACHE when fresh. Otherwise one pane reads GitHub while the
    others wait for it, at most 15 seconds; a lock left by a killed process is ignored after 30."""
    items = cached_items(max_age)
    if items is not None:
        return items
    for attempt in range(2):
        try:
            os.close(os.open(BOARD_FETCHING, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - BOARD_FETCHING.stat().st_mtime >= 30:  # its pane was killed (no finally runs then)
                    BOARD_FETCHING.unlink()
                    continue
                for _ in range(75):
                    time.sleep(0.2)
                    if not BOARD_FETCHING.exists():
                        break
            except OSError:  # gone meanwhile, or Windows would not remove it
                pass
            items = cached_items(max_age)
            return items if items is not None else fetch_items(include_done=False, saved_ok=True)
        except OSError:  # no STATE yet: nobody else is reading either
            return fetch_items(include_done=False, saved_ok=True)
    else:
        return fetch_items(include_done=False, saved_ok=True)
    try:
        return fetch_items(include_done=False, saved_ok=True)
    finally:
        with contextlib.suppress(OSError):
            BOARD_FETCHING.unlink(missing_ok=True)


def tasks(include_done=False, max_age=0):
    """The Issues from the issues repo that are on the Project, as task dicts, the card changed last first.

    Projects are GraphQL-only and GitHub limits GraphQL to 5000 points per hour. `gh project item-list`
    costs 101 points a call (it asks for 100 field values of every card), which a watch asking every
    minute exceeds; ITEMS_QUERY asks for just our fields and costs 1 point per 100 cards.
    max_age: open cards from BOARD_CACHE when it is fresher, for read-only `task list` only; never before a change.
    What this machine knows (runs, stages, waits_for) is worked out again each time.
    Each card's "fetched" is when its board snapshot was read from GitHub (UNIX time).
    """
    items, fetched = shared_items(max_age) if max_age and not include_done else fetch_items(include_done)
    issues = board_config()[2]
    result = []
    for item in items:
        content = item.get("content") or {}
        if "number" not in content or content["repository"]["nameWithOwner"].lower() != issues.lower():
            continue  # a draft card or a PR, or an Issue from another repo
        value = lambda k: ((item.get(k) or {}).get("name") or (item.get(k) or {}).get("text") or "").strip()
        t = {"id": str(content["number"]), "title": content.get("title", ""), "item": item["id"],
             "updated": item.get("updatedAt") or "",  # the card's last change on the Project, e.g. its last move
             "fetched": fetched,
             "closed": content.get("state") == "CLOSED",
             "status": canonical(value("status")), "repo": value("repo"), "agent": value("agent"),
             "base": value("base"), "review": value("review"), "url": content.get("url", ""),
             "blockers": [{"ref": f"#{n['number']}" if n["repository"]["nameWithOwner"].lower() == issues.lower()
                           else f"{n['repository']['nameWithOwner']}#{n['number']}",
                           "number": str(n["number"]), "title": n.get("title", ""), "state": n.get("state", ""),
                           "reason": n.get("stateReason") or ""}
                          for n in (content.get("blockedBy") or {}).get("nodes") or [] if n]}
        t["mentioned"] = mentioned_blockers(content.get("body") or "")
        t["autopilot_off"] = bool(re.search(AUTOPILOT_OFF, content.get("body") or ""))
        t["goal_hash"] = goal_hash(content.get("body") or "")  # a readiness verdict counts for this Goal only
        result.append({**load_run(t["id"]), **t})
    statuses = {t["id"]: t["status"] for t in result}
    for t in result:
        t["running"] = alive(t)
        # its own run is still going whatever the Status says (a replanner after Blocked, a late herdr start):
        # never start a second run in the same worktree
        own = [f"its last run, still running ({t.get('stage') or 'starting'})"] \
            if t["running"] and t["status"] != IN_PROGRESS else []
        linked = {x["number"] for x in t["blockers"] if x["ref"].startswith("#")}
        # written in the body but never linked (the Issue was made with `gh issue create` or another skill):
        # never enough to start, so an open one holds the task back like a link until someone links it
        unlinked = [n for n in t.pop("mentioned") if n not in linked and n != t["id"] and n in statuses]
        t["waits_for"] = ", ".join([f"{x['ref']} ({why})" for x, why in
                                    ((x, waiting_reason(x, statuses)) for x in t["blockers"]) if why]
                                   + [f"#{n} ({statuses[n]}, only in the body: link it)" for n in unlinked] + own)
    # the card changed last first, as on the board: what just moved is at the top of its column
    return sorted(result, key=lambda t: (t["updated"], int(t["id"])), reverse=True)


def move_to_top(t):
    """Put the card first on the Project, so the top of its column is the card that moved last."""
    with contextlib.suppress(RuntimeError):  # only its place on the board: never worth failing the move itself
        graphql(MOVE_TO_TOP, project=board()["id"], item=t["item"])


def archive_overflow():
    """Over MAX_CARDS cards on the board: archive the Done ones moved longest ago until MAX_CARDS are left.
    Only Done cards of closed Issues: an open card, or a card dragged to Done with its Issue still open, is work still
    owed, and an archived card no longer shows in task-hub. The Project's "Archived items" restores a card.
    Returns the ids archived; a GitHub failure names the ones archived before it."""
    cards = tasks(include_done=True)
    done = sorted((t for t in cards if t["status"] == DONE and t["closed"]), key=lambda t: (t["updated"], int(t["id"])))
    archived = []
    for t in done[:max(len(cards) - MAX_CARDS, 0)]:
        try:
            graphql(ARCHIVE_ITEM, project=board()["id"], item=t["item"])  # 1 point: `gh project item-archive` costs more
        except RuntimeError as e:
            raise RuntimeError(f"{e} (archived before it: {', '.join('#' + i for i in archived) or 'none'})")
        archived.append(t["id"])
    return archived


def archive_lines(archived):
    return [f"archived: {len(archived)} Done card(s), the board keeps the newest {MAX_CARDS} cards: "
            + ", ".join(f"#{i}" for i in archived)] if archived else []


def mentioned_blockers(body):
    """Task numbers under a "Blocked by" or "Ready conditions" heading of the Issue body, in order."""
    found, inside = [], False
    for line in body.splitlines():
        if line.lstrip().startswith("#") and not re.match(r"\s*#\d", line):  # a heading, not "#12 ..."
            inside = bool(re.match(r"\s*#+\s*(blocked by|ready conditions)\b", line, re.I))
        elif inside:
            found += [n for n in re.findall(r"(?<![\w/])#(\d+)\b", line) if n not in found]
    return found


def waiting_reason(blocker, statuses):
    """Why this blocker still holds its task back, or "" when it is done.

    Done means closed as completed (a merged PR, `task done`). Closed as not planned or as a duplicate means
    the prerequisite was dropped, not delivered: the task keeps waiting until a human removes the link.
    """
    if blocker["state"] == "CLOSED":
        reason = blocker["reason"]
        return f"closed as {reason.lower().replace('_', ' ')}" if reason in ("NOT_PLANNED", "DUPLICATE") else ""
    if blocker["ref"].startswith("#"):
        return statuses.get(blocker["number"]) or "open, not on the board"
    return "open"


def shown_status(t):
    """The Status, with the stage of the run that is still going: "In progress › review"."""
    return f"{t['status']} › {t['stage']}" if t.get("running") and t.get("stage") else t["status"]


def canonical(status):
    """The board's column name in our spelling ("In Progress" on GitHub is IN_PROGRESS here)."""
    return StatusLifecycle.canonical(status)


def get(tid):
    if str(tid).isdigit():
        for t in tasks(include_done=True):
            if int(t["id"]) == int(tid):
                return t
    fail(f"task {tid} not found on the board", "run `task` to see the board")


def set_status(t, status, reason="", digest_=None, sha=""):
    """digest_: the event's digest; a Blocked without one gets its reason as the digest.
    sha: the PR's head commit the run just pushed, for the phone's buttons on the In review notification."""
    if not t.get("item"):  # the card was removed from the Project; nothing to move
        return
    # a t without "status" came from somewhere that does not know it: unchecked, rather than another GitHub call
    if "status" in t and not StatusLifecycle.expected(t["status"], status):
        # stderr, never EVENTS: an event wakes /chief, and that costs tokens
        print(f"warning: task {t['id']} moved {t['status'] or '(new)'} -> {status}, "
              "not in StatusLifecycle.transitions", file=sys.stderr, flush=True)
    b = board()
    try:
        gh("project", "item-edit", "--id", t["item"], "--project-id", b["id"], "--field-id", b["status_field"],
           "--single-select-option-id", b["status_options"][status.lower()])
    except RuntimeError:
        forget_board()
        raise
    t["status"] = status
    if digest_ is None and status == BLOCKED and reason:
        digest_ = {"reason": clip(reason, DIGEST_TEXT)}
    emit(t, status, reason=reason, pr=t.get("pr", ""), digest=digest_, sha=sha)
    move_to_top(t)  # after the event: whoever sees the new Status finds its event already written
    # the team's copy (`task share`) last: a slow or failing team's GitHub never holds back the event
    to_team(t, f"the Status {status}", lambda team, n: team.move(n, status, share_config(team.repo)))


def emit(t, event, **extra):
    """Note what just happened in EVENTS, one JSON line, so a watcher learns of it without polling GitHub,
    and show it as a notification: the human learns of it without an agent (and its tokens) watching."""
    e = {"time": now(), "id": t["id"], "title": t.get("title", ""), "repo": t.get("repo", ""),
         "event": event, **{k: v for k, v in extra.items() if v}}
    append_jsonl(EVENTS, e)
    notify(e)


def notification(e):
    """An event's notification (title, body), built from the event and its digest: no LLM, no GitHub."""
    if e["event"] == "update":  # task-hub's own new release, not a task's event
        return f"task-hub {e['version']}", e["reason"]
    d = {**{k: e[k] for k in ("reason", "decision", "pr") if e.get(k)}, **(e.get("digest") or {})}
    body = [f"{k}: {v}" for k in DIGEST_KEYS if k != "pr" for v in (d.get(k) if isinstance(d.get(k), list) else [d.get(k)])
            if v]
    if e["event"] == "slow":  # the notification may be all the human sees of it
        body.append("stop it with Ctrl-C in its tab, if you want; task-hub never does")
    return f"#{e['id']} {e['event']}: {e.get('title', '')}", "\n".join(body + ([d["pr"]] if d.get("pr") else []))


WINDOWS_TOAST = """$m = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$x = $m::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
[void]$t.Item(0).AppendChild($x.CreateTextNode($env:TASK_HUB_TITLE))
[void]$t.Item(1).AppendChild($x.CreateTextNode($env:TASK_HUB_BODY))
$m::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show(
    [Windows.UI.Notifications.ToastNotification]::new($x))"""


def notify(e):
    """Show the event if [notify] events lists it: on this machine (herdr, else macOS, Windows or notify-send),
    and on the phone too when [notify] ntfy is set.
    Fire and forget: a missing or hanging notifier must never cost the run or the command that wrote the event."""
    try:
        wanted = {x.strip().lower() for x in config()["notify"].get("events", "").split(",") if x.strip()}
    except configparser.Error:
        return
    if e["event"].lower() not in wanted:
        return
    title, body = notification(e)
    if herdr_available():
        sound = "request" if e["event"] in (BLOCKED, "replan", "slow", "conflict") else "done"
        cmd = ["herdr", "notification", "show", title, "--body", body, "--sound", sound]
    elif shutil.which("osascript"):  # arguments, not a script built from the text: no quoting to get wrong
        cmd = ["osascript", "-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
               "-e", "end run", title, body]
    elif WINDOWS:  # a toast from Windows PowerShell (5.1, which loads WinRT types); the text goes in as variables
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_TOAST]
    elif shutil.which("notify-send"):  # Linux without herdr
        cmd = ["notify-send", "--app-name=task-hub", "--urgency", "critical" if e["event"] in (BLOCKED, "replan")
               else "normal", title, body]
    else:
        cmd = None
    launch = [(cmd, {"TASK_HUB_TITLE": title, "TASK_HUB_BODY": body})] if cmd else []
    if post := ntfy_post(e, title, body):  # in addition to this machine's: the phone is for when nobody is here
        launch.append(([sys.executable, "-I", "-c", NTFY_POST], {"TASK_HUB_NTFY": json.dumps(post)}))
    for argv, env in launch:
        detach(argv, env)


def detach(argv, env):
    """Start argv in its own session and never wait for it; a program that is not there is no error."""
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env={**os.environ, **env}, **DETACHED)
    except OSError:
        pass


# a detached `python -I -c`, so a down or hanging server costs only this process, never the command that wrote the event
NTFY_POST = """import json, os, urllib.request
p = json.loads(os.environ["TASK_HUB_NTFY"])
urllib.request.urlopen(urllib.request.Request(p["url"], data=json.dumps(p["json"]).encode(), headers=p["headers"],
                                              method="POST"), timeout=p["timeout"]).close()"""
NTFY_TIMEOUT = 10  # seconds, for the whole request in its own process


def ntfy_post(e, title, body):
    """[notify] ntfy: the phone's copy of the notification, as ntfy's JSON publish (url, json, headers), or None
    when it is off. JSON, not the Title/Click headers: a title in Japanese is not a valid HTTP header."""
    try:
        issues = config()["board"].get("issues", "")
    except configparser.Error:
        return None
    pr = e.get("pr") or (e.get("digest") or {}).get("pr")
    click = pr or (f"https://github.com/{issues}/issues/{e['id']}"
                   if e.get("id") and re.fullmatch(r"[\w.-]+/[\w.-]+", issues) else "")
    post = ntfy_message(title, body, 4 if e["event"] in (BLOCKED, "replan") else 3, click)
    if post and e["event"] == IN_REVIEW and pr and e.get("sha") and e.get("id"):
        try:
            actions = review_actions(e["id"], pr, e["sha"])
        except OSError:  # no key file to sign with: the notification still goes, without buttons
            actions = []
        if actions:
            post["json"]["actions"] = actions
    return post


def ntfy_target():
    """[notify] ntfy and ntfy_token as (server URL, topic, token), or None when it is off."""
    try:
        n = config()["notify"]
        url, token = n.get("ntfy", "").strip(), n.get("ntfy_token", "").strip()
    except configparser.Error:
        return None
    m = re.fullmatch(r"(https?://[^/?#\s]+(?:/[^?#\s]*)?)/([\w-]{1,64})", url.rstrip("/"))
    return (m[1], m[2], token) if m else None  # empty: off. Not `<server>/<topic>`: nothing to send to


def ntfy_message(title, body, priority=3, click=""):
    """A publish to [notify] ntfy's topic for NTFY_POST, or None when it is off."""
    if not (target := ntfy_target()):
        return None
    server, topic, token = target
    msg = {"topic": topic, "title": title, "message": body or title, "priority": priority, "tags": ["task-hub"],
           **({"click": click} if click else {})}
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    return {"url": server, "json": msg, "headers": headers, "timeout": NTFY_TIMEOUT}


def set_text(t, field, value):
    b = board()
    try:
        gh("project", "item-edit", "--id", t["item"], "--project-id", b["id"], "--field-id", b["text_fields"][field],
           "--text", value)
    except RuntimeError:
        forget_board()
        raise
    t[field.lower()] = value


def comment(t, body):
    f = DATA / f"comment-{t['id']}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    gh("issue", "comment", t["id"], "--repo", board()["issues"], "--body-file", f)
    f.unlink(missing_ok=True)
    if body.startswith((REPORT_MARK, REPLAN_MARK)):  # task-hub's report and triage go to the team; nothing else
        to_team(t, "task-hub's comment", lambda team, n: team.comment(n, body))


def report_comment(t, blocked="", report="", review="", pr="", auto_review=""):
    """The one comment format task-hub writes on an Issue; the last one is the task's current report."""
    comment(t, AgentReport(blocked=blocked, report=report, review=review,
                           auto_review=auto_review).issue_comment(pr, resumed_line(t)))


RESUMED_LINE = r"\n\nResumed once at [^\n]*"


def interrupted_text(why):
    """`interrupted` as people and agents read it: "silent" (the Watchdog) says nothing on its own."""
    return "the watchdog stopped the agent (no output and no CPU used)" if why == "silent" else why


def resumed_line(t):
    """The report's line on where the run was resumed (decision 11: the Issue's report and the `resumed` event,
    no notification of its own); "" for a run never resumed."""
    stages = (t.get("resumed") or "").split()
    why = interrupted_text(t.get("interrupted") or "the run process is gone")
    return f"Resumed once at {', '.join(stages)}: {why}." if stages else ""


def issue(t):
    """Body, labels, and task-hub comments of the task's Issue."""
    data = gh_json("issue", "view", t["id"], "--repo", board()["issues"], "--json", "body,state,comments,labels")
    reports = [c["body"] for c in data.get("comments", []) if c["body"].startswith(REPORT_MARK)]
    replans = [c["body"] for c in data.get("comments", []) if c["body"].startswith(REPLAN_MARK)]
    # A public comment is not permission to edit or close another Issue with this account's credentials.
    links = [(m[1], c["body"]) for c in data.get("comments", [])
             if c["body"].startswith(LINK_MARK) and c.get("viewerDidAuthor") is True
             for m in [re.search(r"([\w.-]+/[\w.-]+#\d+)", c["body"])] if m]
    project = re.search(r"(?m)^Project: ([\w.-]+/\d+)\s*$", links[-1][1]) if links else None
    reported = [c.get("createdAt") or "" for c in data.get("comments", []) if c["body"].startswith(REPORT_MARK)]
    return {"body": data.get("body") or "", "state": data.get("state", ""), "report": reports[-1] if reports else "",
            "reported": reported[-1] if reported else "", "replans": replans, "link": links[-1][0] if links else "",
            "link_project": project[1] if project else "",
            "own_comments": [c["body"] for c in data.get("comments", []) if c["body"].startswith((REPORT_MARK, REPLAN_MARK))],
            "readiness": latest_readiness(data.get("comments") or []),
            "readiness_comment": latest_readiness_comment(data.get("comments") or []),
            "research": any(label.get("name", "").lower() == RESEARCH_LABEL for label in data.get("labels") or [])}


def human_comments(t, since):
    """What people wrote on the task's Issue and on its PR from `since` (the earlier run's start) on, oldest first:
    Issue comments, and the PR's conversation comments, review bodies, and line comments (with their place).
    task-hub's own comments (they start with "<!-- task-hub") and bots' are left out. REST, like pr_merged:
    the first 100 of each kind changed since then is plenty for one re-run."""
    def human(c, at):
        user, body = c.get("user") or {}, (c.get("body") or "").strip()
        return bool(at) and at >= since and body and not body.startswith("<!-- task-hub") \
            and user.get("type") != "Bot" and not (user.get("login") or "").endswith("[bot]")

    def place(c):
        line, first, old = c.get("line"), c.get("start_line"), ""
        if line is None and c.get("original_line") is not None:  # the line changed since: where it was
            line, first, old = c["original_line"], c.get("original_start_line"), " (outdated: an earlier version)"
        span = f"lines {first}-{line}" if first and first != line else f"line {line}" if line else "the whole file"
        return f" on `{c.get('path')}` {span}{old}"

    found = [("Issue comment", c, c.get("created_at"))
             for c in gh_json("api", f"repos/{board()['issues']}/issues/{t['id']}/comments?since={since}&per_page=100")]
    m = re.fullmatch(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", t.get("pr") or "")
    if m:
        pulls = f"repos/{m[1]}/pulls/{m[2]}"
        found += [("PR comment", c, c.get("created_at"))
                  for c in gh_json("api", f"repos/{m[1]}/issues/{m[2]}/comments?since={since}&per_page=100")]
        found += [(f"PR review ({r.get('state', '').lower().replace('_', ' ')})", r, r.get("submitted_at"))
                  for r in gh_json("api", f"{pulls}/reviews?per_page=100") if r.get("state") != "PENDING"]
        found += [("PR line comment" + place(c), c, c.get("created_at"))
                  for c in gh_json("api", f"{pulls}/comments?since={since}&per_page=100")]
    return sorted(([kind, (c.get("user") or {}).get("login") or "someone", at, c["body"].strip()]
                   for kind, c, at in found if human(c, at)), key=lambda x: x[2])


def comments_text(comments):
    """The comments as the agent and the reviewer read them, numbered so a report can answer each."""
    return "\n\n".join(f"## Comment {n}: {kind}, by @{who} at {at}\n\n" + "\n".join(f"> {line}".rstrip()
                                                                                 for line in body.splitlines())
                       for n, (kind, who, at, body) in enumerate(comments, 1))


# ---------- run state on this machine ----------

def load_run(tid):
    """This machine's record of the task's run; {} when there is none. A record a crash or a full disk left cut
    short, or one another task-hub removed meanwhile, counts as none: one bad file must not stop every command."""
    try:
        data = json.loads((RUNS / f"{tid}.json").read_text())
    except (OSError, ValueError):
        return {}
    return {**data, "id": str(tid)} if isinstance(data, dict) else {}  # the id lives in the file name


def save_run(t):
    write_atomic(RUNS / f"{t['id']}.json", json.dumps({k: t.get(k, "") for k in RUN_KEYS}, indent=1))


def read_agent_file(path):
    """A file an agent wrote (its report, review or replan): UTF-8, with a BOM or not, or UTF-16 with its BOM, as
    PowerShell 5.1's `>` and Out-File write it on Windows. A byte that is neither becomes U+FFFD, never an error."""
    return agent_text(path.read_bytes())


def agent_file(path):
    """A file an agent wrote in its worktree, as read_agent_file reads it (through shared_read), or None."""
    data = shared_read(path)
    return None if data is None else agent_text(data)


def agent_text(data):
    text = data.decode("utf-16", errors="replace") if data.startswith((b"\xff\xfe", b"\xfe\xff")) \
        else data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n")


def write_atomic(path, text):
    """Readers in other processes see the complete old or new file, never a half-written one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{os.getpid()}.tmp"  # the runner, watcher and panes write from different processes
    try:
        temp.write_text(text)
        for attempt in range(50):
            try:
                temp.replace(path)
                break
            except PermissionError:  # Windows: a reader has the file open for a moment
                if not WINDOWS or attempt == 49:
                    raise
                time.sleep(0.02)
    finally:
        temp.unlink(missing_ok=True)


def launch_lock(tid):
    """Held by the one process starting this task's run: `task start` and the watch can both see the card Ready.
    Yields False while another process holds it. The system lets go of it when its holder exits or is killed."""
    return file_lock(RUNS / f"{tid}.lock")


@contextlib.contextmanager
def file_lock(path, wait=False):
    """An OS file lock on path (POSIX flock, Windows msvcrt.locking); yields False when another process holds it.
    wait: wait for it (on Windows at most about 10 seconds) instead of giving up at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        try:
            if WINDOWS:
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except OSError:
            yield False
            return
        yield True


def set_stage(t, stage):
    t["stage"] = stage
    save_run(t)


def record_run(record, say=None):
    """Append one run's outcome to METRICS."""
    append_jsonl(METRICS, record, say)


def append_jsonl(path, record, say=None):
    """A failure to note something must never cost the run or the command itself."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        if say:
            say(f"== could not write {home(path)}: {e}")


def seconds_since(stamp):
    started = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()


def alive(t):
    if not t.get("pid"):
        if not t.get("started"):
            return False  # no run of this task on this machine
        # launched (or resumed, relaunch) but `_run` has not recorded itself yet; give it two minutes
        return seconds_since(t.get("resumed_at") or t["started"]) < 120
    # this task's own run (or its conflict fix, `_fix <id> <base>`): pids are handed out again (soon on Windows; and
    # the run files outlive a restart), to another task's run too, and an agent's prompt can say _run
    own = rf"\s_(run\s+{t['id']}|fix\s+{t['id']}\s+\S+)\s*$"
    if WINDOWS:
        return bool(re.search(own, windows_command_line(int(t["pid"]))))
    r = run("ps", "-p", t["pid"], "-o", "command=")
    return r.returncode == 0 and bool(re.search(own, r.stdout))


def windows_command_line(pid):
    """The command line of a running process on Windows, which has no ps; "" when there is none.
    Asked of the system directly: a PowerShell per card would cost a second on every sync."""
    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT), ("buffer", ctypes.c_void_p)]

    kernel32, ntdll = ctypes.WinDLL("kernel32"), ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                                ctypes.POINTER(wintypes.ULONG)]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        code, size = wintypes.DWORD(), wintypes.ULONG()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return ""
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))  # ProcessCommandLineInformation
        buf = ctypes.create_string_buffer(size.value)
        if not size.value or ntdll.NtQueryInformationProcess(handle, 60, buf, size, ctypes.byref(size)) != 0:
            return ""
        s = UnicodeString.from_buffer(buf)
        return ctypes.wstring_at(s.buffer, s.length // 2)
    finally:
        kernel32.CloseHandle(handle)


def slow_threshold(agent):
    """How long a run of this agent may take before it counts as slow, and its usual time (None: too few runs)."""
    seconds = []
    # errors="replace": sync runs every minute and may read a line that is still being written
    for line in (METRICS.read_text(errors="replace").splitlines() if METRICS.exists() else []):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("agent") == agent and r.get("blocked_by") not in AGENT_NEVER_RAN:
            seconds.append(r.get("seconds") or 0)
    usual = median(seconds) if len(seconds) >= SLOW_MIN_RUNS else None
    limit = SLOW_DEFAULT if usual is None else max(SLOW_TIMES * usual, SLOW_FLOOR)
    if os.environ.get("TASK_SLOW_SECONDS"):  # tests: a live run can be slow within seconds
        limit = int(os.environ["TASK_SLOW_SECONDS"])
    return limit, usual


def event_lines_of(text):
    """The lines of EVENTS, split at \\n only: json.dumps leaves U+2028, U+2029 and U+0085 in a title as they are,
    and str.splitlines() would break a line there. A last line still being written is left out."""
    return text[:text.rfind("\n") + 1].split("\n")[:-1]


def events_named(name):
    """The events called `name` in EVENTS, oldest first."""
    events = []
    for line in (event_lines_of(EVENTS.read_text(errors="replace")) if EVENTS.exists() else []):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") == name:
            events.append(e)
    return events


def check_slow(t):
    """Emit `slow` once per run for a live run that takes longer than usual; the human decides whether to stop it.

    "Once" is read from EVENTS, never written to RUNS: the run's own `_run` process writes that file.
    Returns the reason when it emitted one.
    """
    if not t.get("started"):
        return ""
    agent = load_run(t["id"]).get("agent") or t.get("agent") or config()["runner"]["agent"]
    elapsed = seconds_since(t["started"])
    limit, usual = slow_threshold(agent)
    if elapsed < limit:
        return ""
    if any(e.get("id") == t["id"] and e.get("time", "") >= t["started"] for e in events_named("slow")):
        return ""
    reason = f"running {round(elapsed / 60)} min, " + (f"usually {round(usual / 60)} min for {agent}" if usual is not None
                                                       else f"no usual time for {agent} yet (under {SLOW_MIN_RUNS} "
                                                            f"finished runs, so {SLOW_DEFAULT // 60} min)")
    emit(t, "slow", reason=reason)
    return reason


# ---------- herdr ----------

def herdr(*args):
    return run("herdr", *args)


def herdr_available():
    if os.environ.get("TASK_HERDR") == "0" or not shutil.which("herdr"):
        return False
    return "status: running" in herdr("status", "server").stdout


def herdr_json(*args):
    r = herdr(*args)
    try:
        return json.loads(r.stdout)["result"] if r.returncode == 0 else None
    except (ValueError, KeyError):
        return None


def remember_where_asked(t, keep=False):
    """When a task is registered or started inside herdr (/task, /chief in an agent's pane), note that workspace for its tab.

    keep: a start does not replace the workspace the task was registered in.

    Only HERDR_WORKSPACE_ID counts: outside herdr, `herdr pane current` answers with whatever pane has the focus.
    The label is kept too, because herdr can hand the same id to another workspace after a restart.
    """
    ws = os.environ.get("HERDR_WORKSPACE_ID", "") if os.environ.get("HERDR_ENV") == "1" else ""
    if keep and (ASKED / f"{t['id']}.json").exists():
        return
    info = herdr_json("workspace", "get", ws) if ws and herdr_available() else None
    if info:
        ASKED.mkdir(parents=True, exist_ok=True)
        (ASKED / f"{t['id']}.json").write_text(json.dumps({"workspace": ws, "label": info["workspace"]["label"]}))


def task_workspace(t):
    """The workspace for this task's tab: where it was asked for, else one with a pane in a checkout of its repo.

    "" when there is none: the task then gets a workspace of its own.
    """
    workspaces = {w["workspace_id"]: w for w in (herdr_json("workspace", "list") or {}).get("workspaces", [])}
    f = ASKED / f"{t['id']}.json"
    asked = json.loads(f.read_text()) if f.exists() else {}
    if asked.get("workspace") in workspaces and workspaces[asked["workspace"]]["label"] == asked.get("label"):
        return asked["workspace"]
    checked = set()
    for pane in (herdr_json("pane", "list") or {}).get("panes", []):
        cwd = pane.get("cwd") or ""
        if not cwd or cwd in checked or Path(cwd).resolve().is_relative_to(DATA.resolve()):  # not task-hub's own clones
            continue
        checked.add(cwd)
        url = run("git", "-C", cwd, "remote", "get-url", "origin").stdout.strip()
        if re.search(rf"github\.com[:/]{re.escape(t['repo'])}(\.git)?/?$", url, re.I) and pane["workspace_id"] in workspaces:
            return pane["workspace_id"]
    return ""


def close_herdr(t):
    """Close this task's tab (or its own workspace). Only if it still carries this task's label: ids get reused."""
    if not (t.get("tab") or t.get("workspace")) or not herdr_available():
        return
    if t.get("tab"):
        info = herdr_json("tab", "get", t["tab"])
        if info and info["tab"]["label"].startswith(f"#{t['id']} "):
            herdr("tab", "close", t["tab"])
    else:
        info = herdr_json("workspace", "get", t["workspace"])
        if info and info["workspace"]["label"].startswith(f"task {t['id']} "):
            herdr("workspace", "close", t["workspace"])


# ---------- starting a run ----------

def clone_dir(repo):
    return DATA / "repos" / repo


def ensure_clone(repo):
    if sandbox_mode() == "off":
        refuse_after_user()
    d = clone_dir(repo)
    if not (d / ".git").exists():
        url = os.environ.get("TASK_CLONE_URL")  # tests: a local bare repo, e.g. file:///tmp/{repo}.git
        if sandbox_mode() != "off":  # the agent's user makes it, and signs in with its own gh (docs/sandbox.md)
            run(*as_agent(["mkdir", "-p", "--", d.parent]), check=True)
            run(*as_agent(["git", "clone", "-q", url.format(repo=repo) if url else f"https://github.com/{repo}.git",
                           d], cwd=d.parent), check=True)
        elif url:
            d.parent.mkdir(parents=True, exist_ok=True)
            run("git", "clone", "-q", url.format(repo=repo), d, check=True)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            # HTTPS authenticated by gh, set on this clone only: works without SSH keys and
            # leaves the user's global git config alone
            run("git", "clone", "-q", "-c", "credential.helper=", "-c", f"credential.helper=!{GH} auth git-credential",
                f"https://github.com/{repo}.git", d, check=True)
    git_shared(d, "fetch", "-q", "--prune", "origin", check=True)
    git_shared(d, "remote", "set-head", "origin", "--auto")
    return d


def check_base(base):
    """Why a Base branch value is unusable, or "" when it is fine."""
    if base.startswith("origin/"):
        return f"Base branch is a branch name without origin/, e.g. {base[len('origin/'):]}"
    if base == "HEAD" or run("git", "check-ref-format", f"refs/heads/{base}").returncode != 0:
        return f"Base branch {base!r} is not a valid branch name"
    return ""


def base_ref(t, git_dir):
    """What the task branches from and its PR goes into: the card's Base branch, else the default branch."""
    if t.get("base"):
        return f"origin/{t['base']}"
    return git_shared(git_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip() \
        or "origin/main"


def exclude_file(wt):
    exclude = Path(git_shared(wt, "rev-parse", "--git-common-dir").stdout.strip())
    return (exclude if exclude.is_absolute() else wt / exclude) / "info" / "exclude"


def ensure_internal_excludes(wt, extra=()):
    exclude = exclude_file(wt)
    existing_exclude = (shared_read(exclude) or b"").decode(errors="replace")
    missing_excludes = [name for name in [*NEVER_COMMIT, *extra] if name not in existing_exclude.splitlines()]
    if missing_excludes:
        shared_write(exclude, existing_exclude + "\n" + "\n".join(missing_excludes) + "\n")


def env_files(repo):
    """(source, destination in the worktree) for each file [env] in the config copies into this repo's worktrees.

    An entry is "source" (lands at the worktree root under its own name) or "source -> path/in/worktree".
    """
    c = config()
    value = c.get("env", repo, fallback="") if c.has_section("env") else ""  # keys are matched without regard to case
    pairs = []
    for entry in (e.strip() for e in value.split(",")):
        if entry:
            src, _, dest = (s.strip() for s in entry.partition("->"))
            pairs.append((Path(src).expanduser(), dest or Path(src).name))
    return pairs


def copy_env_files(t, wt):
    """Copy, never link: the agent may change its copy, not your checkout's. Never committed."""
    copies = {}
    for src, dest in env_files(t["repo"]):
        if not src.is_file():
            raise RuntimeError(f"env file {src} for {t['repo']} is missing; fix [env] in {home(CONFIG)}")
        target = (wt / dest).resolve()
        if Path(dest).is_absolute() or not target.is_relative_to(wt.resolve()) or target == wt.resolve():
            raise RuntimeError(f"env destination {dest} is outside the worktree; fix [env] in {home(CONFIG)}")
        # the path as git spells it: ./voice/.env, voice//.env and voice\.env (Windows) are all voice/.env, and an
        # exclude line spelled any other way matches nothing, so the secret would be committed
        rel = target.relative_to(wt.resolve()).as_posix()
        if rel in copies:
            raise RuntimeError(f"env destination {dest} is given twice; fix [env] in {home(CONFIG)}")
        copies[rel] = src
        if git_shared(wt, "ls-files", "--error-unmatch", rel).returncode == 0:
            raise RuntimeError(f"env file {rel} is tracked in {t['repo']}; copying it would change the PR")
    for rel, src in copies.items():
        if sandbox_mode() != "off":  # written by the agent's user: a link it left there leads nowhere of yours
            shared_write(wt / rel, src.read_bytes())
            continue
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        (wt / rel).unlink(missing_ok=True)  # an earlier run's copy of a read-only file cannot be written over
        shutil.copy2(src, wt / rel)
    # anchored: this path only; a wildcard character in a file name is matched as itself
    ensure_internal_excludes(wt, ["/" + re.sub(r"([*?\[\\])", r"\\\1", rel) for rel in copies])


def split_rules(text):
    """`Bash(npm test *), WebFetch` -> the two rules: commas inside parentheses stay in their rule."""
    rules, depth, current = [], 0, ""
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth <= 0:
            rules.append(current)
            current = ""
        else:
            current += ch
    return [r.strip().strip("`").strip() for r in [*rules, current] if r.strip().strip("`").strip()]


def goal_rules(body):
    """The Goal's "Rules" heading as Claude Code permissions: lines `can: ...`, `ask: ...` and `never: ...`
    become allow, ask and deny. Lines without such a word (prose) are left to the agent, which reads the Goal."""
    rules, inside = {}, False
    for line in body.splitlines():
        if line.lstrip().startswith("#") and not re.match(r"\s*#\d", line):
            inside = bool(re.match(r"\s*#+\s*rules\s*$", line, re.I))
        elif inside:
            m = re.match(r"\s*(?:[-*]\s+)?(\w+)\s*:\s*(.*)", line)
            if not m:
                continue
            if m[1].lower() not in RULE_LEVELS:
                raise RuntimeError(f'the Goal\'s Rules has a line starting "{m[1]}:"; '
                                   "each rule line starts with can:, ask: or never: (docs/task-format.md)")
            rules.setdefault(RULE_LEVELS[m[1].lower()], []).extend(split_rules(m[2]))
    return {k: rules[k] for k in ("allow", "ask", "deny") if rules.get(k)}


def write_rules(t, wt, body):
    """The Goal's Rules into the worktree's Claude Code local settings (merged with the repository's own
    .claude/settings.json; a deny holds even with --dangerously-skip-permissions). Never committed. Other agents
    get the Rules as part of the Goal in their prompt."""
    rules = goal_rules(body)
    if git_shared(wt, "ls-files", "--error-unmatch", RULES_FILE).returncode == 0:
        if rules:
            raise RuntimeError(f"{RULES_FILE} is tracked in {t['repo']}; the Goal's Rules cannot be written to it")
        return
    target = wt / RULES_FILE
    if not rules:  # Rules taken out of the Goal since the last run: remove our copy, never a file of anyone else
        if "/" + RULES_FILE in (shared_read(exclude_file(wt)) or b"").decode(errors="replace").splitlines():
            shared_unlink(target)
        return
    ensure_internal_excludes(wt, ["/" + RULES_FILE])
    shared_write(target, json.dumps({"permissions": rules}, indent=2) + "\n")


# one limit of the Goal's Budget: `2h`, `90m`, `3M tokens`, `$5`, `30 credits`; a bare `M` is millions, not minutes,
# so `3M` does not read and fails
BUDGET_ITEM = (r"(?i)^(?:\$\s*(?P<cost>\d+(?:\.\d+)?)|(?P<time>\d+(?:\.\d+)?)\s*(?P<unit>h|hours?|(?-i:m)|min|minutes?|s|sec|seconds?)"
               r"|(?P<tokens>\d+(?:\.\d+)?)\s*(?P<scale>[km]?)\s*tokens?|(?P<credits>\d+(?:\.\d+)?)\s*credits?)$")
# `paid api: openai`, also `**paid api**: openai`, `paid apis:` or `有料 API：openai`; any other line naming a paid API
# fails, as a miss would start the agent without a balance check
PAID_API = r"(?i)[*_`]*(?:paid[ _-]?apis?|有料\s*api)[*_`]*\s*[:：][*_`]*\s*(.*)"
PAID_API_WORDS = r"(?i)paid[ _-]?apis?|有料\s*api"
# the Budget heading: `Budget` or `予算`, with an optional colon and a note in brackets (`## Budget (予算)`)
BUDGET_HEADING = r"(?i)(?:budget|予算)[*_`]*\s*[:：]?\s*(?:[(（][^)）]*[)）])?"
# a line under Budget that looks meant as a limit (`tokens: 3M`, `2h まで`, `$5`, `500円`, `300万トークン`): if it does not read, it fails
BUDGET_HINT = (r"(?i)[$¥￥]\s*\d|\d\s*[万千百億]?\s*(?:k|tokens?|credits?|h|hours?|m|min|minutes?|s|sec|seconds?|トークン|クレジット"
               r"|時間|分|秒|ドル|円)(?![a-z])|(?:tokens?|credits?|cost|time|トークン|クレジット|時間|費用)\s*[:：]\s*\d")
LIST_COMMA = r"[,、，]"


def goal_budget(body):
    """The Goal's "Budget" heading as (limits, paid APIs): a line like `2h, 3M tokens, $5, 30 credits` gives the run's
    limits in place of the usual ones (over_budget), and `paid api: openai` names what must have a balance before
    the agent starts ([balance], check_balance). The heading may be `予算`, and the words `有料 API`. Lines with none
    of these are prose, left to the agent; a line with one of them, or with a number and a unit (BUDGET_HINT), that
    does not read fails, as a Rules line does: a mistyped limit would quietly be no limit, and so does a line naming a
    paid API, or a heading starting with Budget, that does not read. A `paid api:` line under any other heading fails
    too, as it would start the agent unchecked. Lines in a code block are neither headings nor limits."""
    limits, paid, inside, fenced = {}, [], False, False
    for line in body.splitlines():
        if re.match(r"\s*(```|~~~)", line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if re.match(r"\s*#+\s", line):  # a heading; `#12` (an Issue) or `#tag` is text
            title = line.strip().lstrip("#").strip().lstrip("*_`")
            inside = bool(re.fullmatch(BUDGET_HEADING, title))
            if not inside and title.lower().startswith(("budget", "予算")):
                raise RuntimeError(f"the Goal has the heading {line.strip()!r}; write the Budget heading as `## Budget` "
                                   "or `## 予算`, with the limits on the lines under it (docs/task-format.md)")
            continue
        text = re.sub(r"^\s*(?:>\s*)*(?:(?:[-*+]|\d+[.)])\s+)?", "", line).strip().strip("*_`").strip()
        if not text:
            continue
        if not inside:
            if re.fullmatch(PAID_API, text):
                raise RuntimeError(f"the Goal has {text!r} outside the Budget heading; put the paid APIs under "
                                   "`## Budget` (docs/task-format.md)")
            continue
        if m := re.fullmatch(PAID_API, text):
            names = [n.strip().strip("*_`").strip().lower() for n in re.split(LIST_COMMA, m[1])]
            names = [n for n in names if n]
            if not names or any(not re.fullmatch(r"[\w.-]+", n) for n in names):
                raise RuntimeError(f"the Goal's Budget has {text!r}; write the paid APIs as names, like "
                                   "`paid api: openai, anthropic` (docs/task-format.md)")
            paid += [n for n in names if n not in paid]
            continue
        if re.search(PAID_API_WORDS, text):
            raise RuntimeError(f"the Goal's Budget has {text!r}; write the paid APIs on their own line, like "
                               "`paid api: openai, anthropic` (docs/task-format.md)")
        items = [i.strip().strip("*_`").strip() for i in re.split(LIST_COMMA, text)]
        found = [re.fullmatch(BUDGET_ITEM, i) for i in items]
        # prose, for the agent; one in ASCII starting with a number or $, or with a number and a unit, was meant as
        # limits (`3M tokns`, `2 hrs`, `tokens: 3M`, `2h まで`)
        if not any(found) and not re.fullmatch(r"[\d$][\x20-\x7e]*", text) and not re.search(BUDGET_HINT, text):
            continue
        if not all(found):
            raise RuntimeError(f"the Goal's Budget has {text!r}; each limit is like 2h, 90m, 3M tokens, $5 "
                               "or 30 credits, separated by commas (docs/task-format.md)")
        for m in found:
            if m["cost"]:
                limits["cost"] = float(m["cost"])
            elif m["time"]:
                limits["seconds"] = round(float(m["time"]) * {"h": 3600, "m": 60, "s": 1}[m["unit"][0].lower()])
            elif m["tokens"]:
                limits["tokens"] = round(float(m["tokens"]) * {"": 1, "k": 1e3, "m": 1e6}[m["scale"].lower()])
            else:
                limits["credits"] = float(m["credits"])
    return limits, paid


def balance_command(name):
    """The [balance] command that tells whether the paid API `name` has enough balance (exit 0), or ""."""
    c = config()
    return (c.get("balance", name, fallback="") if c.has_section("balance") else "").strip()


def shell_command(cmd):
    """cmd as the shell runs it, ending at the first failing command. Windows has no sh: PowerShell, stopping at
    a failing cmdlet, ending with the last program's exit code."""
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}; $ErrorActionPreference = 'Stop'\n" + cmd
            + "\nif ($LASTEXITCODE) { exit $LASTEXITCODE }"] if WINDOWS else ["sh", "-c", "set -e\n" + cmd]


def check_balance(t, wt, say):
    """Run the [balance] command of each paid API the Goal's Budget names, in the worktree, before the agent.
    Returns why the run cannot start (a check that failed, timed out, or is not there), or "".
    Exit 0 means enough; anything else, not enough, and its last line of output says why."""
    for name in (t.get("paid_api") or "").split():
        cmd = balance_command(name)
        if not cmd:  # launch checks it too: the config may have changed since
            return f"the Goal's Budget names the paid API {name}, but [balance] has no {name} command to check it"
        say(f"== balance: {name}: {cmd}")
        # with [sandbox] on, as the agent's user, like [setup]: it reads the repository's own files (.env)
        proc = subprocess.Popen(as_agent(shell_command(cmd), wt, pass_env()), cwd=wt, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                **AGENT_GROUP)
        t["agent_running"] = True  # never saved: a Ctrl-C or SIGHUP now raises Interrupted, so the check is stopped
        output = None
        try:
            output, _ = proc.communicate(timeout=BALANCE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        finally:
            t["agent_running"] = False
            if proc.poll() is None:  # its whole group, as an agent's (sudo's with [sandbox]): a curl it started too
                stop_agent(proc)
        if output is None:
            with contextlib.suppress(subprocess.TimeoutExpired, ValueError):
                proc.communicate(timeout=AGENT_STOP_SECONDS)
            return f"the [balance] {name} check did not finish in {BALANCE_SECONDS} seconds; the agent was not started"
        lines = [line.rstrip() for line in output.splitlines() if line.strip()]
        for line in lines:
            say(line)
        if proc.returncode != 0:
            said = clip(lines[-1], 300) if lines else "no output"
            return (f"not enough balance on {name} ([balance] {name} exited {proc.returncode}: {said}); "
                    "add credit, then move the card to Ready again")
        say(f"== balance: {name}: enough")
    return ""


def setup_command(repo):
    """The [setup] command for this repo's worktrees (for example creating its virtualenv), or ""."""
    c = config()
    return (c.get("setup", repo, fallback="") if c.has_section("setup") else "").strip()


def run_setup(t, wt, say):
    """Run [setup] in the worktree before the agent. Returns why the run cannot go on, or "".

    It must leave nothing git would commit: a virtualenv the repository does not ignore, or a lockfile it rewrote,
    would land in the PR.
    """
    cmd = setup_command(t["repo"])
    if not cmd:
        return ""
    set_stage(t, "setup")
    say(f"== setup: {cmd}")
    before = set(git_shared(wt, "ls-files", "--others", "--exclude-standard").stdout.split("\n"))
    changed_before = set(git_shared(wt, "diff", "--name-only", "HEAD").stdout.split("\n"))
    # with [sandbox] on, as the agent's user: it runs on files an earlier run's agent may have rewritten
    proc = subprocess.Popen(as_agent(shell_command(cmd), wt, pass_env()), cwd=wt, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    for line in proc.stdout:
        say(line.rstrip("\n"))
    code = proc.wait()
    if code != 0:
        return f"setup failed (exit {code}), see `task log {t['id']}`"
    new = sorted(set(git_shared(wt, "ls-files", "--others", "--exclude-standard").stdout.split("\n")) - before)
    if [f for f in new if f]:
        shown = ", ".join(f for f in new if f)[:200]
        return f"setup left files git would commit ({shown}); ignore them in the repository or change [setup]"
    # a file of the repository it rewrote (npm install and package-lock.json) would be committed as the agent's work
    changed = sorted(set(git_shared(wt, "diff", "--name-only", "HEAD").stdout.split("\n")) - changed_before)
    if [f for f in changed if f]:
        shown = ", ".join(f for f in changed if f)[:200]
        return (f"setup changed files of the repository ({shown}); change [setup] so it leaves them as they are "
                "(for example npm ci instead of npm install)")
    return ""


def ensure_worktree(t):
    """The task's worktree on branch task/<number>; a re-run continues where the last run pushed."""
    first = load_run(t["id"])
    if first.get("repo") and first["repo"].lower() != t["repo"].lower():
        raise RuntimeError(f"Target repo was changed after the first run (was {first['repo']}); "
                           "set it back, or create a new task for the other repository")
    repo_dir = clone_dir(t["repo"])
    wt = DATA / "worktrees" / t["id"]
    if (wt / ".git").exists():
        common = git_shared(wt, "rev-parse", "--git-common-dir", check=True).stdout.strip()
        if not (repo_dir / ".git").exists() or not (wt / common).samefile(repo_dir / ".git"):
            raise RuntimeError("existing worktree belongs to another repository; restore its Target repo, "
                               "or create a new task for the other repository")
        if not first:  # recover legacy ownership before fetch, base checks, or env setup can fail
            t["worktree"] = str(wt)
            save_run(t)
        if first.get("snap"):  # the last run died while a reviewer or replanner had the worktree: undo its edits
            restore(wt, first["snap"].split())
            save_run({**first, "snap": ""})
    repo_dir = ensure_clone(t["repo"])
    if first.get("branch") and first.get("base", "") != t.get("base", ""):
        if git_shared(repo_dir, "rev-parse", "--verify", "-q", f"origin/task/{t['id']}").returncode == 0:
            # the pushed task branch and its PR were made from the first base: continuing on another would mix them up
            raise RuntimeError(f"Base branch was changed after the first run (was {first.get('base') or 'empty'}); "
                               f"set it back, or close the PR and delete branch task/{t['id']} to start over")
        if (wt / ".git").exists():  # nothing on GitHub yet: start over from the new base
            git_shared(repo_dir, "worktree", "remove", "--force", wt, check=True)
    if t.get("base"):
        if check_base(t["base"]):
            raise RuntimeError(check_base(t["base"]))
        if git_shared(repo_dir, "rev-parse", "--verify", "-q", f"origin/{t['base']}").returncode != 0:
            raise RuntimeError(f"branch {t['base']} is not on GitHub in {t['repo']}; "
                               "push it, then move the card to Ready again")
    if (wt / ".git").exists():
        ensure_internal_excludes(wt)
        # what a human pushed to the task branch since (the PR's "Update branch", a fix by hand): the agent starts
        # from it, and the push at the end is not refused for being behind
        remote = f"origin/{t['branch']}"
        if git_shared(wt, "rev-parse", "--verify", "-q", remote).returncode == 0 and \
                git_shared(wt, "merge", "--ff-only", "-q", remote).returncode != 0:
            raise RuntimeError(f"branch {t['branch']} on GitHub and this machine's worktree {home(wt)} have both "
                               f"changed; merge {remote} in that worktree (or delete it to start from GitHub's), "
                               "then move the card to Ready again")
        return wt
    git_shared(repo_dir, "worktree", "prune")
    branch = t["branch"]
    if git_shared(repo_dir, "rev-parse", "--verify", "-q", f"origin/{branch}").returncode == 0:
        # continue only a branch this task's own earlier run pushed; anything else is not ours to touch
        if not load_run(t["id"]).get("branch"):
            raise RuntimeError(f"branch {branch} already exists in {t['repo']} but was not made by this task; "
                               "delete or rename it, then move the card to Ready again")
        base = f"origin/{branch}"
    else:
        base = base_ref(t, repo_dir)
    git_shared(repo_dir, "worktree", "add", "-q", "-B", branch, wt, base, check=True)
    t["worktree"] = str(wt)
    save_run(t)  # env files, Issue reads, or herdr may fail next: keep ownership for retries and cleanup
    ensure_internal_excludes(wt)
    return wt


def launch(t):
    """Start `task _run <number>` in a herdr workspace, or as a background process."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", t.get("repo") or ""):
        raise RuntimeError('the card has no valid "Target repo" (owner/name)')
    t["branch"] = t.get("branch") or f"task/{t['id']}"
    t["agent"] = t.get("agent") or config()["runner"]["agent"]
    t.update(dict.fromkeys(RUN_FRESH, ""))  # of the last run (tasks() reads them in), which is over
    if not config().has_option("agents", t["agent"]):  # a typo on one card must not stop the others
        raise RuntimeError(f'unknown agent "{t["agent"]}" on the card')
    for key in ("reviewer", "replanner"):  # found now, not after the agent's work
        name = helper_agent(t, key)
        if name and not config().has_option("agents", name):
            raise RuntimeError(f'unknown {key} "{name}" in the config')
    if helper_agent(t, "reviewer"):
        review_retries()
        review_mode()
    check_sandbox()
    for name in dict.fromkeys([t["agent"], helper_agent(t, "reviewer"), helper_agent(t, "replanner")]):
        if name:  # before the worktree and before any credit is spent
            check_ready(name)
    wt = ensure_worktree(t)
    copy_env_files(t, wt)
    LOGS.mkdir(parents=True, exist_ok=True)
    earlier = load_run(t["id"])  # what this machine last ran of the task: the comments since then are new
    t["worktree"], t["log"], t["started"], t["pid"] = str(wt), str(LOGS / f"{t['id']}.log"), now(), ""
    t["stage"] = "preparing"
    prompt_file(t).parent.mkdir(parents=True, exist_ok=True)
    i = issue(t)
    # a re-run: since this machine's last start, or the last report (the run was on another machine); a first run, none
    since = earlier.get("started") or i["reported"]
    comments = comments_text(human_comments({**t, "pr": earlier.get("pr", "")}, since)) if since else ""
    t["research"] = "yes" if i["research"] else ""
    write_rules(t, wt, i["body"])
    limits, paid = goal_budget(i["body"])
    for name in paid:  # found now, not after [setup]: the human adds the check, or takes the API out of the Goal
        if not balance_command(name):
            raise RuntimeError(f"the Goal's Budget names the paid API {name}, but [balance] has no {name} command "
                               "to check its balance (docs/operations.md)")
    t["budget"], t["paid_api"] = limits or "", " ".join(paid)
    t["link"] = i["link"]
    t["link_project"] = i["link_project"]
    # the Goal as it is now (an answer added before Ready again too), whatever the team changed in the copy
    to_team(t, "the title and Goal", lambda team, n: team.edit(n, share_config(team.repo)["title"] + t["title"],
                                                               share_body(i["body"])))
    prompt_file(t).write_text(build_prompt(t, i, comments))  # kept, so you can always see what the agent was told
    if comments:
        comments_file(t).write_text(comments + "\n")
    else:
        comments_file(t).unlink(missing_ok=True)
    # the last run's: a resume reads them only from this run
    for f in (retry_file(t), review_state_file(t), finish_file(t), held_report_file(t)):
        f.unlink(missing_ok=True)
    start_run(t, IN_PROGRESS)


def start_run(t, status=""):
    """Start `task _run <number>` in a herdr tab or workspace (in place of the run's last one), or as a background
    process: for launch, and for relaunch when a run is resumed. status: the card's new Status, set once the run
    record is saved and before the run begins (launch); the card of a resumed run stays where it is."""
    cmd = [sys.executable, str(BIN), "_run", t["id"]]  # alive() and task-rs know a run by this command
    wt = Path(t["worktree"])
    # with [sandbox] on, your shell, its prompt, and the run itself stay out of the worktree: a git-aware prompt (or
    # gh) there would run git as you on the config the agent can write
    here = wt if sandbox_mode() == "off" else DATA
    t["workspace"], t["tab"] = "", ""
    if herdr_available():
        close_herdr(load_run(t["id"]))  # a re-run replaces this task's old tab or workspace, never anyone else's
        home_ws = task_workspace(t)
        if home_ws:  # a tab next to where you work on this repo
            r = herdr("tab", "create", "--workspace", home_ws, "--cwd", here, "--label",
                      f"#{t['id']} {t['title']}"[:40], "--no-focus")
        else:
            r = herdr("workspace", "create", "--cwd", here, "--label",
                      f"task {t['id']} · {t['repo'].split('/')[-1]}: {t['title']}"[:60], "--no-focus")
        if r.returncode != 0:
            raise RuntimeError(f"herdr could not open a {'tab' if home_ws else 'workspace'}: {r.stderr.strip()[-200:]}")
        res = json.loads(r.stdout)["result"]
        t["workspace"] = res["root_pane"]["workspace_id"]
        t["tab"] = res["tab"]["tab_id"] if home_ws else ""
    save_run(t)  # saved before the run starts: the run reads it, then records its pid
    if status:
        set_status(t, status)
    if t["workspace"]:
        # the pane's shell starts with the herdr server's environment, not ours: a small launcher
        # carries over what the run depends on (config/data under HOME, agents on PATH, settings, [runner] pass_env)
        names = ("HOME", "PATH", *pass_env())
        keep = {k: v for k, v in os.environ.items()
                if k in names or k.startswith(("TASK_", "GIT_AUTHOR_", "GIT_COMMITTER_"))}
        launcher = DATA / "run" / f"{t['id']}.sh"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.touch(mode=0o600)
        launcher.chmod(0o600)  # it may hold API keys
        # it may hold API keys: gone once read. Already gone: task-hub gave up on this start, so it must not run
        launcher.write_text("#!/bin/sh\nrm " + shlex.quote(str(launcher)) + " || exit 1\n"
                            "exec " + shlex.join(["env", *(f"{k}={v}" for k, v in keep.items()), *cmd]) + "\n")
        pane = res["root_pane"]["pane_id"]
        herdr("pane", "run", pane, shlex.join(["sh", str(launcher)]))
        # the run has begun once the launcher removed itself: a file, not the pane's screen, where a redraw or a
        # flood of output can hide the run's first line (#43). A brand-new shell can swallow the Enter while it is
        # still starting up: one more Enter, then give up
        for retry in (False, True):
            if retry:
                herdr("pane", "send-keys", pane, "enter")
            end = time.time() + HERDR_START_SECONDS
            while launcher.exists() and time.time() < end:
                time.sleep(0.2)
            if not launcher.exists():
                break
        else:
            # whoever removes the launcher first decides: the run, which then goes on, or this, after which it never can
            with contextlib.suppress(FileNotFoundError):
                launcher.unlink()
                raise RuntimeError("the run did not start in herdr "
                                   f"{'tab ' + t['tab'] if t['tab'] else 'workspace ' + t['workspace']}")
    else:
        start_logged(cmd, here, t["log"])


def start_logged(cmd, cwd, log_path):
    """Start a run in the background, its output appended to its log, outliving the command that starts it."""
    with open(log_path, "ab") as log:
        start = lambda flags: subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log,
                                               stderr=subprocess.STDOUT, env={**os.environ, "TASK_RUN_LOGGED": "1"},
                                               **flags)
        try:  # Windows: out of the watch's Task Scheduler job, so stopping the watch leaves the run going
            return start({"creationflags": DETACHED["creationflags"] | subprocess.CREATE_BREAKAWAY_FROM_JOB}
                         if WINDOWS else DETACHED)
        except PermissionError:  # the job does not allow it
            return start(DETACHED)


# ---------- resuming a run that stopped unexpectedly (docs/architecture/designs/durable-runs.md) ----------

def resumable(t):
    """Why the run (In progress on the board, its `_run` gone) cannot be resumed; "" when it can. relaunch then
    starts it again from its stage; anything else is Blocked, as before (decision 7)."""
    stage, wt = t.get("stage") or "", Path(t.get("worktree") or "/nonexistent")
    if stage not in RESUME_STAGES:
        return f"a run does not go on from its stage {stage}" if stage else "the run had ended"
    if t.get("interrupted") == "SIGINT":
        return "it was stopped with Ctrl-C"
    if int(t.get("resumes") or 0) >= MAX_RESUMES:
        return f"it was resumed {MAX_RESUMES} time(s) already"
    if not (wt / ".git").exists():
        return f"its worktree {home(wt)} is gone"
    # finishing commits itself; during review, a commit is the reviewer's, which its snapshot takes back
    if t.get("head") and stage not in ("review", "finishing") and \
            git_shared(wt, "rev-parse", "HEAD").stdout.strip() != t["head"]:
        return "the worktree's HEAD moved since its agent started (a commit by someone else)"
    if stage == "review" and not t.get("snap"):  # nothing to undo the reviewer's edits with
        return "it stopped during review with no snapshot of the worktree to go back to"
    if stage == "preparing" and not prompt_file(t).exists():
        return "its prompt is gone"
    if stage == "retry" and not retry_file(t).exists():
        return "the prompt of its retry after review is gone"
    if stage == "finishing" and not finish_file(t).exists():
        return "what it was finishing with is gone"
    return ""


def stopped_reason(t, why):
    """The Blocked reason of a run that stopped unexpectedly and was not resumed. why: what kept it from resuming."""
    if not t.get("stage"):  # it had ended, but could not move the card (GitHub was unreachable); resumed or not
        return "the run stopped unexpectedly"
    if int(t.get("resumes") or 0) >= MAX_RESUMES:
        return f"the run stopped unexpectedly again, after resuming once at {t.get('resumed') or 'some stage'}"
    return f"the run stopped unexpectedly; {why}"


def relaunch(t):
    """Start a run that stopped unexpectedly again, once, from its stage. The caller holds launch_lock and has
    checked that the run is not alive, as for launch and launch_fix: then no one else writes its record."""
    stop_left_agent(t)
    why = t.get("interrupted") or "the run process is gone"
    note_resume(t, t["stage"], why)
    t.update(resume_stage=t["stage"], resumed_at=now(), pid="")
    save_run(t)
    emit(t, "resumed", stage=t["stage"], reason=why)
    try:
        start_run(t)
    except BaseException:  # the card is Blocked next (sync): no run is on its way, for alive() to wait two minutes for
        t.update(resume_stage="", resumed_at="")
        save_run(t)
        raise


def note_resume(t, stage, why):
    """Count one resume of the run, at stage, and why it was cut short (both stay for its report and metrics)."""
    t["resumes"] = str(int(t.get("resumes") or 0) + 1)
    t["resumed"] = " ".join([*(t.get("resumed") or "").split(), stage])
    t["interrupted"] = why
    save_run(t)


def stop_left_agent(t):
    """Stop what is left of the run's agent (agent_pid's process group): two agents must never write the same
    worktree. A process now holding that pid is another one if it started at another time than agent_started
    (pids are handed out again); none at all, and what the agent left in its group is stopped, since no process
    gets a group's id while the group has anyone left in it (POSIX). RuntimeError when it does not stop."""
    pid = int(t.get("agent_pid") or 0)
    if not pid:
        return
    if WINDOWS:  # no ps; the command line names the task, its prompt being one of the arguments
        if f"Task {t['id']}:" in windows_command_line(pid):
            run("taskkill", "/T", "/F", "/PID", str(pid))
        return
    r = run("ps", "-p", str(pid), "-o", "etime=")
    if r.returncode == 0 and r.stdout.strip():
        started = time.time() - elapsed_seconds(r.stdout.strip())
        if not t.get("agent_started") or abs(started - epoch(t["agent_started"])) > 5:
            return  # another process got the pid: the agent's group is long gone
    if not stop_group(pid, (signal.SIGTERM, signal.SIGKILL)):
        raise RuntimeError(f"the agent left from the run (process group {pid}) does not stop")


def stop_group(pgid, signals):
    """Send each signal in turn to the process group until nothing is left in it, giving each AGENT_STOP_SECONDS;
    whether it is empty now (POSIX)."""
    for sig in signals:
        signal_agent(pgid, sig)
        end = time.time() + AGENT_STOP_SECONDS
        while group_left(pgid) and time.time() < end:
            time.sleep(0.1)
        if not group_left(pgid):
            return True
    return False


def group_left(pgid):
    """Whether any process is left in the process group (zombies, which only wait for their parent, are not)."""
    r = run("ps", "-A", "-o", "pgid=,stat=")
    return any(len(f) == 2 and f[0] == str(pgid) and not f[1].startswith("Z") for f in map(str.split, r.stdout.splitlines()))


def elapsed_seconds(etime):
    """`ps -o etime` ([[dd-]hh:]mm:ss) in seconds."""
    days, _, rest = etime.rpartition("-")
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return int(days or 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def resume_prompt(prompt, stage, why):
    """The prompt of an agent started again after it was cut short: all of its first prompt, then # Resumed
    (worker/PROMPT.md), enough to work from without the conversation, which the agent may not have kept."""
    return "\n".join([prompt.rstrip("\n"), "", instruction_parts(WORKER_PROMPT)[2], "",
                      f"It stopped during: {stage} ({interrupted_text(why)})", ""])


def prompt_file(t):
    return DATA / "prompts" / f"{t['id']}.md"


def retry_file(t):
    """The prompt of the agent's retry after review (review_loop), for a run resumed during it."""
    return DATA / "prompts" / f"{t['id']}-retry.md"


def review_state_file(t):
    """What review_loop knows of its earlier rounds (the findings it sent back, the size of each retry's change), for a
    run resumed during review or retry."""
    return DATA / "prompts" / f"{t['id']}-review.json"


def finish_file(t):
    """What finish is given besides the report (review_loop's outcome, the agent's exit code), for a run resumed
    during finishing: it was only in the memory of the run that stopped."""
    return DATA / "prompts" / f"{t['id']}-finish.json"


def held_report_file(t):
    """The agent's report while a Goldfish auditor runs (hide_report): out of the worktree the auditor inspects."""
    return DATA / "prompts" / f"{t['id']}-report.md"


def hide_report(t):
    """Move the agent's report out of the worktree until unhide_report: a Goldfish auditor judges the Goal and the
    code, never the report, and would find the report there with one `ls -a`."""
    wt = Path(t["worktree"])
    text = agent_file(wt / REPORT_FILE)
    if text is not None:
        write_atomic(held_report_file(t), text)
        shared_unlink(wt / REPORT_FILE)


def unhide_report(t):
    """Put back the report hide_report moved out; also one a run cut short during a Goldfish review left there."""
    held = held_report_file(t)
    if held.exists():
        shared_write(Path(t["worktree"]) / REPORT_FILE, held.read_text())
        held.unlink()


def comments_file(t):
    """The comments the run's prompt gave the agent (human_comments), for its reviewer; none, no file."""
    return DATA / "prompts" / f"{t['id']}-comments.md"


def instruction_parts(path, count=3):
    """A worker/*.md file without its header: the instructions, then the part sent only with comments, then the
    part sent only to a resumed agent (worker/PROMPT.md; "" for those a file does not have). worker/READINESS.md has
    count=4 parts: the rules and one per stage of `task check` (readiness_parts)."""
    return [*(part.strip() for part in path.read_text().split("\n---\n")[1:]), *[""] * count][:count]


def build_prompt(t, i, comments=""):
    instructions, about_comments, _ = instruction_parts(WORKER_PROMPT)
    lines = [instructions, "", "# Your task", "", f"Task {t['id']}: {t['title']}", f"Repository: {t['repo']}",
             f"Branch: {t['branch']} (already checked out in the current directory)",
             *([f"Based on: {t['base']} (the work continues that branch; the PR goes into it)"] if t.get("base") else []),
             *([f"Came after: {', '.join(x['ref'] + ' ' + x['title'] for x in t['blockers'])} "
                "(finished before this run started)"] if t.get("blockers") else []),
             *(["Kind: research. Your report is the deliverable: put the answer in its Report's Summary and the findings "
                "under its Details. Change files only if the Goal asks for a file."] if t.get("research") else []),
             "", i["body"].strip()]
    if i["report"]:
        lines += ["", "# Earlier run", "", "An earlier run of this task stopped. Its report:", "",
                  i["report"].replace(REPORT_MARK, "").strip()]
        if section(i["report"], "Suggested instructions"):
            lines += ["", "Its Suggested instructions were there for the human to check before moving the card to "
                          "Ready again: follow them, unless the Goal or a comment since says otherwise."]
    answered = [r for r in i["replans"] if "\nDecision: answered\n" in r]
    if answered:
        lines += ["", "# Replanner notes", "",
                  "Another agent answered what the earlier run was blocked on, from the repository. "
                  "Check its evidence before you rely on it:", "", answered[-1].replace(REPLAN_MARK, "").strip()]
    if comments:
        lines += ["", about_comments, "", comments]
    return "\n".join(lines) + "\n"


def staged_diff(t):
    """The whole PR as it will be pushed: all files, new ones included, from where the branch left its base."""
    wt = t["worktree"]
    git_shared(wt, "add", "-A", check=True)
    fork = git_shared(wt, "merge-base", base_ref(t, wt), "HEAD").stdout.strip() or "HEAD"
    return git_shared(wt, "diff", "--cached", fork, "--").stdout


def pr_size(t, wt):
    """(files, lines added, lines removed) of the whole branch since it left its base: what the PR asks you to review."""
    if sandbox_mode() != "off":  # as GitHub has it: the agent's user pushed it
        files = (branch_compare(t, base_ref(t, wt)) or {}).get("files") or []
        return {"files": len(files), "added": sum(int(f.get("additions") or 0) for f in files),
                "removed": sum(int(f.get("deletions") or 0) for f in files)}
    fork = git_shared(wt, "merge-base", base_ref(t, wt), "HEAD").stdout.strip()
    files = added = removed = 0
    for line in git_shared(wt, "diff", "--numstat", fork, "HEAD").stdout.splitlines() if fork else []:
        plus, minus, _ = line.split("\t", 2)
        files += 1
        added += int(plus) if plus.isdigit() else 0  # "-" for a binary file
        removed += int(minus) if minus.isdigit() else 0
    return {"files": files, "added": added, "removed": removed}


def branch_compare(t, base):
    """GitHub's comparison of the task branch with its base (ahead_by, files with additions and deletions), or None
    when the branch is not on GitHub."""
    try:
        return gh_json("api", f"repos/{t['repo']}/compare/{quote(base.split('/', 1)[-1])}...{quote(t['branch'])}")
    except RuntimeError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return None
        raise


def snapshot(wt):
    """Everything in the worktree, staged, as (tree, HEAD): what a read-only helper must leave as it found it."""
    git_shared(wt, "add", "-A", check=True)
    return (git_shared(wt, "write-tree", check=True).stdout.strip(),
            git_shared(wt, "rev-parse", "HEAD", check=True).stdout.strip())


def hold_snapshot(t):
    """snapshot of the run's worktree, also kept in its record until release_snapshot: if the run dies before then,
    the next launch restores it (ensure_worktree)."""
    t["snap"] = " ".join(snapshot(Path(t["worktree"])))
    save_run(t)
    return t["snap"].split()


def release_snapshot(t, snap):
    """restore, then forget the snapshot; True if the helper had changed the worktree."""
    edited = restore(Path(t["worktree"]), snap)
    t["snap"] = ""
    save_run(t)
    return edited


def restore(wt, snap):
    """Put the worktree back to `snap`; True if a read-only helper had changed it (reviewer, replanner).

    A change is anything that reached the PR's files: edited, staged, deleted, a new staged file, or a commit.
    New files it never staged are leftovers of test runs: removed, but not an offence. Ignored files stay.
    """
    tree, head = snap
    moved = git_shared(wt, "rev-parse", "HEAD").stdout.strip() != head
    edited = moved or git_shared(wt, "write-tree").stdout.strip() != tree \
        or git_shared(wt, "diff", "--quiet").returncode != 0
    if edited:
        if moved:
            git_shared(wt, "reset", "-q", "--soft", head, check=True)  # its commit never reaches the PR
        git_shared(wt, "read-tree", tree, check=True)
        git_shared(wt, "checkout-index", "-a", "-f", check=True)
    git_shared(wt, "clean", "-fdq", check=True)  # also removes new files it had staged
    return edited


def claude_projects():
    """Where Claude Code keeps its transcripts: one JSON line per message, with the API usage on assistant lines."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


USAGE_KEYS = {"input": "input_tokens", "cache_creation": "cache_creation_input_tokens",
              "cache_read": "cache_read_input_tokens", "output": "output_tokens"}


def transcript_call(line, dirs, began, ended):
    """(message id, call) for an assistant line written in `dirs` between began and ended, else None."""
    try:
        d = json.loads(line)
        if not isinstance(d, dict) or d.get("type") != "assistant":
            return None
        cwd = d.get("cwd") or ""
        if not any(cwd == w or cwd.startswith(w.rstrip("/") + "/") for w in dirs):
            return None
        at = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
        if not began <= at <= ended:
            return None
        m, model = d["message"], d["message"].get("model") or ""
        if model == "<synthetic>":  # Claude Code's own placeholder messages: no API call behind them
            return None
        call = {k: int(m["usage"].get(v) or 0) for k, v in USAGE_KEYS.items()}
        call.update(model=model, subagent=d.get("isSidechain") is True)
        return m.get("id") or d.get("uuid"), call
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):  # a broken line or a changed format
        return None


def agent_usage(wt, began, ended):
    """What the agent CLIs' own records say one launch in `wt` used, or None when there are none.

    Read from outside, never asked of the agent. Every reader is tried on every launch, whatever the agent's name:
    Claude Code's transcripts (tokens), pi's sessions (tokens and cost) and kiro-cli's two session stores (credits);
    other agents simply have none.
    A record counts if its directory is the worktree and its time falls within the launch: the agent, the reviewer,
    and the replanner run one after another in the same worktree, so the time tells them apart.
    """
    dirs = {str(wt), os.path.realpath(wt)}  # the agent may see the real path (/private/var on macOS)
    used = {}
    for found in (read(dirs, began, ended) for read in (claude_usage, pi_usage, kiro_db_usage, kiro_session_usage)):
        for k, v in (found or {}).items():
            used[k] = sorted(set(used.get(k, [])) | set(v)) if k == "models" else used.get(k, 0) + v
    if "credits" in used:
        used["credits"] = round(used["credits"], 2)  # Kiro meters to the second decimal point
    if "cost" in used:
        used["cost"] = round(used["cost"], 6)  # USD, as pi works it out from the model's prices
    return used or None


def claude_usage(dirs, began, ended):
    """Claude Code's calls: one API call is written as one line per content block, so they are counted by message.id.

    Files not written since the launch began are never opened, and lines without the worktree's path never parsed:
    the user's own long conversations are in the same folders.
    """
    needles = dirs | {json.dumps(w)[1:-1] for w in dirs}
    calls, root = {}, claude_projects()
    for folder, _, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            try:
                if not name.endswith(".jsonl") or os.path.getmtime(path) < began:
                    continue
                subagents = "subagents" in Path(path).relative_to(root).parts
                with open(path, errors="replace") as f:
                    for line in f:
                        found = any(n in line for n in needles) and transcript_call(line, dirs, began, ended)
                        if found:
                            key, call = found
                            call["subagent"] = call["subagent"] or subagents or calls.get(key, {}).get("subagent", False)
                            calls[key] = call  # the last line of a call has its final usage
            except OSError:  # removed or unreadable meanwhile
                continue
    if not calls:
        return None
    used = {k: sum(c[k] for c in calls.values()) for k in USAGE_KEYS}
    return {"calls": len(calls), **used, "subagent_calls": sum(c["subagent"] for c in calls.values()),
            "models": sorted({c["model"] for c in calls.values() if c["model"]})}


def pi_sessions():
    """Where pi keeps its sessions: one JSON line per entry, the first one the session's header with its cwd
    (pi 1.4.0's docs/session-format.md). Its own settings.json sessionDir is not read: set the variable instead."""
    if base := os.environ.get("PI_CODING_AGENT_SESSION_DIR"):
        return Path(base).expanduser()
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent").expanduser() / "sessions"


# pi's usage field -> ours; its cost is in USD, under cost.total
PI_USAGE_KEYS = {"input": "input", "cache_creation": "cacheWrite", "cache_read": "cacheRead", "output": "output"}


def pi_usage(dirs, began, ended):
    """pi's calls in the worktree during the launch: its assistant messages and its other entries with a usage
    (compaction, branch summaries, cache warming), each one call. Checked on pi 1.4.0's `-p --mode json`.

    A session counts when its header's cwd is the worktree; `--session-id` goes on with the same file on a resume,
    so the entry's own time tells this launch's calls from the earlier ones. Files not written since the launch
    began are never opened.
    """
    calls = {k: 0 for k in PI_USAGE_KEYS} | {"calls": 0, "cost": 0.0}
    models = set()
    for path in pi_sessions().glob("*/*.jsonl"):
        try:
            if path.stat().st_mtime < began:
                continue
            with open(path, errors="replace") as f:
                header = json.loads(f.readline())
                cwd = (header.get("cwd") or "") if header.get("type") == "session" else ""
                if not any(cwd == w or cwd.startswith(w.rstrip("/") + "/") for w in dirs):
                    continue
                for line in f:
                    found = pi_call(line, began, ended)
                    if found:
                        call, model = found
                        for k in calls:
                            calls[k] += call[k]
                        models |= {model} if model else set()
        except (OSError, ValueError, AttributeError):  # gone, unreadable, or a header of another format
            continue
    if not calls["calls"]:
        return None
    return {**calls, "models": sorted(models)}


def pi_call(line, began, ended):
    """(call, model) for one entry of a pi session with a usage, written between began and ended, else None."""
    try:
        d = json.loads(line)
        m = d.get("message") if d.get("type") == "message" else None
        if m is not None and m.get("role") != "assistant":
            return None
        u = (m or d).get("usage")
        if not isinstance(u, dict) or not began <= epoch(d["timestamp"]) <= ended:
            return None
        call = {k: int(u.get(v) or 0) for k, v in PI_USAGE_KEYS.items()}
        cost = u.get("cost")
        total = float((cost.get("total") if isinstance(cost, dict) else 0) or 0)
        call.update(calls=1, cost=total if total == total and abs(total) != float("inf") else 0.0)  # not NaN
        model = (m or d).get("model")
        return call, model if isinstance(model, str) else ""
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):  # a broken line or a changed format
        return None


def kiro_db():
    """kiro-cli's v1 session store: a SQLite database, one row per (directory, conversation)."""
    base = Path.home() / "Library/Application Support" if sys.platform == "darwin" \
        else Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "kiro-cli" / "data.sqlite3"


def kiro_sessions():
    """kiro-cli's v2 session store: one <uuid>.json per session, next to its conversation (<uuid>.jsonl)."""
    return Path.home() / ".kiro" / "sessions" / "cli"


def credits(usage):
    """The credits in kiro-cli's [{"value": 0.12, "unit": "credit"}, ...]; kiro-cli keeps no token counts."""
    return sum(float(u["value"]) for u in usage or [] if u.get("unit") == "credit")


def kiro_db_usage(dirs, began, ended):
    """Conversations kiro-cli 2.2.0's --no-interactive wrote in the worktree during the launch (v1, checked on it).

    Opened read-only; missing, locked, or of another shape, it simply has nothing to say.
    """
    import sqlite3
    path = kiro_db()
    if not path.is_file():
        return None
    try:
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)
        try:
            rows = db.execute(f"SELECT value FROM conversations_v2 WHERE key IN ({','.join('?' * len(dirs))}) "
                              "AND created_at <= ? AND updated_at >= ?",
                              (*dirs, int(ended * 1000), int(began * 1000))).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    used = {"calls": 0, "credits": 0.0, "models": set()}
    for (value,) in rows:
        try:
            d = json.loads(value)
            turn = d["user_turn_metadata"]
            requests = turn.get("requests") or []
            spent = credits(turn.get("usage_info"))
            models = {r.get("model_id") for r in requests} | {(d.get("model_info") or {}).get("model_id")}
        except (ValueError, KeyError, TypeError, AttributeError):  # a value of a format we do not know
            continue
        used["calls"] += len(requests)
        used["credits"] += spent
        used["models"] |= {m for m in models if m and isinstance(m, str)}
    return {**used, "models": sorted(used["models"])} if used["calls"] or used["credits"] else None


def kiro_session_usage(dirs, began, ended):
    """User turns kiro-cli's v2 sessions (newer versions) ended in the worktree during the launch.

    Their input/output token counts are always 0, so only the credits are read. Files not written since the launch
    began are never opened.
    """
    used = {"calls": 0, "credits": 0.0, "models": set()}
    for path in kiro_sessions().glob("*.json"):
        try:
            if path.stat().st_mtime < began:
                continue
            d = json.loads(path.read_text(errors="replace"))
            cwd = d.get("cwd") or ""
            if not any(cwd == w or cwd.startswith(w.rstrip("/") + "/") for w in dirs):
                continue
            state = d["session_state"]
            turns = [t for t in state["conversation_metadata"]["user_turn_metadatas"]
                     if began <= epoch(t.get("end_timestamp") or d.get("updated_at")) <= ended]
            spent = sum(credits(t.get("metering_usage")) for t in turns)
            calls = sum(int(t.get("total_request_count") or 0) for t in turns)
            model = ((state.get("rts_model_state") or {}).get("model_info") or {}).get("model_id")
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):  # gone, or another format
            continue
        if turns:
            used["calls"] += calls
            used["credits"] += spent
            used["models"] |= {model} if model and isinstance(model, str) else set()
    return {**used, "models": sorted(used["models"])} if used["calls"] or used["credits"] else None


def epoch(at):
    """Seconds since 1970 from an ISO 8601 time or a number (milliseconds when that large)."""
    if isinstance(at, (int, float)) and not isinstance(at, bool):
        return at / 1000 if at > 1e11 else at
    return datetime.datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()


def tokens(u):
    return sum(u.get(k) or 0 for k in USAGE_KEYS)


def short(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e4 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


def run_agent_process(agent, prompt, wt, say, label, usage=None, t=None, resume=False, session=None):
    """Run one agent launch; its role, agent, seconds, and what it used (when readable) go into the `usage` list.
    t: the run, whose record notes the agent's pid while it runs. resume: with [resume] <agent> (agent_command).
    session: its {session}; None, a new one."""
    say(f"== {label}: {agent}" + (" ([resume])" if resume and has_resume_command(agent) else ""))
    began = time.time()
    code = agent_process(agent, prompt, wt, say, t, resume, session)
    if usage is not None:
        ended = time.time()
        entry = {"role": label, "agent": agent, "seconds": round(ended - began)}
        try:
            used = agent_usage(wt, began, ended)
        except Exception as e:  # like append_jsonl: measuring must never cost the run
            say(f"== could not read what the {label} used: {e}")
            used = None
        if used:
            entry.update(used)
            said = [f"{used['calls']} calls"]
            if "output" in used:
                said.append(f"{short(tokens(used))} tokens ({short(used['output'])} out)")
            if "subagent_calls" in used:
                said.append(f"{used['subagent_calls']} subagent calls")
            if "cost" in used:
                said.append(f"${used['cost']:.4f}")
            if "credits" in used:
                said.append(f"{used['credits']:.2f} credits")
            say(f"== {label} used {', '.join(said)}, models {', '.join(used['models']) or 'unknown'}")
        usage.append(entry)
        if t is not None:
            try:
                over_budget(t, usage, say)
            except Exception as e:  # like the measuring itself: the budget must never cost the run, for now
                say(f"== could not check the budget: {e}")
    return code


def run_used(usage):
    """What a run's launches used so far, per budget measure; a measure no launch has a record of is left out."""
    used = {"seconds": sum(u.get("seconds") or 0 for u in usage)}
    if any("output" in u for u in usage):
        used["tokens"] = sum(tokens(u) for u in usage if "output" in u)
    for k in ("cost", "credits"):
        if any(k in u for u in usage):
            used[k] = round(sum(u.get(k) or 0 for u in usage), 6)
    return used


def budget_limits(agent, goal=None):
    """The run's limit for each budget measure, with where it comes from: the Goal's Budget, else BUDGET_TIMES the
    median of the agent's finished runs (at least BUDGET_FLOOR), else BUDGET_DEFAULT."""
    totals = {k: [] for k in BUDGET_TIMES}
    for line in (METRICS.read_text(errors="replace").splitlines() if METRICS.exists() else []):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict) and r.get("agent") == agent and r.get("blocked_by") not in AGENT_NEVER_RAN:
            for k, v in run_used(r.get("usage") or [{"seconds": r.get("seconds") or 0}]).items():
                totals[k].append(v)
    limits = {}
    for k, values in totals.items():
        if k in (goal or {}):
            limits[k] = (goal[k], "the Goal's Budget")
        elif len(values) >= BUDGET_MIN_RUNS:
            limits[k] = (max(BUDGET_TIMES[k] * median(values), BUDGET_FLOOR[k]),
                         f"{BUDGET_TIMES[k]} x the median of {len(values)} runs of {agent}")
        else:
            limits[k] = (BUDGET_DEFAULT[k], f"the default, under {BUDGET_MIN_RUNS} runs of {agent} measured")
    return limits


def budget_text(k, n):
    return {"seconds": lambda: f"{n / 3600:.1f}h" if n >= 3600 else f"{round(n / 60)}m",
            "tokens": lambda: f"{short(round(n))} tokens", "cost": lambda: f"${n:.2f}",
            "credits": lambda: f"{n:.2f} credits"}[k]()


def over_budget(t, usage, say, save=True, what=""):
    """An `over budget` event for each measure the run just went past its limit in, once per measure and run.
    Only the event, for now: the run goes on (docs/design.md, decision 18).
    save: False for what is no run (`task check`): what it told is kept in t only. what: the reason's first words."""
    told = (t.get("over_budget") or "").split()
    limits = budget_limits(t.get("agent") or "", t.get("budget") or None)
    over = [(k, n) for k, n in run_used(usage).items() if k not in told and n > limits[k][0]]
    if not over:
        return
    reason = what + "; ".join(f"used {budget_text(k, n)}, over {budget_text(k, limits[k][0])} ({limits[k][1]})"
                              for k, n in over)
    say(f"== over budget: {reason}")
    t["over_budget"] = " ".join(told + [k for k, _ in over])
    if save:
        save_run(t)
    emit(t, "over budget", reason=reason)


HELPERS = set()  # the agents running without a run (t=None: `task check`'s Goldfish), for Ctrl-C to stop
HELPERS_LOCK = threading.Lock()


def agent_process(agent, prompt, wt, say, t=None, resume=False, session=None):
    import queue
    proc = None
    if t is not None:
        t["agent_running"] = True  # never saved: tells cmd_run's signal handler there is an agent to stop
        # never saved either: whether task-hub itself stopped it (Ctrl-C) or the Watchdog did, and how many tool calls
        # it showed
        t["agent_stopped"], t["agent_silenced"], t["agent_steps"], t["agent_group"] = False, False, 0, 0
    try:
        if t is not None:
            stop_left_commands(t, say)  # never two writers in one worktree: a cut-short agent's long test, say
        argv, env = windows_command(agent_command(agent, prompt, resume, session or new_session()))
        env.update(command_groups_env(t))
        argv = as_agent(argv, wt, [*pass_env(), *env])
        proc = subprocess.Popen(argv, cwd=wt, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", env={**os.environ, **env},
                                **AGENT_GROUP)
        if t is not None:
            t["agent_pid"], t["agent_started"] = str(proc.pid), now()
            t["agent_group"] = proc.pid  # never saved: kept after it ends, for what it left in its group (run_worker)
            save_run(t)
        else:
            with HELPERS_LOCK:
                HELPERS.add(proc)
        steps = STEPS.get(step_format(agent), Steps)(wt)
        lines = queue.Queue()  # read in a thread, so the watchdog runs while the agent is silent

        def read():
            try:
                for line in proc.stdout:
                    lines.put(line)
            finally:
                lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        dog = Watchdog(proc, say)
        while True:
            try:
                line = lines.get(timeout=min(1.0, SILENT_CHECK))
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                dog.heard()
                for shown in steps.read(line.rstrip("\n")):
                    say(shown)
                    if t is not None and shown.startswith("· "):  # tool_step's form
                        t["agent_steps"] += 1
            if dog.watch():  # it stopped the agent: what left its group may hold the output open, so not read on
                if t is not None:
                    t["interrupted"], t["agent_silenced"] = "silent", True
                    save_run(t)
                break
        for shown in steps.close():
            say(shown)
        if dog.stopped is not None:
            return dog.stopped
        code = proc.wait()
        return 1 if code == 0 and steps.failed else code
    except (KeyboardInterrupt, Interrupted) as e:  # Ctrl-C in the pane stops the agent; still push what it did
        code = stop_agent(proc) if proc else 130
        if t is not None:
            t["agent_stopped"] = True
        if isinstance(e, Interrupted):  # SIGHUP, SIGTERM: the whole run stops (cmd_run)
            raise
        say("== stopped with Ctrl-C")
        return code
    except OSError as e:
        if getattr(e, "winerror", None) == 206:  # Windows: the command line is over 32,767 characters, which
            # Python reports as FileNotFoundError: not "agent not found", which would send the human to the wrong fix
            say(f"agent cannot run: its command line is over Windows' 32,767 characters (a long goal or report): {e}")
        else:
            say(f"agent {'not found' if isinstance(e, FileNotFoundError) else 'cannot run'}: {e}")
        return 127
    except RuntimeError as e:  # windows_command: a batch file it cannot run
        say(f"agent cannot run: {e}")
        return 127
    finally:
        with HELPERS_LOCK:
            HELPERS.discard(proc)
        if t is not None:
            t["agent_running"] = False
            if t.get("agent_pid") and (proc is None or proc.returncode is not None):
                t["agent_pid"] = t["agent_started"] = ""  # nothing of it left to stop
                save_run(t)


def commands_dir(t):
    """runs/<id>.groups: a file for each process group the task's agents ran a tool command in, named after it and
    holding its leader's start time (worker/group-shell). It outlives the command, until the next stop_left_commands."""
    return RUNS / f"{t['id']}.groups"


def command_groups_env(t):
    """The variables that have worker/group-shell note the agent's tool commands, so that what a cut-short agent
    left running can be stopped (stop_left_commands): the folder for the notes; group-shell for pi's bash tool
    (pi/task-groups.ts, which the built-in [agents] pi loads); and group-shell as Claude Code's
    CLAUDE_CODE_SHELL_PREFIX, unless you set one or its path has " -" (where Claude Code would cut it).
    Agents with no such hook (codex, kiro) note nothing. None without a task, on Windows (no group-shell), and with
    [sandbox] mode = user (its user cannot write the notes here)."""
    if t is None or WINDOWS or sandbox_mode() != "off" or not os.access(GROUP_SHELL, os.X_OK):
        return {}  # never a shell the agent's commands cannot run in
    env = {"TASK_HUB_GROUPS": str(commands_dir(t)), "TASK_HUB_GROUP_SHELL": str(GROUP_SHELL)}
    if "CLAUDE_CODE_SHELL_PREFIX" not in os.environ and " -" not in str(GROUP_SHELL):
        env["CLAUDE_CODE_SHELL_PREFIX"] = str(GROUP_SHELL)
    return env


def stop_left_commands(t, say):
    """Stop what tool commands an earlier agent of the task left running, before another one starts. pi and Claude Code
    start each command in a process group of its own, which stopping the agent's group does not reach (lld.md 7): a
    long test cut short with its agent went on beside the resumed one. group-shell noted each group with its leader's
    start time, and the note outlives the command: a group is stopped only while that leader still lives, so neither
    an ended command nor a process the id went to since. The notes go. RuntimeError when a group does not stop."""
    d = commands_dir(t)
    if WINDOWS or not d.is_dir():
        return
    leaders = None
    for f in sorted(d.iterdir()):
        if not f.name.isdigit():  # a note being written (.<pid>)
            continue
        noted = ""
        with contextlib.suppress(OSError):
            noted = " ".join(f.read_text().split())
        if leaders is None:
            leaders = group_leaders()
        pgid = int(f.name)
        if not noted or leaders.get(pgid) != noted:
            continue
        if not stop_group(pgid, (signal.SIGTERM, signal.SIGKILL)):
            raise RuntimeError(f"a command an earlier agent left running (process group {pgid}) does not stop")
        say(f"== stopped process group {pgid}: a command an earlier agent left running")
    shutil.rmtree(d, ignore_errors=True)


def group_leaders():
    """{pgid: its leader's start time (ps lstart)} of the processes that lead their own process group; none when ps
    cannot run (then nothing is stopped: it cannot be told apart)."""
    try:
        r = subprocess.run(["ps", "-A", "-o", "pid=,pgid=,lstart="], capture_output=True, text=True,
                           env={**os.environ, "LC_ALL": "C"})
    except OSError:
        return {}
    leaders = {}
    for fields in map(str.split, r.stdout.splitlines()):
        if len(fields) > 2 and fields[0] == fields[1] and fields[0].isdigit():
            leaders[int(fields[0])] = " ".join(fields[2:])
    return leaders


class Interrupted(BaseException):
    """SIGHUP or SIGTERM reached `_run` (its pane closed, a shutdown, kill) while an agent runs: agent_process stops
    the agent, and cmd_run ends. A BaseException, as KeyboardInterrupt: no `except Exception` stops it."""


def signal_agent(pid, sig):
    """Send sig to the agent's process group. With [sandbox] mode = user its processes are another user's, which
    this one may not signal: that user sends it too (sudo, the group's leader, is ours and passes it on)."""
    with contextlib.suppress(OSError):
        os.killpg(pid, sig)
    if sandbox_mode() != "off":
        with contextlib.suppress(OSError, RuntimeError):
            run(*as_agent(["kill", "-s", sig.name[3:], "--", f"-{pid}"]))


def stop_agent(proc):
    """Stop the agent and everything it started (AGENT_GROUP); its exit code. SIGTERM first, then after
    AGENT_STOP_SECONDS SIGKILL, also for what it started and left behind. Never waits without a limit."""
    if WINDOWS:
        run("taskkill", "/T", "/F", "/PID", str(proc.pid))
    else:
        signal_agent(proc.pid, signal.SIGTERM)
        try:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=AGENT_STOP_SECONDS)
        finally:  # a second Ctrl-C while it waits too
            # what it left behind: a group's id is never given out again while anything is left in it (POSIX)
            signal_agent(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=AGENT_STOP_SECONDS)
    return proc.returncode if proc.returncode is not None else -9


class Watchdog:
    """Stops what a silent agent waits on (decision 19). A log that is only quiet is no hang (docs/lessons.md): it
    acts only when the agent printed nothing for SILENT_SECONDS and its descendants used no CPU since the last check
    (ps), so a long test or build that works without printing is left alone. Then the descendants, never the agent
    itself, get SIGTERM and AGENT_STOP_SECONDS later SIGKILL; the agent sees its command fail and goes on. Still
    silent, and its descendants still idle, SILENT_GRACE after that (after SILENT_SECONDS when there was nothing to
    stop), the agent's whole group is stopped (stop_agent). Without ps (Windows) whether the descendants use CPU is
    unknown, so the watchdog stops nothing: silence alone is no hang."""

    def __init__(self, proc, say):
        self.proc, self.say = proc, say
        self.stopped = None  # the agent's exit code, once the watchdog stopped it
        self.kill, self.kill_at = {}, 0.0  # descendants sent SIGTERM, to get SIGKILL at kill_at if still there
        self.heard()

    def heard(self):
        """The agent printed a line: it is not silent."""
        self.last, self.checked, self.before, self.cut_at = time.monotonic(), 0.0, None, None

    def watch(self):
        """Called after each line and each second without one. True once it stopped the agent itself."""
        at = time.monotonic()
        if self.kill and at >= self.kill_at:
            left = [pid for pid in self.kill if pid in (agent_descendants(self.proc.pid) or {})]
            signal_pids(left, signal.SIGKILL)
            self.kill = {}
        silent = at - self.last
        # ps starts one check early, so the first decision at SILENT_SECONDS has a check before it to compare with
        if silent < SILENT_SECONDS - SILENT_CHECK or at - self.checked < SILENT_CHECK:
            return False
        self.checked = at
        before, self.before = self.before, agent_descendants(self.proc.pid)
        seen = self.before
        idle = seen is not None and seen == before  # the same processes, none with more CPU time
        if silent < SILENT_SECONDS:
            return False
        if idle and seen and self.cut_at is None:
            self.cut_at = at
            self.kill, self.kill_at = seen, at + AGENT_STOP_SECONDS
            shown = ", ".join(f"{pid} {name}" for pid, (_cpu, name) in sorted(seen.items()))
            self.say(f"== watchdog: no output for {span(silent)} and no CPU used by what the agent started: "
                     f"stopping it ({shown})")
            signal_pids(seen, signal.SIGTERM)
        elif idle and at - (self.last + SILENT_SECONDS if self.cut_at is None else self.cut_at) >= SILENT_GRACE:
            self.say(f"== watchdog: no output for {span(silent)}: stopping the agent")
            self.stopped = stop_agent(self.proc)
            return True
        return False


def span(seconds):
    return f"{seconds / 60:.0f} min" if seconds >= 120 else f"{seconds:.0f} s"


def agent_descendants(pid):
    """{pid: (CPU seconds, command name)} of what the agent started and what is left in its group (AGENT_GROUP),
    the agent itself left out, from `ps -o time`; None when ps cannot be run (Windows). With [sandbox] mode = user
    the agent is under sudo: each sudo with one child is passed through to it."""
    if WINDOWS:
        return None
    try:
        r = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "pgid=", "-o", "stat=", "-o", "time=",
                            "-o", "comm="],
                           capture_output=True, text=True, errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    table = {}
    for line in r.stdout.splitlines():
        with contextlib.suppress(ValueError):
            p, parent, group, stat, cpu, name = line.split(None, 5)
            if not stat.startswith("Z"):  # exited, only its status left for its parent: nothing to stop
                table[int(p)] = (int(parent), int(group), cpu_seconds(cpu), Path(name.strip()).name)
    children = {}
    for p, (parent, *_rest) in table.items():
        children.setdefault(parent, []).append(p)
    agent = [pid]
    while agent[-1] in table and table[agent[-1]][3] == "sudo" and len(children.get(agent[-1], [])) == 1:
        agent.append(children[agent[-1]][0])
    found, todo = set(), list(children.get(agent[-1], [])) + [p for p, v in table.items() if v[1] == pid]
    while todo:
        p = todo.pop()
        if p not in found and p not in agent and p != os.getpid():
            found.add(p)
            todo += children.get(p, [])
    return {p: (table[p][2], table[p][3]) for p in found}


def cpu_seconds(s):
    """ps's `time`: [[dd-]hh:]mm:ss, with hundredths on macOS (0:01.25)."""
    days, _, clock = s.rpartition("-")
    seconds = sum(float(x) * 60 ** i for i, x in enumerate(reversed(clock.split(":"))))
    return (int(days) if days else 0) * 86400 + seconds


def signal_pids(pids, sig):
    """Send sig to these processes. With [sandbox] mode = user they may be another user's: that user sends it too."""
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, sig)
    if pids and sandbox_mode() != "off":
        with contextlib.suppress(OSError, RuntimeError):
            run(*as_agent(["kill", "-s", sig.name[3:], "--", *map(str, pids)]))


def step_format(name):
    """Which CLI's JSON events the agent's command asks for, as the built-in commands do: "claude" or "kiro" for
    --output-format stream-json (kiro when the command runs kiro-cli), "codex" for `codex exec --json`, "pi" for
    `pi --mode json`, or None for text. Only the command is looked at, never the prompt: a goal may well mention
    these flags."""
    parts = shlex.split(config()["agents"].get(name, ""))
    programs = {re.sub(r"\.(exe|cmd)$", "", Path(p).name, flags=re.I) for p in parts}
    given = lambda flag, value: f"{flag}={value}" in parts or any(
        a == flag and b == value for a, b in zip(parts, parts[1:]))
    if given("--output-format", "stream-json"):
        return "kiro" if programs & {"kiro-cli", "kiro-cli-chat"} else "claude"
    if "codex" in programs and "exec" in parts and "--json" in parts:
        return "codex"
    if "pi" in programs and given("--mode", "json"):
        return "pi"
    return None


def cut(s):
    """One step as one log line of at most LOG_LINE_MAX characters."""
    return s if len(s) <= LOG_LINE_MAX else s[:LOG_LINE_MAX - 3] + "..."


def first_line(text):
    return next((t.strip() for t in text.splitlines() if t.strip()), "")


class Steps:
    """An agent's output as log lines: as it came, for a command that prints text. The subclasses read one CLI's
    JSON events (step_format) into a line per tool call (`· <tool>: <target>`, tool_step) and per text (its first
    line), the final answer in full, and nothing for tool results, thinking, or bookkeeping. There, a line that is
    not JSON stays as it is, and JSON of a type or shape we do not know is kept, cut to LOG_LINE_MAX."""
    failed = False  # the events said the run failed, which the CLI's exit code may not (pi --mode json exits 0)

    def __init__(self, wt):
        self.wt = wt

    def lines(self, line):
        return [line]

    def end(self):
        """What is still held back when the output ends."""
        return []

    # What agent_process calls. Showing the output must never cost the run, whatever a CLI prints: a reader that
    # breaks (any exception, on a shape we do not know) keeps the line as it came, and the run goes on.
    def read(self, line):
        try:
            return self.lines(line)
        except Exception:
            return [cut(line)]

    def close(self):
        try:
            return self.end()
        except Exception as e:
            return [cut(f"== cannot show the end of the agent's output ({type(e).__name__}: {e})")]


class ClaudeSteps(Steps):
    def lines(self, line):
        return stream_json_lines(line, self.wt)


class JsonSteps(Steps):
    def lines(self, line):
        try:
            d = json.loads(line)
        except ValueError:
            return [line]
        if not isinstance(d, dict) or "type" not in d:
            return [line]
        try:
            shown = self.event(d)
        except (KeyError, TypeError, AttributeError, IndexError):  # a shape we do not know
            shown = None
        return [cut(line)] if shown is None else shown

    def event(self, d):
        """The log lines for one event, or None for a type we do not know."""
        return None


class CodexSteps(JsonSteps):
    """`codex exec --json` (checked on codex-cli 0.160.0): items that start and complete. A tool call is shown when
    it starts. A message is held until the next item: then its first line is shown, or, when the turn ends, all of
    it, as `codex exec` prints its last message."""
    NAMES = {"command_execution": "shell", "file_change": "apply_patch", "todo_list": "update_plan"}

    def __init__(self, wt):
        super().__init__(wt)
        self.said, self.started, self.error = "", set(), None

    def held(self):
        first, self.said = first_line(self.said), ""
        return [cut(first)] if first else []

    def end(self):
        said, self.said = self.said, ""
        return said.splitlines()

    def event(self, d):
        kind = d["type"]
        if kind in ("thread.started", "turn.started", "item.updated"):
            return []
        if kind == "turn.completed":
            return self.end()
        if kind in ("error", "turn.failed"):
            message = str((d["error"] if kind == "turn.failed" else d)["message"])
            if message == self.error:  # codex says it twice: the error, then the failed turn
                return []
            self.error = message
            return self.held() + f"ERROR: {message}".splitlines()
        if kind not in ("item.started", "item.completed"):
            return None
        item = d["item"]
        if item["type"] == "agent_message":
            shown, self.said = self.held(), str(item.get("text") or "")
            return shown
        if item["type"] == "reasoning":
            return []
        if item["type"] == "error":  # a warning: the turn goes on
            return self.held() + [cut(f"warning: {item['message']}")]
        if item["id"] in self.started:
            return []
        self.started.add(item["id"])
        return self.held() + [cut(f"· {self.step(item)}")]

    def step(self, item):
        kind = item["type"]
        if kind == "command_execution":
            return tool_step("shell", {"command": unwrapped(item["command"])}, self.wt)
        if kind == "file_change":
            paths = ", ".join(shown_path(c["path"], self.wt) for c in item.get("changes") or [])
            return f"apply_patch: {paths}" if paths else "apply_patch"
        if kind == "mcp_tool_call":
            return tool_step(f"{item['server']}.{item['tool']}", item.get("arguments"), self.wt)
        if kind == "web_search":
            return tool_step("web_search", {"query": item.get("query")}, self.wt)
        return self.NAMES.get(kind, kind)


def unwrapped(command):
    """`/bin/zsh -lc 'cargo test'`, as codex reports the commands it runs: `cargo test`."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if len(parts) == 3 and Path(parts[0]).name in ("sh", "bash", "zsh") and parts[1] in ("-c", "-lc"):
        return parts[2]
    return command


class PiSteps(JsonSteps):
    """`pi -p --mode json` (checked on pi 1.1.0 and 1.4.0). A tool call is shown when it starts to run, and the text
    of a message that calls tools by its first line. The last message of a run is held: pi may compact its context and go
    on (after a context overflow or an answer cut short), and then it is shown by its first line. When pi settles, or
    the output ends, the held one is shown in full, as `pi -p` prints it, or why it failed: `pi -p` then exits 1,
    but pi --mode json exits 0, so `failed` is set."""
    QUIET = {"session", "turn_start", "turn_end", "message_start", "message_update", "tool_execution_update",
             "tool_execution_end", "queue_update", "entry_appended", "session_info_changed", "thinking_level_changed",
             "compaction_end", "auto_retry_end"}

    def __init__(self, wt):
        super().__init__(wt)
        self.last = None

    def end(self):
        last, self.last = self.last, None
        if last is None:
            return []
        self.failed = last.get("stopReason") in ("error", "aborted")
        if self.failed:
            return f"== pi ended with {last['stopReason']}: {last.get('errorMessage') or 'no message'}".splitlines()
        return self.text(last).splitlines()

    @staticmethod
    def text(message):
        return "\n".join(b["text"] for b in message["content"] if b.get("type") == "text")

    def event(self, d):
        kind = d["type"]
        if kind in self.QUIET:
            return []
        indent = "  " if d.get("parentToolCallId") else ""  # a subagent's step
        if kind == "tool_execution_start":
            return [cut(f"{indent}· {tool_step(d.get('toolName') or 'tool', d.get('args'), self.wt)}")]
        if kind == "message_end":
            m = d["message"]
            if m.get("role") != "assistant" or not any(b.get("type") == "toolCall" for b in m["content"]):
                return []  # the last message is shown whole at the end
            first = first_line(self.text(m))
            return [cut(indent + first)] if first else []
        if kind == "agent_start":  # pi goes on after compacting: the held message was not the last
            last, self.last = self.last, None
            first = "" if indent or last is None or last.get("stopReason") == "error" else first_line(self.text(last))
            return [cut(first)] if first else []
        if kind == "agent_end":
            last = (d.get("messages") or [{}])[-1]
            if not indent and not d.get("willRetry") and last.get("role") == "assistant":
                self.last = last
            return []
        if kind == "agent_settled":
            return [] if indent else self.end()
        if kind == "auto_retry_start":
            return [cut(f"== pi retries ({d.get('attempt')}/{d.get('maxAttempts')}): {d.get('errorMessage')}")]
        if kind == "compaction_start":
            return [f"== pi compacts its context ({d.get('reason')})"]
        return None


class KiroSteps(JsonSteps):
    """kiro-cli's --output-format stream-json (checked on kiro-cli 2.28.0): ACP session updates. The text comes in
    chunks. What came before a tool call is shown by its first line, and what came after the last one, the final
    answer, in full when the run finishes."""
    QUIET = {"tool_call_update", "agent_thought_chunk", "user_message_chunk", "plan", "available_commands_update",
             "current_mode_update"}

    def __init__(self, wt):
        super().__init__(wt)
        self.text = ""

    def end(self):
        text, self.text = self.text, ""
        return text.splitlines()

    def event(self, d):
        kind = d["type"]
        if kind in ("runStarted", "metadata"):
            return []
        if kind == "runFinished":
            data = d["data"]
            ended = [] if data.get("status") == "success" else [
                f"== kiro ended with {data.get('status')} ({data.get('stopReason')})"]
            return self.end() + ended
        if kind == "runError":
            self.failed = True
            return self.end() + f"== kiro ended with an error: {d['data'].get('message')}".splitlines()
        if kind != "sessionUpdate":
            return None
        update = d["data"]["update"]
        what = update["sessionUpdate"]
        if what == "agent_message_chunk":
            self.text += update["content"].get("text") or ""
            return []
        if what == "tool_call":
            first, self.text = first_line(self.text), ""
            return ([cut(first)] if first else []) + [cut(f"· {self.step(update)}")]
        return [] if what in self.QUIET else None

    def step(self, update):
        """`shell: cargo test`, `read: src/x.rs`: kiro-cli's name for the tool, and its command or file."""
        name = ((update.get("_meta") or {}).get("kiro") or {}).get("toolName") or update.get("kind") or "tool"
        args = dict(update["rawInput"]) if isinstance(update.get("rawInput"), dict) else {}
        if update.get("kind") != "execute":
            args.pop("command", None)  # write's "create" or "strReplace", not a command
        if not isinstance(args.get("path"), str) and update.get("locations"):
            args["path"] = update["locations"][0].get("path")
        return tool_step(name, args, self.wt)


STEPS = {"claude": ClaudeSteps, "codex": CodexSteps, "pi": PiSteps, "kiro": KiroSteps}


def stream_json_lines(line, wt):
    """The log lines for one line of Claude Code's stream-json: one per tool call and per text (its first line), the
    final result in full, and nothing for the rest (tool results, hooks, system). A line that is not JSON stays as
    it is. No tool result and no input beyond the one shown reaches the log, and no step is over LOG_LINE_MAX.
    JSON of another type or shape (a newer Claude Code) is kept, cut to LOG_LINE_MAX."""
    try:
        d = json.loads(line)
    except ValueError:
        return [line]
    if not isinstance(d, dict) or "type" not in d:
        return [line]
    if d["type"] in ("system", "user", "rate_limit_event", "stream_event"):  # hooks, tool results, partial messages
        return []
    try:
        if d["type"] == "result":
            text = d.get("result") if isinstance(d.get("result"), str) else ""
            ended = [f"== claude ended with {d.get('subtype') or 'an error'}"] if d.get("is_error") else []
            return text.splitlines() + ended
        if d["type"] != "assistant":
            return [cut(line)]
        indent = "  " if d.get("parent_tool_use_id") else ""  # a subagent's step
        shown = []
        for block in d["message"]["content"]:
            if block.get("type") == "tool_use":
                shown.append(f"{indent}· {tool_step(block.get('name') or 'tool', block.get('input'), wt)}")
            elif block.get("type") == "text":
                first = first_line(block["text"])
                shown += [indent + first] if first else []
        return [cut(s) for s in shown]
    except (KeyError, TypeError, AttributeError):  # a shape we do not know
        return [cut(line)]


def tool_step(name, args, wt):
    """`Bash: cargo test`, `Edit: src/x.rs`, `Grep: "pattern"`: the tool and the one input that says what it does."""
    if not isinstance(args, dict):  # no input, or one of a shape we do not know: only the name
        return name
    for key in ("command", "file_path", "notebook_path", "pattern", "url", "query", "description", "skill", "path"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            break
    else:
        return name
    lines = value.strip().splitlines()
    value = lines[0] + " ..." * (len(lines) > 1)
    if key in ("file_path", "notebook_path", "path"):
        value = shown_path(value, wt)
    return f'{name}: "{value}"' if key == "pattern" else f"{name}: {value}"


def shown_path(path, wt):
    """The path from the worktree when it is in it. The agents give the real path (/private/var on macOS)."""
    for base in (os.path.realpath(wt), str(wt)):
        try:
            return Path(path).relative_to(base).as_posix()
        except ValueError:
            continue
    return path


def build_review_prompt(t, goal, report, diff, sent=(), comments="", auditor=None, readiness=""):
    """sent: the findings earlier reviews of this run sent the agent back with. comments: what people wrote since the
    earlier run (comments_file). auditor: (name, what each auditor is told, its persona) for one Goldfish auditor
    ([runner] review_mode = goldfish), which gets readiness (`task check`'s comment on the Goal, if any) and never the
    agent's report; None: the one reviewer, which gets the report."""
    instructions, about_comments, about_sent, _ = instruction_parts(WORKER_REVIEW, 4)
    limit = 12000 if WINDOWS else 20000  # Windows: the whole prompt goes on a command line of 32,767 characters
    if len(diff) > limit:
        diff = diff[:limit] + "\n... (diff truncated)\n"
    if auditor:
        name, about, persona = auditor
        head = [instructions, "", f"# Goldfish review: {name}", "", about, "", persona]
        given = ["", "# Readiness check of the Goal", "",
                 clip_text(readiness.replace(READINESS_MARK, "").strip(), limit // 2)] if readiness else []
    else:
        head, given = [instructions], ["", "# Agent report", "", report.strip() or "(no report)"]
    return "\n".join([*head, "", "# Task", "", f"Task {t['id']}: {t['title']}",
                      f"Repository: {t['repo']}", f"Branch: {t['branch']}", "", "## Goal", "",
                      goal.strip(), *(["", about_comments, "", comments] if comments else []),
                      *(["", about_sent, "", *sent] if sent else []),
                      *given, "", "# Diff", "", "```diff", diff, "```", ""])


def review_auditors():
    """worker/REVIEW.md's Goldfish part as (what each auditor is told, {auditor: its persona})."""
    part = instruction_parts(WORKER_REVIEW, 4)[3]
    about, _, personas = part.partition("\n## ")
    named = dict((n.strip(), text.strip()) for n, text in re.findall(r"(?ms)^## ([^\n]+)\n(.*?)(?=^## |\Z)",
                                                                     "## " + personas))
    if not personas or not named:
        raise RuntimeError(f"{home(WORKER_REVIEW)} names no Goldfish auditor (a `## ` heading in its fourth part)")
    return about.strip(), named


def run_review(t, report, say, usage=None, sent=()):
    """The reviewer's verdict on the whole PR, or None when no reviewer is set or there is nothing to review.
    sent: the findings earlier reviews of this run sent the agent back with."""
    reviewer = helper_agent(t, "reviewer")  # "agent": the task's own agent, in a fresh context
    if not reviewer:
        return None
    if not config().has_option("agents", reviewer):
        raise RuntimeError(f'unknown reviewer "{reviewer}" in the config')
    wt = Path(t["worktree"])
    diff = staged_diff(t)
    if not diff.strip():
        if not t.get("research"):
            return None  # finish() blocks it as "changed no files"
        diff = "(no file changes: this is a research task, and the agent's report above is the deliverable)"
    set_stage(t, "review")
    i = issue(t)
    comments = comments_file(t).read_text().strip() if comments_file(t).exists() else ""
    # a research task's report is its deliverable: a review without it would have nothing to judge
    mode = "agent" if t.get("research") else review_mode()

    def launch(prompt, label):
        shared_unlink(wt / REVIEW_FILE)
        if mode == "goldfish":  # out of the prompt, and out of the worktree the auditor inspects
            hide_report(t)
        try:
            snap = hold_snapshot(t)
            code = run_agent_process(reviewer, prompt, wt, say, label, usage, t)
            return review_result(label, code, release_snapshot(t, snap), agent_file(wt / REVIEW_FILE))
        finally:
            unhide_report(t)
    return review_by(mode, launch, t, i["body"], report, diff, sent, comments, i.get("readiness_comment", ""), say)


def review_by(mode, launch, t, goal, report, diff, sent=(), comments="", readiness="", say=print):
    """The review in mode: one reviewer given the agent's report (agent), or each Goldfish auditor of worker/REVIEW.md
    in a fresh context of its own, one after another, never given the report, and their results combined (goldfish).
    launch(prompt, label): one reviewer launch's ReviewResult (review_result)."""
    if mode == "agent":
        result = launch(build_review_prompt(t, goal, report, diff, sent, comments), "reviewer")
    else:
        about, auditors = review_auditors()
        found = {}
        for name, persona in auditors.items():  # in turn: the worktree, [setup] and the usage measured are the run's
            found[name] = launch(build_review_prompt(t, goal, "", diff, sent, comments, (name, about, persona),
                                                     readiness), name)
            say(f"== {name}: {found[name].verdict or 'missing'}")
        result = combine_reviews(found)
    result.mode = mode
    return result


def review_result(label, code, edited, text):
    """One reviewer launch's ReviewResult: blocked when it changed files (edited) or wrote no REVIEW_FILE (text None)."""
    who = label[:1].upper() + label[1:]
    if edited:
        return ReviewResult(f"## Verdict\n\nblocked\n\n## Review\n\n{who} changed files; its edits were undone. "
                            "Reviewers must only inspect the worktree.")
    if text is None:
        return ReviewResult(f"## Verdict\n\nblocked\n\n## Review\n\n{who} exited {code} without writing {REVIEW_FILE}.")
    return ReviewResult(text)


RETRY_ASK = "Revise the work once, update .task-report.md, and stop."


def review_loop(t, report, code, say, record, resume_at="", why=""):
    """Review before the PR; on "needs changes", send the work back to the agent, up to [runner] review_retries times.
    Returns (report, code, review section, blocked).

    Sending back stops early when it is not getting anywhere (review_stop): a finding comes back after the retry it
    was sent back with, or the retries' changes are not getting smaller. A review that stops it blocks the card, and
    its section ends with Suggested instructions for the next run.
    Each verdict goes into record["reviews"], record["retries"] counts the retries (record["retried"]: any), and
    record["review_stop"] says why the last "needs changes" was not sent back. Each launch is measured into
    record["usage"].
    resume_at, why: a resumed run (relaunch) goes on from its review ("review": review_attempt says which) or from
    its retry ("retry", with the retry's prompt as it was saved, then the next review), cut short for why.
    """
    wt = Path(t["worktree"])
    attempt = int(t.get("review_attempt") or 0) if resume_at in ("review", "retry") else 0
    state = {"sent": [], "sizes": [], "tree": ""}
    if attempt and review_state_file(t).exists():
        state.update(json.loads(review_state_file(t).read_text()))
    record["retries"], record["retried"] = attempt, attempt > 0
    if resume_at == "retry":
        feedback = retry_file(t).read_text()
        section = feedback.rpartition("\n# Automated review feedback\n\n")[2].rpartition(f"\n\n{RETRY_ASK}")[0]
        code, report = review_retry(t, feedback, state, say, record, why)
        if not report.strip() or AgentReport(report).blocked:
            return report, code, section, ""
    elif not report.strip() or AgentReport(report).blocked:  # finish() blocks these anyway
        return report, code, "", ""
    while True:
        t["review_attempt"] = str(attempt)
        review = run_review(t, report, say, record["usage"], state["sent"])
        if review is None:
            return report, code, "", ""
        review.attempt = attempt + 1
        say(f"== reviewer verdict: {review.verdict or 'missing'}")
        record["reviews"].append(review.verdict or "missing")
        record["review_mode"], record["review_verdict"] = review.mode, review.field_verdict
        if review.passed:
            return report, code, review.issue_section(), ""
        if not review.needs_changes:
            return report, code, review.issue_section(), review.blocked_line()
        stop, record["review_stop"] = review_stop(review, state, attempt)
        if stop:
            say(f"== {stop}")
            return (report, code, review.issue_section() + "\n\n" + review.suggested_instructions(stop, state["sent"]),
                    review.blocked_line(stop))
        feedback = "\n".join([prompt_file(t).read_text(), "", "# Automated review feedback", "",
                              review.issue_section(), "", RETRY_ASK, ""])
        attempt += 1
        record["retries"], record["retried"] = attempt, True
        retry_file(t).write_text(feedback)  # before the stage: a run resumed during the retry reads it
        shared_unlink(wt / REPORT_FILE)  # a retry that dies must not pass for the first run's report
        t["head"] = git_shared(wt, "rev-parse", "HEAD").stdout.strip()
        state = {"sent": state["sent"] + review.findings, "sizes": state["sizes"], "tree": staged_tree(wt)}
        write_atomic(review_state_file(t), json.dumps(state))
        t["review_attempt"] = str(attempt)  # the retry's number, then the next review's
        set_stage(t, "retry")
        code, report = review_retry(t, feedback, state, say, record)
        if not report.strip() or AgentReport(report).blocked:
            return report, code, review.issue_section(), ""


def review_retry(t, feedback, state, say, record, why=""):
    """The agent's retry after a "needs changes" review: (its exit code, its report). The size of its change (the
    lines it added and removed since state["tree"], the worktree before it) goes into state, for review_stop."""
    wt = Path(t["worktree"])
    code = run_worker(t, feedback, "retry", "agent retry after review", say, record, why)
    if state["tree"]:  # none: a run resumed in a retry it started before task-hub kept the tree
        state["sizes"].append(changed_lines(wt, state["tree"]))
        write_atomic(review_state_file(t), json.dumps(state))
    return code, agent_file(wt / REPORT_FILE) or ""


def review_stop(review, state, retries):
    """Why a "needs changes" review is not sent back again ("" to send it back), and the word for record["review_stop"]:
    the limit ([runner] review_retries) is reached, or the retries are not getting anywhere: a finding came back after
    the retry it was sent back with, the last retry changed nothing, or it changed as much as the one before it or
    more (the change is not converging)."""
    limit, sizes, done = review_retries(), state["sizes"], f"after {plural(retries, 'retry', 'retries')}"
    if retries and review.repeated(state["sent"]):
        return f"automated review stopped {done}: a finding came back after the retry it was sent back with", "repeated"
    if retries and sizes and sizes[-1] == 0:
        return f"automated review stopped {done}: the last retry changed no files", "no change"
    if len(sizes) > 1 and sizes[-1] >= sizes[-2]:
        return (f"automated review stopped {done}: the retries' changes are not getting smaller "
                f"({' then '.join(map(str, sizes[-2:]))} changed lines)", "not converging")
    if retries >= limit:
        return (f"automated review did not pass {done}" if limit else
                "automated review: needs changes ([runner] review_retries = 0: it is never sent back)"), "limit"
    return "", ""


def plural(n, one, many):
    return f"{'one' if n == 1 else n} {one if n == 1 else many}"


def staged_tree(wt):
    """The worktree as git would commit it now: a tree object, to measure what the next agent changes in it."""
    git_shared(wt, "add", "-A", check=True)
    return git_shared(wt, "write-tree", check=True).stdout.strip()


def changed_lines(wt, tree):
    """Lines added and removed in the worktree since tree (staged_tree); a binary file counts as one."""
    git_shared(wt, "add", "-A", check=True)
    numstat = git_shared(wt, "diff", "--cached", "--numstat", tree, "--").stdout
    return sum(int(a) + int(r) if a.isdigit() and r.isdigit() else 1
               for a, r, *_ in (line.split("\t") for line in numstat.splitlines() if line.count("\t") >= 2))


def run_worker(t, prompt, stage, label, say, record, resumed_why=""):
    """The task's agent at stage (agent, retry); its exit code. Killed by something other than task-hub (POSIX: a
    negative code; never Ctrl-C) or stopped by the Watchdog, it is started again in place, once (MAX_RESUMES) for
    the whole run.
    resumed_why: this `_run` was itself started again (relaunch) to go on with it, cut short for that reason."""
    if resumed_why:
        return run_resumed_worker(t, prompt, stage, label, say, record, resumed_why)
    code = run_agent_process(t["agent"], prompt, Path(t["worktree"]), say, label, record["usage"], t,
                             session=start_session(t, stage))
    # Windows: an exit code never says a signal ended it
    if WINDOWS or code >= 0 or t.get("agent_stopped") or int(t.get("resumes") or 0) >= MAX_RESUMES:
        return code
    why = "silent" if t.get("agent_silenced") else f"the agent was killed ({signal_name(-code)})"
    said = interrupted_text(why)
    # what the killed agent started (a test run, a subagent) may still write the worktree: never two agents at once
    if t.get("agent_group") and not stop_group(t["agent_group"], (signal.SIGKILL,)):
        say(f"== {said} during {stage}; what it left in process group {t['agent_group']} does not stop, "
            "so it is not resumed")
        return code
    say(f"== {said} during {stage}; resuming it once")
    note_resume(t, stage, why)
    emit(t, "resumed", stage=stage, reason=why)
    return run_resumed_worker(t, prompt, stage, label, say, record, why)


def run_resumed_worker(t, prompt, stage, label, say, record, why):
    """The agent started again after it was cut short: [resume] <agent> if there is one, with # Resumed after its
    prompt. A [resume] command that did nothing (no tool call, no report, a failing exit: it found no conversation
    to go on with) gets one more go as [agents] <agent>, a new session, within the same resume.
    The resume command gets the {session} of the launch cut short at stage (none recorded: a new one); [agents]
    <agent>, a new session, always a new one: claude's --session-id refuses one in use."""
    wt = Path(t["worktree"])
    text = resume_prompt(prompt, stage, why)
    session = t.get("session") if t.get("session_role") == stage and has_resume_command(t["agent"]) else ""
    code = run_agent_process(t["agent"], text, wt, say, f"{label}, resumed", record["usage"], t, resume=True,
                             session=session or start_session(t, stage))
    if has_resume_command(t["agent"]) and code != 0 and not t.get("agent_stopped") and not t.get("agent_steps") \
            and agent_file(wt / REPORT_FILE) is None:
        say("== the [resume] command did nothing; starting the agent again in a new session")
        code = run_agent_process(t["agent"], text, wt, say, f"{label}, resumed in a new session", record["usage"], t,
                                 session=start_session(t, stage))
    return code


def start_session(t, stage):
    """A new {session} for the task's agent at stage (agent, retry), saved before the launch for a resume to read."""
    t["session"], t["session_role"] = new_session(), stage
    save_run(t)
    return t["session"]


def signal_name(signum):
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"signal {signum}"


def unverified_evidence(wt, evidence):
    """The evidence lines that do not check out. Each must be `path:line` plus a `quote` that is on that line.

    The path must be one git tracks: a file the replanner wrote itself where git does not look (an ignored folder,
    which restore leaves) proves nothing. A quote of under 3 characters is on almost any line."""
    items = [line.strip() for line in evidence.splitlines() if line.strip()]
    bad = []
    for item in items:
        m = re.search(r"([^\s`:]+):(\d+)\D.*?`([^`]+)`", item)
        ok = False
        if m and len(m.group(3).strip()) >= 3:
            path = (wt / m.group(1)).resolve()
            data = shared_read(path) if path.is_relative_to(wt.resolve()) else None
            if data is not None and git_shared(
                    wt, "ls-files", "--error-unmatch", "--", path.relative_to(wt.resolve())).returncode == 0:
                lines = data.decode(errors="replace").splitlines()
                n = int(m.group(2))
                ok = 1 <= n <= len(lines) and m.group(3).strip() in lines[n - 1]
        if not ok:
            bad.append(item)
    return bad if items else ["no evidence given"]


def build_replan_prompt(t, report):
    instructions = WORKER_REPLAN.read_text().split("\n---\n", 1)[-1].strip()
    return "\n".join([instructions, "", "# Task", "", f"Task {t['id']}: {t['title']}", f"Repository: {t['repo']}",
                      "", "## Goal", "", issue(t)["body"].strip(), "", "# The agent's report", "", report.strip(), ""])


def run_replan(t, report, say, usage=None):
    """Triage the agent's own Blocked: answer it from the repository, or sharpen the question for the human.

    It only comments; the card stays Blocked and the human decides whether to move it to Ready.
    Returns the decision, "skipped", "ignored" (no usable result), or "" when it did not run.
    """
    name, blocked = helper_agent(t, "replanner"), AgentReport(report).blocked
    if not name or not blocked:
        return ""
    replans = issue(t)["replans"]
    if sum("\nDecision: answered\n" in r for r in replans) >= MAX_REPLAN_ANSWERS:
        say(f"== replanner: skipped, it already answered {MAX_REPLAN_ANSWERS} times")
        return "skipped"
    if replans and f"\nBlocked: {blocked}\n" in replans[-1]:
        say("== replanner: skipped, blocked for the same reason as last time")
        return "skipped"
    wt = Path(t["worktree"])
    shared_unlink(wt / REPLAN_FILE)
    set_stage(t, "replanning")
    snap = hold_snapshot(t)
    code = run_agent_process(name, build_replan_prompt(t, report), wt, say, "replanner", usage, t)
    if release_snapshot(t, snap):
        say("== replanner changed files; its edits were undone and its result is ignored")
        return "ignored"
    text = agent_file(wt / REPLAN_FILE)
    if text is None:
        say(f"== replanner exited {code} without writing {REPLAN_FILE}")
        return "ignored"
    decision = (section(text, "Decision").splitlines() or [""])[0].strip(" *`_.").lower()
    note = ""
    if decision == "answered":
        bad = unverified_evidence(wt, section(text, "Evidence"))
        if bad:  # an answer we cannot check is exactly the invented kind; the human gets the question instead
            decision = "human"
            note = f"The replanner's answer was not used: its evidence could not be verified ({'; '.join(bad)[:300]})."
    if decision == "answered":
        details = [f"### Answer\n\n{section(text, 'Answer')}", f"### Evidence\n\n{section(text, 'Evidence')}",
                   "Move the card to Ready to re-run with this answer (the next run gets it as Replanner notes). "
                   "If it is wrong, answer in the Goal instead."]
    elif decision == "human":
        question = (section(text, "For the human").splitlines() or [""])[0] or blocked
        details = [note] * bool(note) + [f"### Question for you\n\n{question}",
                                          "Answer in the Goal, then move the card to Ready."]
    elif decision == "goal-conflict":
        details = [f"### Proposed goal change\n\n{section(text, 'Proposed goal change')}",
                   "Edit the Goal if you agree, then move the card to Ready."]
    else:
        say(f"== replanner wrote an unknown decision {decision!r}")
        return "ignored"
    body = "\n\n".join([f"{REPLAN_MARK}\n\n## Replanner\n\nBlocked: {blocked}\nDecision: {decision}", *details])
    comment(t, body)
    say(f"== replanner decision: {decision}")
    emit(t, "replan", decision=decision, digest=digest(replan=body))
    return decision


# ---------- readiness: `task check`, the Goldfish's GO / NO-GO on a Goal before it starts (docs/task-format.md) ----------

def goal_hash(body):
    """The Goal a readiness verdict was given for: 16 hex characters of the SHA-256 of the Issue body, its line ends
    and outer blank space aside. Any other edit of the Goal makes the verdict stale."""
    import hashlib
    return hashlib.sha256(body.replace("\r\n", "\n").strip().encode()).hexdigest()[:16]


NONE_WORDS = {"", "-", "none", "n/a", "na", "nothing", "none found", "no findings", "nothing blocking", "none blocking",
              "no blocking findings", "no minor findings", "nothing to add", "no additions", "なし", "特になし"}


def none_text(text):
    """A section's text, or "" when the agent wrote that there is nothing: `none`, `n/a`, `-`, also as the one item
    of a list (`- None.`, `- n/a`) and with a few words more (`Nothing blocking.`). The Readiness verdict counts what
    is left as findings, so a GO with `- None` under Blocking must not become a NO-GO."""
    items = list_items(text.strip())
    if len(items) > 1:
        return text.strip()
    return "" if not items or " ".join(finding_text(items[0]).strip(".*_`。 ").lower().split()) in NONE_WORDS \
        else text.strip()


class ReadinessResult:
    """The Goldfish's verdict on a Goal: GO, NO-GO, or blocked (a Goldfish edited files or wrote no result: why says
    which). Blocking and Minor are sorted as ReviewResult sorts Please fix and Known issues: a NO-GO with only minor
    findings is a GO, and a GO that still lists a blocking finding is a NO-GO."""
    def __init__(self, markdown="", blocked=""):
        self.markdown = markdown or ""
        # models decorate the word as they do a review's: **GO**, `NO-GO`, No go.
        said = re.sub(r"[\s_-]+", "-", (section(self.markdown, "Verdict").splitlines() or [""])[0].strip(" *`_.").upper())
        said = "NO-GO" if said == "NOGO" else said
        self.summary = none_text(section(self.markdown, "Summary"))
        self.blocking = list_items(none_text(section(self.markdown, "Blocking")))
        self.minor = list_items(none_text(section(self.markdown, "Minor")))
        self.additions = none_text(section(self.markdown, "Goal additions"))
        self.why = blocked
        if not blocked and said not in READINESS_VERDICTS:
            self.why = f"the readiness agent wrote no verdict GO or NO-GO (it wrote {said or 'none'})"
        if self.why:
            self.verdict = "blocked"
        elif said == "NO-GO" and not self.blocking and self.minor:  # nothing blocking: what it lists can wait
            self.verdict = "GO"
        elif said == "GO" and self.blocking:
            self.verdict = "NO-GO"
        else:
            self.verdict = said

    def comment(self, tid, hash_, about, comprehension=""):
        """The Issue comment: READINESS_MARK, then the two lines task-hub reads back (parse_readiness), then the rest."""
        parts = [f"{READINESS_MARK}\nVerdict: {self.verdict}\nGoal: {hash_}", "## Readiness", about]
        if self.why:
            return "\n\n".join(parts + [f"Blocked: {self.why}.", f"Fix that, then run `task check {tid}` again."])
        parts += [self.summary] * bool(self.summary)
        parts += ["### Blocking\n\n" + ("\n".join(self.blocking) or "none"),
                  "### Minor\n\n" + ("\n".join(self.minor) or "none")]
        if self.verdict == "NO-GO":
            parts += ["### Suggested Goal additions\n\n" + (self.additions or "none proposed"),
                      f"Add what the blocking findings need to the Goal, then run `task check {tid}` again. task-hub "
                      "does not move the card: whether it goes back to Backlog is yours to decide."]
        else:
            parts += ["This GO counts for the Goal as it is now: an edit of the Goal makes it stale."]
        if comprehension:
            parts += [f"<details><summary>Comprehension Check</summary>\n\n{clip_text(comprehension, 20000)}\n\n"
                      "</details>"]
        return clip_text("\n\n".join(parts), COMMENT_MAX)


COMMENT_MAX = 60000  # GitHub refuses a comment over 65,536 characters


def clip_text(text, limit):
    """text, cut to limit characters with a note when it is longer (its head, where the verdict is, stays)."""
    return text if len(text) <= limit else text[:limit] + "\n\n... (cut: too long for one comment)"


def parse_readiness(body):
    """{verdict, hash} from the head of a READINESS_MARK comment (above its first heading), or {}."""
    head = body.split("\n## ", 1)[0]
    verdict = re.search(r"(?m)^Verdict: (GO|NO-GO|blocked)[ \t]*$", head)
    hash_ = re.search(r"(?m)^Goal: ([0-9a-f]{16})[ \t]*$", head)
    return {"verdict": verdict[1], "hash": hash_[1]} if verdict and hash_ else {}


def latest_readiness(comments):
    """The verdict of the newest READINESS_MARK comment this account wrote, or {}: a comment anyone else wrote is no
    verdict, whatever it says, and a newest one that does not read is none (never the one before it)."""
    body = latest_readiness_comment(comments)
    return parse_readiness(body) if body else {}


def latest_readiness_comment(comments):
    """The newest READINESS_MARK comment this account wrote, or "" (latest_readiness)."""
    return next((c["body"] for c in reversed(comments)
                 if (c.get("body") or "").startswith(READINESS_MARK) and c.get("viewerDidAuthor") is True), "")


def readiness_mode():
    """[runner] readiness: off (the default), warn, or require."""
    mode = config()["runner"].get("readiness", "").strip().lower() or "off"
    if mode not in READINESS_MODES:
        fail(f"[runner] readiness must be off, warn or require; got {mode!r}",
             f"fix it in {home(CONFIG)} (see docs/task-format.md)")
    return mode


def readiness_cards():
    """READINESS's cards: {id: {read, research, verdict, hash}}, {} when it is another board's or unreadable."""
    data = read_json(READINESS)
    cards = data.get("cards")
    return cards if data.get("key") == list(board_config()) and isinstance(cards, dict) else {}


def note_readiness(tid, entry):
    with file_lock(STATE / "readiness.lock", wait=True):
        cards = readiness_cards()
        cards[tid] = entry
        write_cache(READINESS, json.dumps({"key": list(board_config()), "cards": cards}))


READINESS_WHY = {"NO-GO": "its Goal got NO-GO", "blocked": "its last check was blocked",
                 "stale": "its Goal changed since its last check", "none": "its Goal was never checked",
                 "unknown": "its readiness was not read on this machine yet"}


def readiness_of(t, entry):
    """What a card's readiness is for the gate: "GO" (given to its Goal as it is now), "research" (not gated),
    "NO-GO", "blocked", "stale" (the last verdict was given to an earlier Goal), "none" (never checked), or "unknown"
    (not read on this machine yet)."""
    if not entry:
        return "unknown"
    if entry.get("research"):
        return "research"
    if not entry.get("verdict"):
        return "none"
    return entry["verdict"] if entry.get("hash") == t["goal_hash"] else "stale"


def readiness_gate(board_, mode, repos=(), read=True, errors=None):
    """[runner] readiness on the board just read. Each Ready card's readiness goes into t["readiness"], and that of
    the Backlog cards of autopilot's repos: with require, a card without a GO for its current Goal then waits, the
    reason in its waits_for as a blocker's would be, so it is neither started nor moved to Ready.
    read: the Issue's comments and labels are read (one call) when the card's Goal or the card itself changed since
    the last read (`task`, `task watch`); False for the read-only `task list`, which shows what was last read.
    Off: nothing is read, and nothing changes. task-hub never moves a card for its readiness."""
    if mode == "off":
        return
    cards = readiness_cards()
    for t in board_:
        if t["status"] != READY and not (t["status"] == BACKLOG and (t.get("repo") or "").lower() in repos):
            continue
        key = f"{t['goal_hash']} {t.get('updated') or ''}"  # a field set by `task check` elsewhere moves updatedAt
        entry = cards.get(t["id"])
        if read and (not entry or entry.get("read") != key):
            try:
                i = issue(t)
            except RuntimeError as e:  # unknown until the next check reads it: never a GO meanwhile
                if errors is not None:
                    errors.append({"id": t["id"], "error": f"readiness: {e}"})
            else:
                entry = {"read": key, "research": i["research"], "verdict": i["readiness"].get("verdict", ""),
                         "hash": i["readiness"].get("hash", "")}
                note_readiness(t["id"], entry)
        t["readiness"] = readiness_of(t, entry)
        if mode == "require" and t["readiness"] not in ("GO", "research"):
            t["waits_for"] = ", ".join(filter(None, [t["waits_for"], f"readiness: {READINESS_WHY[t['readiness']]} "
                                                                     f"(`task check {t['id']}`)"]))


def set_readiness(t, verdict):
    """The card's Readiness field: GO or NO-GO, cleared for a blocked check."""
    set_select(t, "readiness", READINESS_FIELD, READINESS_VERDICTS, verdict)


def set_review(t, verdict):
    """The card's Review field: the verdict of its run's last automated review (pass, needs changes, blocked), cleared
    for a run without one. A Project without the field gets it with the first verdict; none to clear: no call."""
    if t.get("item") and (verdict or board().get("review")):
        set_select(t, "review", REVIEW_FIELD, REVIEW_VERDICTS, verdict)


def set_select(t, key, name, options, value):
    """The card's single-select field name (board()[key]): value, or cleared for one not in options. The field is
    made, with all options, when the Project has none; one of another type, or without the option, is the human's
    to fix."""
    b = board()
    if not b.get(key):
        gh("project", "field-create", b["number"], "--owner", b["owner"], "--name", name,
           "--data-type", "SINGLE_SELECT", "--single-select-options", ",".join(options))
        forget_board()
        b = board()
    field = b.get(key) or {}
    if field.get("type") != "SINGLE_SELECT":
        raise RuntimeError(f'the Project\'s "{name}" field is {field.get("type") or "missing"}, not a '
                           f"single select with the options {', '.join(options)}")
    if value in options:
        option = field["options"].get(value.lower())
        if not option:
            raise RuntimeError(f'the Project\'s "{name}" field has no option "{value}"; add it in the '
                               f"Project's settings ({b.get('url', '')})")
        value = ["--single-select-option-id", option]
    else:
        value = ["--clear"]
    try:
        gh("project", "item-edit", "--id", t["item"], "--project-id", b["id"], "--field-id", field["id"], *value)
    except RuntimeError:
        forget_board()
        raise


def checker(t):
    """The agent each Goldfish of `task check` runs: [runner] checker ("agent": the card's own), else the card's."""
    own = t.get("agent") or config()["runner"]["agent"]
    name = config()["runner"].get("checker", "").strip()
    name = own if name in ("", "agent") else name
    if not config().has_option("agents", name):
        raise RuntimeError(f'unknown agent "{name}" for `task check` ([runner] checker, or the card\'s Agent)')
    return name


def readiness_parts():
    """worker/READINESS.md as (rules, comprehension, {critic: its persona}, the critics' output format, readiness)."""
    rules, comprehension, critics, readiness = instruction_parts(WORKER_READINESS, 4)
    personas, _, output = critics.partition(f"\n## `{READINESS_FILE}`\n")
    named = dict((n.strip(), text.strip()) for n, text in re.findall(r"(?ms)^## ([^\n]+)\n(.*?)(?=^## |\Z)", personas))
    if not named:
        raise RuntimeError(f"{home(WORKER_READINESS)} names no critic (a `## ` heading in its third part)")
    return rules, comprehension, named, f"## `{READINESS_FILE}`\n{output}", readiness


GOLDFISH_TEXT = 12000 if WINDOWS else 40000  # what the readiness agent gets of each earlier Goldfish's file
# the critics' threads make and remove their worktrees of one clone in turn: a `git worktree add` reads the files of
# every worktree in .git/worktrees, and fails ("failed to read .../commondir") when another add or remove is halfway
# through writing or deleting them. Seen under load (-j 4 on CI's macOS); the Goldfish themselves still run at once
GOLDFISH_WORKTREES = threading.Lock()


def goldfish_prompt(rules, part, t, goal, extra=()):
    return "\n".join([rules, "", part, "", "# The task", "", f"Task {t['id']}: {t['title']}", f"Repository: {t['repo']}",
                      "", "## Goal", "", goal.strip(), *extra, ""])


def goldfish(agent, role, prompt, repo_dir, ref, t, say, usage):
    """One Goldfish, in a detached worktree of ref of its own, made for it and removed after: its role's own
    worktree tells its usage apart from the others' running at the same time. (its file's text, or None and why the
    check is blocked.) An edit is undone (restore) before the worktree goes."""
    wt = DATA / "worktrees" / f"{t['id']}-check-{re.sub(r'[^a-z0-9]+', '-', role.lower()).strip('-')}"
    with GOLDFISH_WORKTREES:
        if wt.exists():  # left by a check that was killed
            git_shared(repo_dir, "worktree", "remove", "--force", wt)
            shutil.rmtree(wt, ignore_errors=True)
        git_shared(repo_dir, "worktree", "prune")
        git_shared(repo_dir, "worktree", "add", "-q", "--detach", wt, ref, check=True)
    try:
        with GOLDFISH_WORKTREES:  # the clone's info/exclude, which all its worktrees share
            ensure_internal_excludes(wt)
        snap = snapshot(wt)
        code = run_agent_process(agent, prompt, wt, say, role, usage)
        if restore(wt, snap):
            return None, f"the {role} changed files; its edits were undone. A Goldfish must only read the code"
        text = agent_file(wt / READINESS_FILE)
        if not (text or "").strip():
            return None, f"the {role} exited {code} without writing {READINESS_FILE}"
        return text, ""
    finally:
        with GOLDFISH_WORKTREES:
            git_shared(repo_dir, "worktree", "remove", "--force", wt)


def at_once(jobs):
    """Run each job (a no-argument function) in a thread of its own and wait for all: their results, in order.
    Ctrl-C reaches only this thread: it stops every Goldfish still running (HELPERS), then goes on as Ctrl-C."""
    results = [None] * len(jobs)

    def work(n, job):
        try:
            results[n] = job()
        except Exception as e:  # a git or agent failure of one Goldfish blocks the check, with why
            results[n] = (None, f"{type(e).__name__}: {e}")
    threads = [threading.Thread(target=work, args=(n, job), daemon=True) for n, job in enumerate(jobs)]
    for th in threads:
        th.start()
    try:
        while any(th.is_alive() for th in threads):
            for th in threads:
                th.join(0.2)
    except KeyboardInterrupt:
        with HELPERS_LOCK:
            procs = list(HELPERS)
        for proc in procs:
            stop_agent(proc)
        for th in threads:
            th.join(AGENT_STOP_SECONDS)
        raise
    return results


def readiness_check(t, goal, agent, repo_dir, ref, say, usage):
    """The three stages of `task check`, each by Goldfish in fresh contexts: the Comprehension Check, then every
    critic of worker/READINESS.md at once, then Implementation Readiness. (ReadinessResult, the Comprehension Check's
    text.) A stage that is blocked ends the check there: its verdict is blocked."""
    rules, comprehension, critics, critic_output, readiness = readiness_parts()
    probe = {"id": t["id"], "title": t["title"], "repo": t["repo"], "agent": agent}  # over_budget's; never saved

    def stage(jobs):
        found = at_once(jobs)
        over_budget(probe, usage, say, save=False, what="task check: ")
        return found
    say("== stage 1: Comprehension Check")
    (understood, why), = stage([lambda: goldfish(agent, "comprehension", goldfish_prompt(rules, comprehension, t, goal),
                                                 repo_dir, ref, t, say, usage)])
    if why:
        return ReadinessResult(blocked=why), ""
    say(f"== stage 2: adversarial review by {', '.join(critics)}, at once")
    found = stage([lambda name=name, persona=persona: goldfish(
        agent, name, goldfish_prompt(rules, f"# Adversarial review: {name}\n\n{persona}\n\n{critic_output}", t, goal),
        repo_dir, ref, t, say, usage) for name, persona in critics.items()])
    blocked = [why for _, why in found if why]
    if blocked:
        return ReadinessResult(blocked="; ".join(blocked)), understood.strip()
    clipped = lambda text: text.strip() if len(text) <= GOLDFISH_TEXT else text[:GOLDFISH_TEXT] + "\n... (cut)"
    extra = ["", "# Comprehension Check", "", clipped(understood)]
    for name, (text, _) in zip(critics, found):
        extra += ["", f"# Critic: {name}", "", clipped(text)]
    say("== stage 3: Implementation Readiness")
    (text, why), = stage([lambda: goldfish(agent, "readiness", goldfish_prompt(rules, readiness, t, goal, extra),
                                           repo_dir, ref, t, say, usage)])
    return (ReadinessResult(blocked=why) if why else ReadinessResult(text)), understood.strip()


def cmd_check(a):
    """`task check <id>`: Goldfish read only the card's Goal and its repository's base branch, and say GO or NO-GO.
    The verdict goes on the Issue (READINESS_MARK) and in the Project's Readiness field; --no-write prints it and
    writes nothing (any card: past cards for a trial, with --ref at the commit before their change)."""
    t = get(a["id"])
    write = not a["no_write"]
    if (a["goal_file"] or a["ref"]) and write:  # a verdict on the Issue is for its Goal at the base branch only
        fail("--ref and --goal-file are for trials: they go with --no-write only")
    if write and t["status"] not in (BACKLOG, READY):
        fail(f"task {t['id']} is {t['status']}; `task check` judges Backlog and Ready cards",
             f"`task check {t['id']} --no-write` prints a verdict on any card and writes nothing")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", t.get("repo") or ""):
        fail('the card has no valid "Target repo" (owner/name)')
    if t.get("base") and check_base(t["base"]):
        fail(check_base(t["base"]))
    readiness_mode()  # a bad config stops before any credit is spent
    agent = checker(t)
    check_sandbox()
    check_ready(agent)
    i = issue(t)
    if a["goal_file"]:  # a trial: the Goal as it was before an earlier run (the Issue's edit history)
        try:
            i["body"] = read_agent_file(Path(a["goal_file"]))
        except OSError as e:
            fail(f"cannot read --goal-file {a['goal_file']}: {e.strerror or e}", code=2)
    if not i["body"].strip():
        fail(f"task {t['id']} has no Goal to check", "write the Goal in the Issue body first")
    repo_dir = ensure_clone(t["repo"])
    ref = a["ref"] or base_ref(t, repo_dir)
    commit = git_shared(repo_dir, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}").stdout.strip()
    if not commit:
        fail(f"{ref} is not in {t['repo']}", "push the Base branch, or give --ref a commit or branch of the repo")
    LOGS.mkdir(parents=True, exist_ok=True)
    log, lock = LOGS / f"{t['id']}-check.log", threading.Lock()

    def say(line):  # the whole of it in the log; the stages and what they come to here too
        with lock, log.open("a") as f:
            f.write(line + "\n")
            if line.startswith("== "):
                print(line, file=sys.stderr, flush=True)
    for s in INTERRUPTS:  # a closed pane or kill stops the Goldfish too, as Ctrl-C does
        signal.signal(s, signal.default_int_handler)
    began, usage = time.time(), []
    with file_lock(RUNS / f"{t['id']}.check.lock") as mine:
        if not mine:
            fail(f"another `task check {t['id']}` is running")
        say(f"== task check {t['id']}: {t['title']} | {t['repo']} at {ref} ({commit[:12]}) | agent {agent} | {now()}")
        try:
            result, understood = readiness_check(t, i["body"], agent, repo_dir, ref, say, usage)
        finally:  # stopped (Ctrl-C), a Goldfish's thread may not have removed its worktree yet
            for wt in DATA.joinpath("worktrees").glob(f"{t['id']}-check-*"):
                git_shared(repo_dir, "worktree", "remove", "--force", wt)
    used = run_used(usage)
    spent = ", ".join([span(round(time.time() - began))] +  # the wall clock: the critics run at once
                      [budget_text(k, used[k]) for k in ("tokens", "cost", "credits") if k in used])
    hash_ = goal_hash(i["body"])
    about = (f"Checked {now()} by {plural(len(usage), 'Goldfish', 'Goldfish')} ({agent}) that read only this Goal and "
             f"{t['repo']} at " + (commit[:12] if commit.startswith(ref) else f"{ref.removeprefix('origin/')} "
                                   f"({commit[:12]})") + f": {spent}.")
    body = result.comment(t["id"], hash_, about, understood)
    append_jsonl(CHECKS, {"id": t["id"], "title": t["title"], "repo": t["repo"], "agent": agent, "ref": ref,
                          "commit": commit, "goal": hash_, "started": datetime.datetime.fromtimestamp(
                              began, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "finished": now(),
                          "seconds": round(time.time() - began), "verdict": result.verdict,
                          "blocking": len(result.blocking), "minor": len(result.minor), "written": write,
                          "usage": usage}, say)
    say(f"== verdict: {result.verdict}")
    if write:
        comment(t, body)
        # before the field: when setting it fails, the gate must not go on with the verdict this comment replaced
        note_readiness(t["id"], {"read": "", "research": i["research"], "verdict": result.verdict, "hash": hash_})
        set_readiness(t, result.verdict)
        emit(t, "readiness", decision=result.verdict, reason=clip(result.why or result.summary, DIGEST_TEXT))
    out("check:", f"  id: {t['id']}", f"  verdict: {result.verdict}", f"  goal: {hash_}",
        f"  blocking: {len(result.blocking)}", f"  minor: {len(result.minor)}", f"  used: {q(spent)}",
        f"  log: {home(log)}", *([f"  why: {q(result.why)}"] if result.why else []),
        f"  written: {'comment on the Issue, Readiness field' if write else 'nothing (--no-write)'}",
        *(["comment:", body] if not write else []),
        "help[1]:", "  " + ("NO-GO: add what the blocking findings need to the Goal, then check again; moving the card "
                            "is yours to decide" if result.verdict == "NO-GO" else
                            "GO: it counts for the Goal as it is now; an edit of the Goal makes it stale"
                            if result.verdict == "GO" else "blocked: fix the cause, then check again"))


def cmd_review(a):
    """`task review <id> --no-write --ref <commit>`: a trial of the automated review on a card's code at a commit (a
    past PR's), in [runner] review_mode or --mode, as a run would review it: prints the verdict and what it used, and
    writes nothing to GitHub. For comparing the modes on past cards (docs/lessons.md)."""
    usage_ = f"usage: {COMMANDS['review'][3].split('  #')[0]}"
    if not a["no_write"] or not a["ref"]:
        fail("`task review` is a trial only: give --no-write and --ref (a run reviews its own work)", usage_, 2)
    if a["mode"] and a["mode"] not in REVIEW_MODES:
        fail(f"--mode must be agent or goldfish; got {a['mode']!r}", usage_, 2)
    t = get(a["id"])
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", t.get("repo") or ""):
        fail('the card has no valid "Target repo" (owner/name)')
    try:
        mode = a["mode"] or review_mode()
    except RuntimeError as e:
        fail(str(e))
    if mode == "agent" and not a["report_file"]:
        fail("--mode agent gives the reviewer the agent's report: give it with --report-file", usage_, 2)
    t = {**t, "agent": t.get("agent") or config()["runner"]["agent"], "branch": f"task/{t['id']}"}
    reviewer = helper_agent(t, "reviewer")
    if not reviewer or not config().has_option("agents", reviewer):
        fail(f'no reviewer: [runner] reviewer is {config()["runner"].get("reviewer", "") or "empty"}',
             f"set it in {home(CONFIG)} (agent: the card's own agent)")
    check_sandbox()
    check_ready(reviewer)
    i = issue(t)
    texts = {}
    for key in ("goal_file", "report_file"):
        try:
            texts[key] = read_agent_file(Path(a[key])) if a[key] else ""
        except OSError as e:
            fail(f"cannot read --{key.replace('_', '-')} {a[key]}: {e.strerror or e}", code=2)
    goal = texts["goal_file"] or i["body"]
    repo_dir = ensure_clone(t["repo"])
    commit = git_shared(repo_dir, "rev-parse", "--verify", "-q", f"{a['ref']}^{{commit}}").stdout.strip()
    base = a["base"] or git_shared(repo_dir, "merge-base", base_ref(t, repo_dir), commit or "HEAD").stdout.strip()
    base = git_shared(repo_dir, "rev-parse", "--verify", "-q", f"{base}^{{commit}}").stdout.strip() if base else ""
    if not commit or not base:
        fail(f"{a['ref'] if not commit else a['base']} is not in {t['repo']}",
             "give --ref (and --base) a commit or branch of the repo")
    diff = git_shared(repo_dir, "diff", base, commit, "--").stdout
    if not diff.strip():
        fail(f"no change between {base[:12]} and {commit[:12]}")
    LOGS.mkdir(parents=True, exist_ok=True)
    log, wt = LOGS / f"{t['id']}-review-trial.log", DATA / "worktrees" / f"{t['id']}-review-trial"

    def say(line):
        with log.open("a") as f:
            f.write(line + "\n")
        if line.startswith("== "):
            print(line, file=sys.stderr, flush=True)

    def launch(prompt, label):
        shared_unlink(wt / REVIEW_FILE)
        snap = snapshot(wt)
        code = run_agent_process(reviewer, prompt, wt, say, label, usage)
        return review_result(label, code, restore(wt, snap), agent_file(wt / REVIEW_FILE))
    for s in INTERRUPTS:  # a closed pane or kill stops the reviewer too, as Ctrl-C does
        signal.signal(s, signal.default_int_handler)
    began, usage = time.time(), []
    with file_lock(RUNS / f"{t['id']}.review-trial.lock") as mine:
        if not mine:
            fail(f"another `task review {t['id']}` is running")
        if wt.exists():  # left by a trial that was killed
            git_shared(repo_dir, "worktree", "remove", "--force", wt)
            shutil.rmtree(wt, ignore_errors=True)
        git_shared(repo_dir, "worktree", "prune")
        git_shared(repo_dir, "worktree", "add", "-q", "--detach", wt, commit, check=True)
        say(f"== task review {t['id']}: {t['title']} | {t['repo']} {base[:12]}..{commit[:12]} | {mode} | "
            f"reviewer {reviewer} | {now()}")
        try:
            ensure_internal_excludes(wt)
            result = review_by(mode, launch, t, goal, texts["report_file"], diff,
                               readiness=i.get("readiness_comment", ""), say=say)
        finally:
            git_shared(repo_dir, "worktree", "remove", "--force", wt)
    used = run_used(usage)
    spent = ", ".join([span(round(time.time() - began))] +
                      [budget_text(k, used[k]) for k in ("tokens", "cost", "credits") if k in used])
    blocking, minor = len(result.findings) if result.fix else 0, len(list_items(result.minor))
    append_jsonl(REVIEW_TRIALS, {"id": t["id"], "title": t["title"], "repo": t["repo"], "reviewer": reviewer,
                                 "mode": mode, "base": base, "commit": commit, "finished": now(),
                                 "seconds": round(time.time() - began), "verdict": result.field_verdict,
                                 "blocking": blocking, "minor": minor, "usage": usage}, say)
    say(f"== verdict: {result.verdict or 'missing'}")
    out("review:", f"  id: {t['id']}", f"  mode: {mode}", f"  verdict: {result.field_verdict}",
        f"  blocking: {blocking}", f"  minor: {minor}", f"  used: {q(spent)}", f"  log: {home(log)}",
        "  written: nothing (--no-write)", "comment:", result.issue_section())


# ---------- one run (called in the herdr pane or background process) ----------

INTERRUPTS = [s for s in (getattr(signal, "SIGHUP", None), signal.SIGTERM) if s]  # Windows has no SIGHUP


def cmd_run(a):
    t = {"id": a["id"], **load_run(a["id"])}
    t["pid"] = str(os.getpid())
    save_run(t)
    log = None if os.environ.get("TASK_RUN_LOGGED") else open(t["log"], "a")

    def say(line):
        with contextlib.suppress(OSError):  # its pane is gone (SIGHUP): the log goes on
            print(line, flush=True)
        if log:
            log.write(line + "\n")
            log.flush()

    def stopped(name):
        t["interrupted"] = name
        save_run(t)
        # straight to the files, not through say: in the signal handler, print or log.write may be the very call
        # the signal cut into, and writing to its buffer again raises "reentrant call" instead of ending the run
        line = f"== stopped with Ctrl-C during {t['stage']}; the next check of the board blocks it\n" \
            if name == "SIGINT" else f"== stopped by {name} during {t['stage']}; the next check of the board takes it from there\n"
        for fd in (1, *([log.fileno()] if log else [])):
            with contextlib.suppress(OSError):  # its pane is gone (SIGHUP): the log goes on
                os.write(fd, line.encode())
        os._exit(128 + signal.Signals[name])

    def interrupted(signum, _frame):
        if not t.get("stage"):  # the run is over (its tab closing ends it): nothing was cut short
            os._exit(128 + signum)
        for s in (*INTERRUPTS, signal.SIGINT):  # once: stopping the agent must not be cut short
            signal.signal(s, signal.SIG_IGN)
        if t.get("agent_running"):
            raise Interrupted(signal.Signals(signum).name)
        # in git or a GitHub call: end at once, as without this handler, and never kill a git that is writing
        stopped(signal.Signals(signum).name)

    for s in INTERRUPTS:
        signal.signal(s, interrupted)
    try:
        run_task(t, say)
    except Interrupted as e:
        stopped(e.args[0])
    except KeyboardInterrupt:  # Ctrl-C outside the agent (agent_process has its own): never resumed
        if t.get("stage"):
            stopped("SIGINT")
        raise


def run_task(t, say):
    """The run of cmd_run, from the setup to the card's new Status; a resumed one (relaunch), from its stage."""
    wt = Path(t["worktree"])
    if sandbox_mode() != "off":
        os.chdir(DATA)  # nothing of task-hub's own (gh, herdr) runs in the folder the agent writes
    stage, why = t.get("resume_stage") or "", t.get("interrupted") or "the run process is gone"
    if stage:  # read once: whatever starts `_run` again next must say so again
        t["resume_stage"] = ""
        save_run(t)
    for name in (REPORT_FILE, REVIEW_FILE, REPLAN_FILE):
        if not (name == REPORT_FILE and stage in ("review", "finishing")):  # there, the report is the agent's
            shared_unlink(wt / name)
    if stage in ("review", "finishing"):
        unhide_report(t)  # a run cut short while a Goldfish auditor ran had moved it out
    else:
        held_report_file(t).unlink(missing_ok=True)
    say(f"== task {t['id']}: {t['title']} | agent {t['agent']} | {now()}")
    if sandbox_mode() != "off":
        say(f"== sandbox: user {sandbox_user()} (the agent and git run as that user, see docs/sandbox.md)")
    if stage:
        say(f"== resumed at {stage}, once: it was cut short there ({why})")
    began = time.time()
    record = {"id": t["id"], "title": t["title"], "repo": t["repo"], "agent": t["agent"],
              "reviewer": helper_agent(t, "reviewer"), "started": now(), "reviews": [], "retried": False,
              "retries": 0, "review_stop": "", "review_mode": "", "review_verdict": "", "blocked_by": "", "replan": "",
              "usage": []}
    if stage in ("", "preparing", "setup"):  # from the start: [setup] gives the same result each time it runs
        stage = ""
        stop, by = run_setup(t, wt, say), "setup"
        if not stop:  # after [setup]: a check may use what it installs
            stop, by = check_balance(t, wt, say), "balance"
        # the agent never starts: nothing of this run can be trusted without its environment, and a paid API without
        # balance only fails halfway through (a 429), after the agent spent its own tokens
        if stop:
            say(f"== {stop}")
            try:
                take_card(t)
                report_comment(t, blocked=stop)
                set_status(t, BLOCKED, reason=stop)
            except RuntimeError as e:
                say(f"== could not report it: {e}")
            set_stage(t, "")
            record_run({**record, **resume_record(t), "finished": now(), "seconds": round(time.time() - began),
                        "status": BLOCKED, "blocked_by": by}, say)
            say(f"== task {t['id']} is now {BLOCKED}. This pane stays open; `task done {t['id']}` closes it.")
            return
        t["head"] = git_shared(wt, "rev-parse", "HEAD").stdout.strip()
        set_stage(t, "agent")
    if stage in ("", "agent"):
        code = run_worker(t, prompt_file(t).read_text(), "agent", "agent", say, record, why if stage else "")
        say(f"== agent exited with code {code}")
    else:  # the agent's exit code is gone with the run that was cut short: its report is what counts
        code = 0
        if stage == "review" and t.get("snap"):  # the reviewer may have changed the worktree before it was cut short
            if release_snapshot(t, t["snap"].split()):
                say("== the reviewer had changed files; its edits were undone")
    report = agent_file(wt / REPORT_FILE) or ""
    review, review_blocked = "", ""
    try:
        if stage == "finishing":  # what review_loop gave the run that was cut short
            kept = json.loads(finish_file(t).read_text())
            code, review, review_blocked = kept["code"], kept["review"], kept["blocked"]
            record["review_verdict"] = kept.get("verdict") or ""
        else:
            resume_at = stage if stage in ("review", "retry") else ""
            report, code, review, review_blocked = review_loop(t, report, code, say, record, resume_at, why)
            if not review:  # a review cut short by the agent's own Blocked, or none: no verdict for the field
                record["review_verdict"] = ""
            write_atomic(finish_file(t), json.dumps({"code": code, "review": review, "blocked": review_blocked,
                                                     "verdict": record["review_verdict"]}))
        set_stage(t, "finishing")
        take_card(t)
        status = finish(t, report, code, say, auto_review=review, blocked_override=review_blocked,
                        again=stage == "finishing", review_verdict=record["review_verdict"])
        record.update(pr_size(t, wt))
        shared_unlink(wt / REPORT_FILE)  # only once it is safely on GitHub
        if status == BLOCKED:
            record["blocked_by"] = ("no report" if not report.strip() else "review" if review_blocked
                                    else "agent" if AgentReport(report).blocked else "no changes")
        if status == BLOCKED and not review_blocked:  # the agent's own Blocked, not one task-hub gave
            try:
                record["replan"] = run_replan(t, report, say, record["usage"])
            except RuntimeError as e:  # the run itself is already on GitHub
                record["replan"] = "failed"
                say(f"== replanner failed: {e}")
    except RuntimeError as e:
        status = BLOCKED
        record["blocked_by"] = "finish error"
        say(f"== could not finish: {e}")
        try:
            report_comment(t, blocked=f"task-hub could not finish the run: {str(e)[:300]}", report=report.strip())
            shared_unlink(wt / REPORT_FILE)
            set_status(t, BLOCKED, reason=f"task-hub could not finish the run: {str(e)[:300]}")
        except RuntimeError:  # GitHub unreachable too: the next sync sees the dead run and blocks the card
            say(f"== the agent's report is kept in {home(wt / REPORT_FILE)}")
    set_stage(t, "")  # the pid stays: once this process is gone, `alive` knows the run has ended
    record_run({**record, **resume_record(t), "finished": now(), "seconds": round(time.time() - began),
                "status": status}, say)
    if status == IN_REVIEW and (t.get("tab") or t.get("workspace")):  # nothing more to see here: `task log` keeps it
        say(f"== task {t['id']} is now {status}. Closing this tab; `task log {t['id']}` has the output.")
        closing = dict(t)
        t["tab"] = t["workspace"] = ""
        save_run(t)  # forget the ids first: herdr may give them to someone else's tab later
        close_herdr(closing)  # this process ends with its tab
        return
    say(f"== task {t['id']} is now {status}. This pane stays open; `task done {t['id']}` closes it.")


def resume_record(t):
    """The run's resumes, for METRICS: the stages it was resumed at, and why it was last cut short. A resumed run's
    record has only the reviews and usage since it was resumed: the rest was in the memory of the one cut short."""
    return {"resumed": (t.get("resumed") or "").split(), "interrupted": t.get("interrupted") or ""}


def take_card(t):
    """The card's item and Status, from the one board read the run makes anyway: the run file has neither."""
    item = next((x for x in tasks() if x["id"] == t["id"]), None)
    t["item"] = item["item"] if item else ""
    if item:
        t["status"] = item["status"]


def finish(t, report, code, say, auto_review="", blocked_override="", again=False, review_verdict=""):
    """Commit and push the agent's work, open or update the PR, report on the Issue, move the card.
    again: the run was cut short in finish and resumed. All of it gives the same result once more, but the report:
    it is not written again when the Issue's last report is the same (but for the line on the resume).
    review_verdict: the run's last automated review for the Review field (set_review; "": none, cleared)."""
    parsed = AgentReport(report, auto_review=auto_review)
    wt = t["worktree"]
    git_shared(wt, "add", "-A", check=True)
    if git_shared(wt, "diff", "--cached", "--quiet").returncode != 0:
        git_shared(wt, "commit", "-q", "-m", f"task {t['id']}: {t['title']}", check=True)
    base = base_ref(t, wt)
    ahead = git_shared(wt, "rev-list", "--count", f"{base}..HEAD").stdout.strip() not in ("", "0")
    if ahead and sandbox_mode() != "off":
        # the agent's user pushes with its own GitHub sign-in; what reached GitHub is then read from GitHub, never
        # from the git the agent could have set up (decision 28)
        git_shared(wt, "push", "-q", "-u", "origin", f"HEAD:{t['branch']}", check=True)
        ahead = (branch_compare(t, base) or {}).get("ahead_by", 0) > 0

    # the Watchdog stopped the last agent, after its one resume (run_worker); `interrupted` stays "silent" after a
    # resume, so it would also name a resumed agent that ended on its own
    if not report.strip() and t.get("agent_silenced"):
        # how long it was silent is in the log: a descendant may have used CPU for a while before it hung
        parsed.blocked = f"the watchdog stopped the agent: no output and no CPU used, see `task log {t['id']}`"
    elif not report.strip():
        parsed.blocked = f"agent exited without a report (exit {code}), see `task log {t['id']}`"
    elif blocked_override:
        parsed.blocked = blocked_override
    elif not parsed.blocked and not ahead and not t.get("research"):  # a research task's report is its result
        parsed.blocked = "agent wrote a report but changed no files"
    head = ""
    if ahead:
        if sandbox_mode() == "off":
            git_shared(wt, "push", "-q", "-u", "origin", f"HEAD:{t['branch']}", check=True)
        head = git_shared(wt, "rev-parse", "HEAD").stdout.strip()
        t["pr"] = upsert_pr(t, parsed.pr_body(t), bool(parsed.blocked), base.split("/", 1)[-1])
        say(f"== PR: {t['pr']}")
    body = parsed.issue_comment(t.get("pr", "") if ahead else "", resumed_line(t))
    if again and re.sub(RESUMED_LINE, "", issue(t)["report"]) == re.sub(RESUMED_LINE, "", body):
        say("== the report is on the Issue already")
    else:
        comment(t, body)
    status = BLOCKED if parsed.blocked else IN_REVIEW
    try:  # before the Status: the card must never move with the verdict of an earlier review on it
        set_review(t, review_verdict)
    except RuntimeError as e:  # the verdict is in the report anyway: the field must never cost the run
        say(f"== could not set the Project's {REVIEW_FIELD} field: {e}")
    set_status(t, status, reason=parsed.blocked, digest_=digest(report=body), sha=head if status == IN_REVIEW else "")
    return status


def upsert_pr(t, body, draft, base):
    pr = find_pr(t)
    body_file = DATA / f"pr-body-{t['id']}.md"
    body_file.write_text(body)
    if pr is None or pr["state"] != "OPEN":
        out_ = gh("pr", "create", "--repo", t["repo"], "--head", t["branch"], "--base", base,
                  "--title", t["title"], "--body-file", body_file, *(["--draft"] if draft else []))
        url = out_.strip().splitlines()[-1]
    else:
        url = pr["url"]
        gh("pr", "edit", url, "--body-file", body_file)
        if pr["isDraft"] != draft:
            gh("pr", "ready", url, *(["--undo"] if draft else []))
    body_file.unlink(missing_ok=True)
    return url


def pr_merged(t):
    """Whether the task's PR was merged, and the PR as REST gives it (None when it was found by its branch): the merge
    queue reads whether it conflicts from the same call. REST, not GraphQL: the watch asks every minute, and GraphQL
    has the tighter hourly limit. Without this machine's run file (the task ran elsewhere), the PR is
    found by its branch, as is a PR this machine's run did not open (made by hand after a run without changes).
    Only the newest PR of that branch counts, only if it closes this task's Issue, and not if it was merged before
    this machine's last run started: an older merged PR of a reused branch name never closes a card worked on again."""
    m = re.fullmatch(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", t.get("pr") or "")
    if m:
        pull = gh_json("api", f"repos/{m[1]}/pulls/{m[2]}")
        return pull.get("merged") is True, pull
    owner = t["repo"].split("/")[0]
    prs = gh_json("api", f"repos/{t['repo']}/pulls?head={owner}:task/{t['id']}&state=all&sort=created"
                         "&direction=desc&per_page=1")
    if not prs or not prs[0].get("merged_at") or prs[0]["merged_at"] < (load_run(t["id"]).get("started") or ""):
        return False, None
    return bool(re.search(rf"(?i)\bcloses {re.escape(board()['issues'])}#{t['id']}\b", prs[0].get("body") or "")), None


def find_pr(t):
    prs = gh_json("pr", "list", "--repo", t["repo"], "--head", t["branch"], "--state", "all",
                  "--limit", "1", "--json", "url,state,isDraft")
    return prs[0] if prs else None


def cleanup(t):
    """Close this task's herdr tab or workspace, remove its worktree and its local branch (only ones task-hub made).

    The branch on GitHub stays: it is the PR's. The local one would only pile up in task-hub's clone.
    Returns "" when done, else what is left: the run record then stays, so the next check tries again.
    """
    t = {**t, **load_run(t["id"])}  # remove the saved run's resources, even if the card's settings changed
    close_herdr(t)
    with contextlib.suppress(RuntimeError):  # what a cut-short agent left running must not write on in its worktree
        stop_left_commands(t, lambda _line: None)
    if sandbox_mode() == "off":
        try:
            refuse_after_user()
        except RuntimeError as e:  # left for the human to delete, as the message says
            return str(e)
    wt = Path(t.get("worktree") or "")
    repo = clone_dir(t["repo"]) if t.get("repo") else None
    if t.get("worktree") and (DATA / "worktrees") in wt.parents and wt.exists():
        git_shared(repo, "worktree", "remove", "--force", wt)
        if wt.exists():  # a failed removal unregisters it but leaves the folder, which git then refuses to touch
            if sandbox_mode() == "off":
                shutil.rmtree(wt, ignore_errors=True)
            else:  # the agent's user made what is in it
                run(*as_agent(["rm", "-rf", "--", wt]))
            git_shared(repo, "worktree", "prune")
    if wt.exists() and (DATA / "worktrees") in wt.parents:
        return f"worktree {home(wt)} could not be removed"
    if repo and t.get("branch") == f"task/{t['id']}" and (repo / ".git").exists():
        git_shared(repo, "branch", "-D", t["branch"])
        if git_shared(repo, "rev-parse", "--verify", "-q", f"refs/heads/{t['branch']}").returncode == 0:
            return f"branch {t['branch']} could not be deleted"
    (ASKED / f"{t['id']}.json").unlink(missing_ok=True)
    shutil.rmtree(commands_dir(t), ignore_errors=True)
    (RUNS / f"{t['id']}.json").unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        (RUNS / f"{t['id']}.lock").unlink(missing_ok=True)
    return ""


# ---------- sharing: a task's copy on a team's board ----------

def share_config(repo):
    """[share] for one place to share to: its team Project, the title prefix, the single-select fields to set, and
    the Status table (`status.<column>`, for every place; `<repo>.status.<column>`, for this one). Names are matched
    without regard to case, as configparser lowers them."""
    s, key = config()["share"], repo.lower()
    project = s.get(key, "").strip()
    if project and not re.fullmatch(r"[\w.-]+/\d+", project):
        raise RuntimeError(f"[share] {repo} must be a Project as <owner>/<number>, got {project!r}")
    prefix = s.get(f"{key}.title", "")
    if len(prefix) >= 2 and prefix[0] == prefix[-1] == '"':  # quoted: a space at its end stays
        prefix = prefix[1:-1]
    named = lambda start: {k[len(start):]: v.strip() for k, v in s.items() if k.startswith(start) and k != start}
    return {"project": project, "title": prefix, "fields": named(f"{key}.field."),
            "status": {**named("status."), **named(f"{key}.status.")}}


def share_body(goal):
    """The team's Issue body: the notice that task-hub overwrites it, then the Goal as it is."""
    return f"{SHARED_MARK}\n{SHARE_NOTICE}\n\n{goal.strip()}\n"


def share_column(status, settings, columns, project):
    """The team's column (an option of columns, by lowered name) for a personal Status: [share], then a column of the
    same name, then SHARE_STATUS; None when the team has none of them. One that [share] names but the team lacks raises."""
    wanted = settings["status"].get(status.lower())
    if wanted and wanted.lower() not in columns:
        raise RuntimeError(f'the team\'s Project {project} has no column "{wanted}" (status.{status})')
    return columns.get((wanted or status).lower()) or columns.get(SHARE_STATUS.get(status, "").lower())


class TeamGitHub:
    """The connector for a team's GitHub: an Issue in its repo, and a card on its Project. Another kind of place to
    share to (Jira, ...) is another connector with the same methods; `task share` and `set_status` stay as they are.
    (docs/architecture/designs/team-sync.md)"""

    def __init__(self, repo, project=""):
        self.repo, self.project, self.card = repo, project, None

    def ref(self, number):
        return f"{self.repo}#{number}"

    def prepare(self, status, settings):
        """Read the team's Project and work out the card's values before anything is written: a column, a field or a
        value it does not have stops the share with nothing made. Returns the team's column for status, or ""."""
        if not self.project:
            return ""
        owner, number = self.project.split("/")
        where = f"[share] in {home(CONFIG)}"
        try:
            project = (graphql(PROJECT_QUERY, owner=owner, number=int(number))["repositoryOwner"] or {}).get("projectV2")
            if not project:
                raise RuntimeError(f"no user or organization {owner}")
        except RuntimeError as e:
            fail(f"cannot read the team's Project {self.project}: {e}",
                 f"run `gh auth refresh -s project`, and check --project or {where}")
        by_name = {f["name"].lower(): f for f in project["fields"]["nodes"] if f}
        options = lambda f: {o["name"].lower(): o for o in f.get("options") or []}
        values, column = [], ""
        if "status" in by_name:
            columns = options(by_name["status"])
            try:
                found = share_column(status, settings, columns, self.project)
            except RuntimeError as e:
                fail(str(e), f"columns: {', '.join(o['name'] for o in columns.values())}; fix {where}")
            if found:
                values.append((by_name["status"]["id"], found["id"]))
                column = found["name"]
        for name, value in settings["fields"].items():
            field = by_name.get(name)
            if not field or field.get("dataType") != "SINGLE_SELECT":
                fail(f'the team\'s Project {self.project} has no single-select field "{name}"', f"fix {where}")
            if value.lower() not in options(field):
                fail(f'the field "{field["name"]}" of the team\'s Project {self.project} has no option "{value}"',
                     f"options: {', '.join(o['name'] for o in options(field).values())}; fix {where}")
            values.append((field["id"], options(field)[value.lower()]["id"]))
        self.card = {"id": project["id"], "owner": owner, "number": number, "values": values}
        return column

    def create_issue(self, title, body):
        """The team's Issue, assigned to you. Returns its number and url."""
        f = DATA / "share-issue.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
        try:
            url = gh("issue", "create", "--repo", self.repo, "--title", title, "--body-file", f,
                     "--assignee", "@me").strip().splitlines()[-1]
        finally:
            f.unlink(missing_ok=True)
        return url.rstrip("/").rsplit("/", 1)[-1], url

    def body_file(self, kind, number, text):
        f = DATA / f"share-{kind}-{self.repo.replace('/', '-')}-{number}.md"  # two runs may write at once
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        return f

    def comment(self, number, body):
        f = self.body_file("comment", number, body)
        try:
            gh("issue", "comment", number, "--repo", self.repo, "--body-file", f)
        finally:
            f.unlink(missing_ok=True)

    def edit(self, number, title, body):
        """Write the title and body again: task-hub's copy, whatever the team changed in it (its notice says so)."""
        f = self.body_file("body", number, body)
        try:
            gh("issue", "edit", number, "--repo", self.repo, "--title", title, "--body-file", f)
        finally:
            f.unlink(missing_ok=True)

    def close(self, number):
        gh("issue", "close", number, "--repo", self.repo)

    def move(self, number, status, settings):
        """Put the Issue's card on the team's Project in the column for status. One read finds the card, the Project's
        columns, and the card's column now: the mutation only when the column changes. Returns the column, or "" when
        the Issue has no card or the Project no column for it."""
        owner, name = self.repo.split("/")
        items = ((graphql(TEAM_CARD_QUERY, owner=owner, name=name, number=int(number))["repository"] or {})
                 .get("issue") or {}).get("projectItems", {}).get("nodes") or []
        items = [x for x in items if x and x.get("project")]
        project = self.project or settings["project"]  # the saved choice, then [share]; legacy links may name none
        at = f"/{project.split('/')[0]}/projects/{project.split('/')[-1]}".lower() if project else ""
        item = next((x for x in items if x["project"].get("url", "").lower().endswith(at)), None) if at else \
            (items[0] if items else None)
        if not item:
            return ""
        field = next((f for f in item["project"]["fields"]["nodes"] if f and f.get("name", "").lower() == "status"),
                     None)
        if not field:
            return ""
        found = share_column(status, settings, {o["name"].lower(): o for o in field.get("options") or []},
                             item["project"].get("url", project))
        if not found:
            return ""
        now_ = next((v.get("name") for v in item["fieldValues"]["nodes"]
                     if v and (v.get("field") or {}).get("id") == field["id"]), None)
        if now_ != found["name"]:
            gh("project", "item-edit", "--id", item["id"], "--project-id", item["project"]["id"],
               "--field-id", field["id"], "--single-select-option-id", found["id"])
        return found["name"]

    def add_card(self, url):
        """Put the Issue on the team's Project with the values prepare() worked out (no Project: nothing)."""
        if not self.card:
            return
        c = self.card
        item = gh_json("project", "item-add", c["number"], "--owner", c["owner"], "--url", url, "--format", "json")["id"]
        for field, option in c["values"]:
            gh("project", "item-edit", "--id", item, "--project-id", c["id"], "--field-id", field,
               "--single-select-option-id", option)


def to_team(t, what, change):
    """Copy a change to the task's team Issue (`task share`): change(connector, number). Only for a task with a link
    (t["link"]: launch's issue() read, kept in the run file, or the command's own issue() read): no GitHub call is added
    to find it. A failure stops nothing: one line on stderr, as a failed notification or cache (lld.md 8)."""
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", t.get("link") or "")
    if not m:
        return
    try:
        change(TeamGitHub(m[1], t.get("link_project") or ""), m[2])
    except (RuntimeError, OSError, ValueError, LookupError, TypeError, AttributeError) as e:
        print(f"warning: task {t['id']}: could not copy {what} to {m[0]}: {e}", file=sys.stderr, flush=True)


def add_closes(url, ref):
    """`Closes <ref>` in an open PR's body, after its other Closes lines. False when it is closed or has it already."""
    pr = gh_json("pr", "view", url, "--json", "body,state")
    body = pr.get("body") or ""
    if pr.get("state") != "OPEN" or re.search(rf"(?im)^closes {re.escape(ref)}\s*$", body):
        return False
    closes = list(re.finditer(r"(?im)^closes \S+[ \t]*$", body))
    at = closes[-1].end() if closes else len(body.rstrip())
    f = DATA / f"pr-body-{ref.replace('/', '-').replace('#', '-')}.md"
    f.write_text(body[:at] + f"\n\nCloses {ref}" + body[at:])
    try:
        gh("pr", "edit", url, "--body-file", f)
    finally:
        f.unlink(missing_ok=True)
    return True


def share_pr(t, ref):
    """The lines about the task's PR once it is shared: its PR closes the team's Issue too. A run still going
    rewrites its PR's body when it finishes, from what it read when it began."""
    if t.get("running"):
        return [f"help: its run began before it was shared, so that run's PR closes only #{t['id']}: run this again "
                "once the run ends (later runs add it themselves)"]
    if t.get("pr") and add_closes(t["pr"], ref):
        return [f"  pr: {t['pr']} (closes {ref} too now)"]
    return []


# ---------- merge queue: approved PRs kept up to date and merged one at a time (docs/operations.md) ----------

MERGE_QUEUE = STATE / "merge-queue.json"  # {"queue": [...]}: the approved PRs, oldest approval first
MERGE_QUEUE_LOCK = STATE / "merge-queue.lock"  # held for each read-change-write of MERGE_QUEUE (`task merge`, sync)
MERGE_WORK_LOCK = STATE / "merge-queue.work.lock"  # held by the one task-hub working the queue (`task watch`, `task`)
# after a push, how long "no checks" may only mean GitHub has not started them yet (tests: 0)
CHECKS_GRACE = float(os.environ.get("TASK_CHECKS_GRACE_SECONDS") or 120)
MERGE_READY = {"CLEAN", "HAS_HOOKS"}  # mergeStateStatus values GitHub merges at once
MERGE_WAIT = {"BLOCKED", "UNKNOWN", ""}  # may still change by itself (GitHub recomputing): waited for up to ci_minutes
MERGE_STATES = {"BLOCKED": "a required review or a rule of the branch is missing",
                "UNSTABLE": "a check that is not required failed or has not finished",
                "DRAFT": "the PR is a draft"}
CONFLICT_MARKER = r"(?m)^(<{7}|>{7})( |$)"


def merge_config():
    """[merge]: queue (off by default), prefix (fix In review PRs that conflict before anyone approves them), checks
    (all, or only the required ones), ci_minutes (how long to wait for them). A bad value stops before anything changes."""
    m = config()["merge"]

    def switch(key):
        value = m.get(key, "").strip().lower() or "off"
        if value not in ("on", "off"):
            fail(f"[merge] {key} must be on or off; got {value!r}", f"set  [merge]  {key} = on  in {home(CONFIG)} "
                                                                    "(off by default)")
        return value == "on"
    checks = m.get("checks", "").strip().lower() or "all"
    if checks not in ("all", "required"):
        fail(f"[merge] checks must be all or required; got {checks!r}", f"fix it in {home(CONFIG)} (default all)")
    minutes = m.get("ci_minutes", "").strip() or str(CI_MINUTES)
    if not re.fullmatch(r"\d+", minutes) or int(minutes) < 1:
        fail(f"[merge] ci_minutes must be a whole number, 1 or more; got {minutes!r}",
             f"fix it in {home(CONFIG)} (default {CI_MINUTES})")
    return {"queue": switch("queue"), "prefix": switch("prefix"), "required": checks == "required",
            "ci_seconds": int(minutes) * 60}


def read_queue():
    """The queue's entries: {id, repo, pr, queued, step, since, fixed, ci_wait}; none when the file is missing."""
    q = read_json(MERGE_QUEUE).get("queue")
    return [e for e in q if isinstance(e, dict) and e.get("id") and e.get("pr")] if isinstance(q, list) else []


def change_queue(change):
    """Run change(entries) on the queue and write it back, under its lock: `task merge` and the sync both change it."""
    with file_lock(MERGE_QUEUE_LOCK, wait=True) as mine:
        if not mine:
            raise RuntimeError(f"another task-hub holds {home(MERGE_QUEUE_LOCK)}; try again")
        q = read_queue()
        result = change(q)
        write_atomic(MERGE_QUEUE, json.dumps({"queue": q}, indent=1))
        return result


def queue_drop(tid):
    change_queue(lambda q: q.__setitem__(slice(None), [e for e in q if e["id"] != tid]))


def queue_set(e, **changes):
    e.update(changes)
    change_queue(lambda q: [x.update(changes) for x in q if x["id"] == e["id"]])


def queue_column():
    """Where an approved card waits: the optional wait for merge column when the board has it, else In review."""
    return WAIT_FOR_MERGE if WAIT_FOR_MERGE.lower() in board()["status_options"] else IN_REVIEW


def queue_entry(t):
    """The card's queue entry, with its open PR (this machine's run, else found by the task's branch); None without."""
    pr = t.get("pr") or ""
    if not pr and re.fullmatch(r"[\w.-]+/[\w.-]+", t.get("repo") or ""):
        found = find_pr({**t, "branch": t.get("branch") or f"task/{t['id']}"})
        pr = found["url"] if found and found["state"] == "OPEN" else ""
    m = re.fullmatch(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/\d+", pr)
    return {"id": t["id"], "repo": m[1], "pr": pr, "queued": now(), "step": "update"} if m else None


def position(q, e):
    return [x["repo"].lower() for x in q].count(e["repo"].lower())


def pr_view(url):
    return gh_json("pr", "view", url, "--json",
                   "url,state,isDraft,headRefName,baseRefName,headRefOid,mergeable,mergeStateStatus")


def pr_checks(url, required):
    """The PR's checks as [{name, bucket, link}] (bucket: pass, fail, pending, skipping or cancel); [] when it has none."""
    try:
        r = run(GH, "pr", "checks", url, *(["--required"] if required else []), "--json", "name,bucket,link")
    except FileNotFoundError:
        raise RuntimeError(f"gh not found ({GH})") from None
    if r.stdout.strip():  # it exits 8 while one is pending and 1 when one failed: the JSON says which
        with contextlib.suppress(ValueError):
            checks = json.loads(r.stdout)
            if isinstance(checks, list):
                return checks
    if re.search(r"no (required )?checks reported", r.stderr + r.stdout):
        return []
    raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or ["gh pr checks failed"])[-1])


def git_out(wt, *args):
    return git_shared(wt, *args).stdout.strip()


def unmerged(wt):
    return git_out(wt, "diff", "--name-only", "--diff-filter=U").splitlines()


def merge_worktree(t, head):
    """The task's worktree on the PR's branch, as the branch is on GitHub: where its base is merged into it."""
    repo_dir = ensure_clone(t["repo"])  # fetches: the base as it is now
    wt = Path(t.get("worktree") or DATA / "worktrees" / t["id"])
    if not (wt / ".git").exists():  # the task ran on another machine, or its worktree was removed
        git_shared(repo_dir, "worktree", "prune")
        git_shared(repo_dir, "worktree", "add", "-q", "-B", head, wt, f"origin/{head}", check=True)
        t.update(worktree=str(wt), branch=head)
        save_run(t)  # cleanup removes it with the card
        ensure_internal_excludes(wt)
        return wt
    if git_out(wt, "rev-parse", "--abbrev-ref", "HEAD") != head:
        raise RuntimeError(f"the worktree {home(wt)} is not on the PR's branch {head}")
    if git_out(wt, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError(f"the worktree {home(wt)} has changes nobody committed; commit or undo them")
    if git_shared(wt, "merge", "--ff-only", "-q", f"origin/{head}").returncode != 0:
        raise RuntimeError(f"branch {head} on GitHub and the worktree {home(wt)} have both changed; "
                           f"merge origin/{head} in that worktree (or delete it to start from GitHub's)")
    return wt


def merge_block(t, e, reason):
    """The queue stops for this card: why, on the Issue and the card. The next PR of its repo goes on."""
    comment(t, f"{MERGE_MARK}\n\n## Merge queue\n\nBlocked: {reason}\n\nPR: {e['pr']}\n\n"
               f"Fix it, then run `task merge {t['id']}` to queue it again.")
    set_status(t, BLOCKED, reason=f"merge queue: {reason}")
    queue_drop(t["id"])  # last: a GitHub failure above leaves it queued, to try again at the next check
    return f"blocked: {reason}"


def close_merged(t):
    """Its PR was merged: close the Issue (GitHub's "Closes ..." works only for PRs into the default branch, and can
    miss even those), move the card to Done, clean up."""
    gh("issue", "close", t["id"], "--repo", board()["issues"])
    to_team(t, "the close", lambda team, n: team.close(n))  # GitHub did not close it either
    set_status(t, DONE)
    cleanup(t)


def merge_queue(open_, settings, lines, changed, errors):
    """[merge] queue: cards a human moved to wait for merge join the queue, and the first PR of each repo takes its next
    step. Only one PR per repo moves at a time: each merge changes the base the next one is merged with."""
    cards = {t["id"]: t for t in open_}
    try:
        column = queue_column()
        queued = {e["id"] for e in read_queue()}
        # dragged to wait for merge on GitHub: approved like `task merge`, in the order the cards were moved
        for t in sorted((t for t in open_ if t["status"] == WAIT_FOR_MERGE and t["id"] not in queued),
                        key=lambda t: t["updated"]):
            e = queue_entry(t)
            if not e:
                lines.append(f"merge: task {t['id']} is in {WAIT_FOR_MERGE} but has no open PR")
                continue
            n = change_queue(lambda q: q.append(e) or position(q, e))
            emit(t, "queued", pr=e["pr"], reason=f"position {n} in the merge queue of {e['repo']}")
            lines.append(f"merge: task {t['id']} joined the queue of {e['repo']} (position {n})")
    except RuntimeError as err:
        errors.append({"id": "", "error": f"merge queue: {err}"})
        return
    with file_lock(MERGE_WORK_LOCK) as mine:
        if not mine:
            lines.append("merge: another task-hub is working the queue")
            return
        heads = {}
        for e in read_queue():
            heads.setdefault(e["repo"].lower(), e)
        for e in heads.values():
            t = cards.get(e["id"])
            before = t["status"] if t else ""
            try:
                line = merge_step(t, e, column, settings)
            except (RuntimeError, OSError) as err:  # GitHub or git: the same step again at the next check
                errors.append({"id": e["id"], "error": f"merge queue: {err}"})
                continue
            if line:
                lines.append(f"merge: task {e['id']}: {line}")
            if t and t["status"] != before:
                changed.append({"id": t["id"], "title": t["title"], "now": t["status"]})


def queued_after(e, fetched):
    """Whether the entry was queued after the board was read at fetched (UNIX time). `queued` has whole seconds:
    queued within the second the read began counts as after, so the entry waits one check rather than leaving."""
    try:
        queued = datetime.datetime.strptime(e.get("queued") or "", "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return queued.replace(tzinfo=datetime.timezone.utc).timestamp() >= int(fetched)


def merge_step(t, e, column, settings):
    """One step of the first PR of a repo's queue; returns what it did, as one line."""
    if t and t["status"] != column and queued_after(e, t["fetched"]):
        return None  # queued since the board was read (`task merge` moved it meanwhile): the next check sees it
    if not t or t["status"] != column:  # a human moved it (or `task done`): no longer approved
        queue_drop(e["id"])
        return f"left the queue ({t['status'] if t else 'no longer open'})"
    if t["running"]:
        return f"waiting for its run ({t.get('stage') or 'starting'})"
    pr = pr_view(e["pr"])
    if pr["state"] == "MERGED":  # merged by hand: the merge watch moves the card to Done
        queue_drop(e["id"])
        return "its PR was merged elsewhere"
    if pr["state"] != "OPEN":
        return merge_block(t, e, f"its PR was closed without merging: {e['pr']}")
    if pr.get("isDraft"):
        return merge_block(t, e, f"its PR is a draft: {e['pr']}")
    t["pr"] = e["pr"]
    if e.get("step") == "ci":
        return merge_ci(t, e, pr, settings)
    return merge_update(t, e, pr, settings)


def merge_update(t, e, pr, settings):
    """Merge the PR's base into its branch, a real merge commit; push it, or start the conflict fix."""
    head, base = pr["headRefName"], pr["baseRefName"]
    wt = merge_worktree(t, head)
    base_sha = git_out(wt, "rev-parse", f"origin/{base}")
    r = git_shared(wt, "merge", "--no-edit", "-q", f"origin/{base}")
    if r.returncode == 0:
        # against GitHub's branch, not the worktree's: a merge an earlier push failed to send is still to push
        if git_out(wt, "rev-parse", "HEAD") == git_out(wt, "rev-parse", f"origin/{head}"):
            queue_set(e, step="ci", since=now())  # up to date already: its checks are the ones to wait for
            return merge_ci(t, e, pr, settings)
        failed = push_failed(wt, head)
        if failed:  # the merge commit stays in the worktree, never reset away: queued again, it is pushed then
            return merge_block(t, e, failed)
        queue_set(e, step="ci", since=now())
        emit(t, "updated", pr=e["pr"], reason=f"merged {base} into {head}")
        return f"merged {base} into {head} and pushed; its checks come next"
    conflicted = unmerged(wt)
    git_shared(wt, "merge", "--abort")
    if not conflicted:
        raise RuntimeError(f"git merge origin/{base} failed: {git_said(r)}")
    files = ", ".join(conflicted)
    if e.get("fixed") == base_sha:  # the fix ran for this very base and the conflict is still there
        return merge_block(t, e, f"the conflict fix did not resolve the conflicts with {base} ({files})")
    with launch_lock(t["id"]) as mine:
        if not mine or alive(load_run(t["id"])):
            return "its run is starting in another task-hub"
        launch_fix(t, base, head)
    queue_set(e, step="update", fixed=base_sha)
    emit(t, "conflict-fix", pr=e["pr"], reason=f"{files} conflict with {base}; {t['agent']} is resolving them")
    return f"{files} conflict with {base}; started the conflict fix (`task log {t['id']}`)"


def push_failed(wt, head):
    """Push the worktree's HEAD to the PR's branch: "" when it got there, else why not (the commit stays local)."""
    r = git_shared(wt, "push", "-q", "origin", f"HEAD:{head}")
    if r.returncode == 0:
        return ""
    return f"pushing {head} failed, the merge commit is kept in {home(wt)}: {git_said(r)}"


TERMINAL_ESCAPE = r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Za-z0-9]|\x1b[=>]"


def git_said(r, limit=300):
    """What a failed git command said, for a reason: one clean line per message, at most about `limit` characters.
    Sideband output (`remote: `, a hook's message) comes padded with spaces or ANSI clear-line codes and
    redrawn with \\r, more so on macOS; only the last drawing of each line is kept. Cut to size by whole lines,
    the `remote:` ones first, then a ref's `! [rejected]`: they say why, where `To <url>` and `error: failed to
    push` only say where."""
    lines = []
    for line in (r.stderr or r.stdout or "").split("\n"):  # not splitlines(): that splits at \r too
        drawn = [d.strip() for d in re.sub(TERMINAL_ESCAPE, "", line).split("\r")]
        if last := next((d for d in reversed(drawn) if d not in ("", "remote:")), ""):
            lines.append(last[:limit])
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    order = sorted(reversed(range(len(lines))), key=lambda i: 0 if lines[i].startswith("remote:") else
                   1 if lines[i].startswith("! ") else 2)
    kept, size = set(), 0
    for i in order:  # the first one always fits: every line is at most `limit`, and \n only goes between lines
        need = len(lines[i]) + (1 if kept else 0)
        if size + need > limit:
            continue
        kept.add(i)
        size += need
    return "\n".join(lines[i] for i in sorted(kept))


def merge_ci(t, e, pr, settings):
    """Wait for the PR's checks, then merge it when GitHub says it can."""
    checks = pr_checks(e["pr"], settings["required"])
    failed = [c for c in checks if c.get("bucket") in ("fail", "cancel")]
    if failed:
        return merge_block(t, e, "; ".join(f"check {c.get('name') or '?'} failed: {c.get('link') or e['pr']}"
                                           for c in failed[:3]))
    waited, limit = seconds_since(e.get("since") or now()), settings["ci_seconds"]
    pending = [c.get("name") or "?" for c in checks if c.get("bucket") == "pending"]
    pushed = git_shared(clone_dir(t["repo"]), "log", "-1", "--format=%ct", pr["headRefOid"]).stdout.strip()
    if not checks and pushed.isdigit() and time.time() - int(pushed) < CHECKS_GRACE:
        pending = ["(none reported yet)"]  # just pushed: GitHub may not have started them
    if pending:
        if waited >= limit:
            return merge_block(t, e, f"its checks did not finish in {limit // 60} min: {', '.join(pending)}")
        ci_wait(t, e, pr, f"waiting for {', '.join(pending)}")
        return f"waiting for its checks: {', '.join(pending)}"
    state = pr.get("mergeStateStatus") or ""
    if pr.get("mergeable") == "CONFLICTING" or state in ("DIRTY", "BEHIND"):  # the base moved on meanwhile
        queue_set(e, step="update")
        return f"{pr['baseRefName']} moved on; merging it in at the next check"
    # [merge] checks = required: the required ones all passed above, so the ones still running or failed are not
    # required, and GitHub merges an UNSTABLE PR
    if state in MERGE_READY or (state == "UNSTABLE" and settings["required"]):
        # only the commit whose checks passed: a push since then waits for its own
        gh("pr", "merge", e["pr"], "--merge", "--match-head-commit", pr["headRefOid"])
        queue_drop(t["id"])
        emit(t, "merged", pr=e["pr"], reason=f"merged into {pr['baseRefName']} by the merge queue")
        close_merged(t)
        return f"merged {e['pr']}"
    if state == "UNSTABLE" and waited < limit:
        # none of the checks read above (after the PR) failed or is running: GitHub has not yet counted the one that
        # finished last (it lags seconds behind), so wait like for a running one; one that failed blocks above
        ci_wait(t, e, pr, "waiting for GitHub to count its finished checks")
        return "waiting for GitHub to count its finished checks (UNSTABLE)"
    if state in MERGE_WAIT and waited < limit:
        return f"waiting for GitHub to allow the merge ({state or 'UNKNOWN'})"
    return merge_block(t, e, f"GitHub does not allow the merge ({state or 'UNKNOWN'}: "
                             f"{MERGE_STATES.get(state, 'see the PR')}): {e['pr']}")


def ci_wait(t, e, pr, reason):
    """Tell that the queue waits for the PR's checks: once per commit of the PR."""
    if e.get("ci_wait") != pr["headRefOid"]:
        queue_set(e, ci_wait=pr["headRefOid"])
        emit(t, "ci-wait", pr=e["pr"], reason=reason)


def watch_conflict(t, pull, settings):
    """An In review PR nobody approved yet that conflicts with its base now: told once per commit of the PR, and with
    [merge] prefix = on fixed (never merged) before the human looks at it. pull: the merge watch's own REST read."""
    sha = (pull.get("head") or {}).get("sha") or ""
    if t["status"] != IN_REVIEW or pull.get("mergeable_state") != "dirty" or t["running"] or not sha:
        return []
    base, head = (pull.get("base") or {}).get("ref") or "", (pull.get("head") or {}).get("ref") or ""
    told = lambda name: any(x.get("id") == t["id"] and x.get("sha") == sha for x in events_named(name))
    lines = []
    if not told("conflict"):
        emit(t, "conflict", pr=t["pr"], sha=sha, reason=f"its PR conflicts with {base} now"
             + ("" if settings["prefix"] else f"; `task merge {t['id']}` queues it, and the queue resolves it"))
        lines.append(f"merge: task {t['id']}: its PR conflicts with {base} now")
    if settings["prefix"] and base and head and not told("conflict-fix"):
        with launch_lock(t["id"]) as mine:
            if not mine or alive(load_run(t["id"])):
                return lines
            launch_fix(t, base, head)
        emit(t, "conflict-fix", pr=t["pr"], sha=sha, reason=f"{t['agent']} is resolving the conflicts with {base}")
        lines.append(f"merge: task {t['id']}: started the conflict fix (`task log {t['id']}`)")
    return lines


def launch_fix(t, base, head):
    """Start `task _fix <number> <base>` in the background: the agent resolves the conflicts of base with the PR's
    branch in the task's worktree. The card stays where it is; `task list` shows the run's stage."""
    t["agent"] = t.get("agent") or config()["runner"]["agent"]
    if not config().has_option("agents", t["agent"]):
        raise RuntimeError(f'unknown agent "{t["agent"]}" on the card')
    check_ready(t["agent"])
    wt = merge_worktree(t, head)
    LOGS.mkdir(parents=True, exist_ok=True)
    # `started` stays the last run's: a re-run's prompt gets the comments since then, the review of the PR included
    t.update(worktree=str(wt), branch=head, log=str(LOGS / f"{t['id']}.log"), pid="", stage="conflict-fix")
    save_run(t)  # before it starts: the run reads it
    t["pid"] = str(start_logged([sys.executable, str(BIN), "_fix", t["id"], base],
                                   wt if sandbox_mode() == "off" else DATA, t["log"]).pid)
    save_run(t)  # alive() at once (the fix writes the same pid when it begins)


def build_fix_prompt(t, base, conflicted):
    instructions = WORKER_CONFLICT.read_text().split("\n---\n", 1)[-1].strip()
    return "\n".join([instructions, "", "# Task", "", f"Task {t['id']}: {t['title']}", f"Repository: {t['repo']}",
                      f"Branch: {t['branch']} (the PR's branch, already checked out, in the middle of merging {base})",
                      f"Base branch: {base}", "", "## Goal", "", issue(t)["body"].strip(), "", "# Conflicted files", "",
                      *(f"- {f}" for f in conflicted), ""])


def cmd_fix(a):
    """One conflict fix (launch_fix): merge the base into the PR's own branch, let the agent resolve the conflicts,
    make the merge commit (two parents) and push it. One that cannot be finished is undone, and the card is Blocked."""
    t = {"id": a["id"], **load_run(a["id"])}
    t["pid"] = str(os.getpid())
    save_run(t)
    log = None if os.environ.get("TASK_RUN_LOGGED") else open(t["log"], "a")

    def say(line):
        print(line, flush=True)
        if log:
            log.write(line + "\n")
            log.flush()

    wt, base = Path(t["worktree"]), f"origin/{a['base']}"
    shared_unlink(wt / REPORT_FILE)
    say(f"== task {t['id']}: conflict fix of {t['branch']} with {base} | agent {t['agent']} | {now()}")
    start = git_out(wt, "rev-parse", "HEAD")
    try:
        reason, report, conflicted, keep = fix_conflicts(t, wt, base, say)
    except RuntimeError as e:
        reason, report, conflicted, keep = f"the conflict fix failed: {e}", "", [], False
    if reason and not keep:  # nothing of it reaches the PR
        say(f"== {reason}")
        git_shared(wt, "merge", "--abort")
        git_shared(wt, "reset", "-q", "--hard", start)
        git_shared(wt, "clean", "-fdq")
    parsed = AgentReport(report)
    body = "\n\n".join([f"{MERGE_MARK}\n\n## Merge queue",
                        f"Blocked: {reason}" if reason else
                        f"Resolved the conflicts of {t['branch']} with {base}"
                        + (f" ({', '.join(conflicted)})" if conflicted else "") + " and pushed the merge commit.",
                        *([f"### Report\n\n{parsed.report}"] if parsed.report else []),
                        *([f"### Please review\n\n{parsed.review}"] if parsed.review else []),
                        *([f"PR: {t['pr']}"] if t.get("pr") else [])])
    try:
        take_card(t)
        comment(t, body)
        if reason:
            set_status(t, BLOCKED, reason=f"merge queue: {reason}")
        else:
            emit(t, "updated", pr=t.get("pr", ""), reason=f"merged {a['base']} into {t['branch']}"
                 + (f"; {t['agent']} resolved the conflicts in {', '.join(conflicted)}" if conflicted else ""))
    except RuntimeError as e:  # the push is done; a card left where it was is fixed by the queue's next check
        say(f"== could not report it: {e}")
    shared_unlink(wt / REPORT_FILE)
    set_stage(t, "")
    say(f"== task {t['id']}: conflict fix {'blocked' if reason else 'pushed'}.")


def fix_conflicts(t, wt, base, say):
    """(why it cannot be merged or "", the agent's report, the conflicted files, whether the merge commit is kept:
    made but not pushed, so it is never undone)."""
    r = git_shared(wt, "merge", "--no-ff", "--no-commit", base)
    conflicted = unmerged(wt)
    merging = lambda: git_shared(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0
    if r.returncode != 0 and not conflicted:
        return f"git merge {base} failed: {git_said(r)}", "", [], False
    if not merging():  # up to date: nothing to fix
        say(f"== {t['branch']} already has {base}")
        return "", "", [], False
    report = ""
    if conflicted:
        say(f"== conflicts: {', '.join(conflicted)}")
        code = run_agent_process(t["agent"], build_fix_prompt(t, base, conflicted), wt, say, "conflict fixer")
        say(f"== agent exited with code {code}")
        report = agent_file(wt / REPORT_FILE) or ""
        if not report.strip():
            return f"the conflict fixer exited without a report (exit {code}), see `task log {t['id']}`", "", conflicted, False
        if AgentReport(report).blocked:
            return f"the conflict fixer could not resolve them: {AgentReport(report).blocked}", report, conflicted, False
        if not merging():
            return "the conflict fixer ended the merge itself (a commit, an abort or a reset); task-hub makes the " \
                   "merge commit", report, conflicted, False
        git_shared(wt, "add", "-A", check=True)
        left = unmerged(wt) + [f for f in conflicted
                               if re.search(CONFLICT_MARKER, (shared_read(wt / f) or b"").decode(errors="replace"))]
        if left:
            return f"conflict markers are left in {', '.join(dict.fromkeys(left))}", report, conflicted, False
    git_shared(wt, "commit", "-q", "--no-edit", check=True)  # MERGE_HEAD: a commit with both parents
    failed = push_failed(wt, t["branch"])
    if failed:
        return failed, report, conflicted, True
    say(f"== pushed the merge of {base} into {t['branch']}")
    return "", report, conflicted, False


# ---------- sync: board and runs in, new runs out ----------

def sync(started_here=False):
    """started_here: someone ran `task` or `task start` by hand, so the tasks it starts belong where they are.
    Not for `task watch`: it starts whatever becomes Ready, wherever it happens to run."""
    slots = parallel()  # a bad value stops before anything changes
    merge = merge_config()
    autopilot = autopilot_config()
    readiness = readiness_mode()
    lines, changed, errors = [], [], []
    open_ = tasks()
    queued = {e["id"] for e in read_queue()} if merge["queue"] else set()
    # a card that left the open columns (GitHub moves it to Done when its Issue closes, e.g. the PR
    # was merged) no longer needs its worktree or herdr workspace: clean up from local state only
    all_ = None  # every card, Done ones too: read once, and only when a run's card left the open columns
    for f in RUNS.glob("*.json") if RUNS.exists() else []:
        t = {"id": f.stem, **load_run(f.stem)}
        if t["id"] not in {x["id"] for x in open_} and not alive(t):
            if all_ is None:
                try:
                    all_ = {x["id"]: x for x in tasks(include_done=True)}
                except RuntimeError as e:  # keep the run files: the next check reads again and may still owe the Done
                    errors.append({"id": t["id"], "error": str(e)})
                    all_ = False
            if all_ is False:
                continue
            card = all_.get(t["id"])
            # GitHub moved it to Done (its "Item closed" workflow, about a second after the Issue closed), so no
            # set_status wrote the event. Once per run, as check_slow does: `task done` or the merge watch may have
            # written it already
            if card and card["status"] == DONE and not any(
                    e.get("id") == t["id"] and e.get("time", "") >= t.get("started", "") for e in events_named(DONE)):
                move_to_top(card)
                to_team(t, f"the Status {DONE}", lambda team, n: team.move(n, DONE, share_config(team.repo)))
                emit(t, DONE, pr=t.get("pr", ""))
            left = cleanup(t)
            if left:
                lines.append(f"cleanup: task {t['id']}: {left}; trying again at the next check")
            else:
                changed.append({"id": t["id"], "title": t.get("title", ""), "now": "cleaned up (card is Done)"})
    for t in open_:
        before = t["status"]
        try:
            if before == IN_PROGRESS and not alive(t):
                why = resumable(t) if t.get("started") else "no run here"
                why = why and f"not resumed: {why}"
                if not why:  # once (MAX_RESUMES): it goes on from its stage, and the card stays In progress
                    with launch_lock(t["id"]) as mine:
                        run_ = {**t, **load_run(t["id"])}
                        # another task-hub on this machine is resuming or starting it, or the run moved on since the
                        # board was read (it finished, or another task-hub resumed it): the next check decides
                        if not mine or alive(run_) or any(run_.get(k) != t.get(k) for k in ("stage", "resumes", "pid")):
                            continue
                        why = resumable(run_)  # again, now that no one else can start it
                        why = why and f"not resumed: {why}"
                        if not why:
                            try:
                                relaunch(run_)
                                lines.append(f"resumed: task {t['id']} at {run_['resume_stage']} "
                                             f"({run_['interrupted']}), once")
                                continue
                            except (RuntimeError, OSError, ValueError) as e:  # blocked below, as a failed start
                                why = f"could not resume it: {str(e)[:300]}"
                # a report the run could not deliver (GitHub was unreachable) is posted now
                kept, held = Path(t.get("worktree") or "/nonexistent") / REPORT_FILE, held_report_file(t)
                report = agent_file(kept) or (held.read_text() if held.exists() else "")  # held: died in a review
                reason = stopped_reason(t, why) if t.get("started") else "no run here"
                report_comment(t, blocked=f"{reason}, see `task log {t['id']}`"
                               if t.get("started") else "no run of this task on this machine",
                               report=report.strip())
                shared_unlink(kept)
                held.unlink(missing_ok=True)
                set_status(t, BLOCKED, reason=reason)
            elif before == IN_PROGRESS:  # alive: tell once if it runs much longer than usual
                slow = check_slow(t)
                if slow:
                    lines.append(f"slow: task {t['id']} {slow} (stop it with Ctrl-C in its tab)")
            elif StatusLifecycle.needs_merge_watch(t):
                merged, pull = pr_merged(t)
                if merged:
                    close_merged(t)
                elif merge["queue"] and pull and t["id"] not in queued:
                    lines += watch_conflict(t, pull, merge)
        except RuntimeError as e:
            errors.append({"id": t["id"], "error": str(e)})
            continue
        if t["status"] != before:
            changed.append({"id": t["id"], "title": t["title"], "now": t["status"]})
    if autopilot:
        autopilot_merge(open_, autopilot, lines, changed, errors)
    if merge["queue"]:
        merge_queue(open_, merge, lines, changed, errors)
    if any(c["now"] in (DONE, "cleaned up (card is Done)") for c in changed):
        try:
            lines += archive_lines(archive_overflow())
        except RuntimeError as e:  # the next card that gets Done tries again
            errors.append({"id": "", "error": f"archiving old Done cards: {e}"})
    board_ = tasks() if changed else open_
    readiness_gate(board_, readiness, autopilot, errors=errors)  # before autopilot: require holds its Backlog cards too
    if autopilot:  # before the starts: what it approves starts in this same check
        autopilot_ready(board_, autopilot, lines, errors)
    if changed:
        lines += table("updated", changed, ["id", "title", "now"])
    if errors:
        lines += table("github_errors", errors, ["id", "error"])
    free = slots - sum(t["status"] == IN_PROGRESS for t in board_)
    waiting = [t for t in board_ if t["status"] == READY and t["waits_for"]]
    if waiting:  # never started, so they take no slot; each starts once what it waits for is done
        lines += table("waiting", waiting, ["id", "title", "waits_for"])
    # started in the order they were made, whatever order the board is shown in
    ready = sorted((t for t in board_ if t["status"] == READY and not t["waits_for"]), key=lambda t: int(t["id"]))
    if ready and free <= 0:
        lines.append(f"queue: {len(ready)} Ready task(s) waiting, all {slots} slots busy")
    started = []
    for t in ready[:max(free, 0)]:
        with launch_lock(t["id"]) as mine:
            # the board was read before another task-hub on this machine started it: a second start would
            # close the first one's tab and share its worktree (#43)
            if not mine or alive(load_run(t["id"])):
                lines.append(f"skipped: task {t['id']} is already starting in another task-hub "
                             "(`task watch` or `task start`)")
                continue
            try:
                if started_here:  # Issues made without `task new` (gh, GitHub, other skills) have no workspace yet
                    remember_where_asked(t, keep=True)
                launch(t)
            # still holding the lock: no other start sees the card Ready in between. OSError and ValueError too (a
            # file in the way, a read-only copy): the card is blocked with why, instead of ending a watch that would
            # fail on it again after every restart, and start no other card
            except (RuntimeError, OSError, ValueError) as e:
                record_run({"id": t["id"], "title": t["title"], "repo": t.get("repo", ""),
                            "agent": t.get("agent", ""), "started": now(), "finished": now(), "seconds": 0,
                            "status": BLOCKED, "blocked_by": "start", "reviews": [], "retried": False, "retries": 0,
                            "review_stop": "", "replan": ""})
                report_comment(t, blocked=f"could not start: {str(e)[:300]}")
                set_status(t, BLOCKED, reason=f"could not start: {str(e)[:300]}")
                lines.append(f"error: task {t['id']} could not start: {e}")
                continue
        started.append({"id": t["id"], "agent": t["agent"],
                        "where": f"herdr tab {t['tab']}" if t["tab"] else
                        f"herdr workspace {t['workspace']}" if t["workspace"] else home(t["log"])})
        if readiness == "warn" and t.get("readiness") not in ("GO", "research"):  # started anyway: only said
            why = f"started without a GO for its current Goal: {READINESS_WHY[t.get('readiness') or 'unknown']}"
            emit(t, "readiness", reason=why)
            lines.append(f"readiness: task {t['id']} {why} (`task check {t['id']}`)")
    if started:
        lines += table("started", started, ["id", "agent", "where"])
    return lines, board_


# ---------- autopilot: the human's two decisions, made by task-hub for the listed repos (docs/autopilot.md) ----------

def autopilot_config():
    """[autopilot] repos as a set of lower-case owner/name; empty when unset. It merges through the merge queue after
    the automated review, so it needs both: a bad value or a missing one stops before anything changes."""
    repos = autopilot_repos()
    for r in sorted(repos):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", r):
            fail(f"[autopilot] repos takes repos written owner/name; got {r!r}",
                 f"fix it in {home(CONFIG)} (see docs/autopilot.md)")
    if repos and not merge_config()["queue"]:
        fail("[autopilot] merges through the merge queue, which is off",
             f"set  [merge]  queue = on  in {home(CONFIG)} (see docs/autopilot.md)")
    if repos and not config()["runner"].get("reviewer", "").strip():
        fail("[autopilot] merges only what the automated review passed, and no reviewer is set",
             f"set  [runner]  reviewer = agent  in {home(CONFIG)} (see docs/autopilot.md)")
    return repos


def autopilot_repos():
    """[autopilot] repos as written, lower case, unchecked (autopilot_config checks them)."""
    return {r.strip().lower() for r in re.split(r"[,\s]+", config()["autopilot"].get("repos", "")) if r.strip()}


def all_events():
    """Every event in EVENTS, oldest first, from one read; a line that is not an event is left out."""
    events = []
    for line in (event_lines_of(EVENTS.read_text(errors="replace")) if EVENTS.exists() else []):
        with contextlib.suppress(ValueError):
            e = json.loads(line)
            if isinstance(e, dict) and e.get("event"):
                events.append(e)
    return events


def left_backlog():
    """The ids of the cards task-hub ever moved out of Backlog (its Status events)."""
    return {e.get("id") for e in all_events() if e["event"] in StatusLifecycle.all and e["event"] != BACKLOG}


def autopilot_ready(board_, repos, lines, errors):
    """Move the listed repos' Backlog cards to Ready, as the human would, when nothing it waits for is open and its
    Goal does not say `Autopilot: off`. Only cards that never left Backlog: one that ran before, or that the human
    started or moved back to Backlog, stays with the human."""
    candidates = [t for t in board_ if t["status"] == BACKLOG and (t.get("repo") or "").lower() in repos
                  and not t["waits_for"] and not t["running"] and not t.get("autopilot_off") and not t["closed"]
                  and not (RUNS / f"{t['id']}.json").exists()]
    left = left_backlog() if candidates else set()
    for t in sorted(candidates, key=lambda t: int(t["id"])):
        if t["id"] in left:
            continue
        try:
            set_status(t, READY)
            emit(t, "autopilot", action="ready", reason=f"moved to Ready: [autopilot] repos lists {t['repo']}")
        except RuntimeError as e:  # the next check tries again
            errors.append({"id": t["id"], "error": f"autopilot: {e}"})
            continue
        lines.append(f"autopilot: task {t['id']} moved to Ready")


def autopilot_merge(open_, repos, lines, changed, errors):
    """Queue the PR of each listed repo's In review card whose last run's automated review passed, as `task merge`
    would, unless its Goal says `Autopilot: off`. Only what was reviewed: the card's newest Status event is that In
    review, and the PR is the one the run opened, still at the commit the run pushed and not a draft. Once per review:
    a PR that was in the queue since (queued by anyone, then taken out) or that autopilot skipped is the human's."""
    cards = [t for t in open_ if t["status"] == IN_REVIEW and (t.get("repo") or "").lower() in repos
             and not t.get("autopilot_off")]
    if not cards:
        return
    statuses, done = {}, {}
    for e in all_events():
        if e["event"] in StatusLifecycle.all:
            statuses[e.get("id")] = e  # the newest last
        elif e.get("event") == "queued" or (e.get("event") == "autopilot" and e.get("action") in ("merge", "skip")):
            done.setdefault(e.get("id"), []).append(e["time"])
    for t in cards:
        last = statuses.get(t["id"]) or {}
        d = last.get("digest") or {}
        # an In review without a digest (a cancelled merge) has no verdict; no PR: a research task's report
        if last.get("event") != IN_REVIEW or d.get("verdict", "").lower() != "pass" or not d.get("pr"):
            continue
        if any(time_ >= last["time"] for time_ in done.get(t["id"], [])):
            continue
        # its own run, or a conflict fix this check just started ([merge] prefix): t["running"] predates it
        if t["running"] or alive(load_run(t["id"])):
            continue
        try:
            pr = pr_view(d["pr"])
            why = ("its PR is not the one the review passed" if (t.get("pr") or d["pr"]) != d["pr"] else
                   "its PR is a draft" if pr.get("isDraft") else
                   "its PR is not open" if pr.get("state") != "OPEN" else
                   "its PR changed since its review" if not last.get("sha") or pr.get("headRefOid") != last["sha"]
                   else "")
            if why:
                emit(t, "autopilot", action="skip", pr=d["pr"], reason=f"{why}; it waits for you (`task merge "
                                                                          f"{t['id']}` queues it)")
                lines.append(f"autopilot: task {t['id']} left to you: {why}")
                continue
            e, n = enqueue(t)
        except ValueError:  # its PR is gone or its run is back: the next check looks again
            continue
        except RuntimeError as err:
            errors.append({"id": t["id"], "error": f"autopilot: {err}"})
            continue
        emit(t, "autopilot", action="merge", pr=e["pr"],
             reason=f"queued for merge: the automated review passed (position {n} in the queue of {e['repo']})")
        lines.append(f"autopilot: task {t['id']} queued for merge")
        if t["status"] != IN_REVIEW:
            changed.append({"id": t["id"], "title": t["title"], "now": t["status"]})


# ---------- triggers: cards task-hub makes on its own (docs/triggers.md) ----------

TRIGGER_KEYS = {"ci", "issues", "issue_label", "ready", "drift_report"}  # any other name is a recurring goal
CI_FAILED = {"failure", "timed_out", "startup_failure"}  # a run's conclusion that needs fixing
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DEFAULT_BRANCH_MAX_AGE = 24 * 3600  # a repo's default branch, asked once a day


def parse_schedule(text):
    """`daily`, `weekly [mon..sun]` (Monday), or `monthly [1-31]` (the 1st), each with an optional HH:MM (00:00) in the
    machine's own time zone: (period, day, (hour, minute)). ValueError says what is wrong."""
    words, clock = text.lower().split(), (0, 0)
    if words and re.fullmatch(r"\d{1,2}:\d{2}", words[-1]):
        clock = tuple(map(int, words.pop().split(":")))
        if clock[0] > 23 or clock[1] > 59:
            raise ValueError(f"{text!r}: {clock[0]}:{clock[1]:02d} is not a time of day")
    if words == ["daily"]:
        return "daily", None, clock
    if words[:1] == ["weekly"] and len(words) <= 2:
        name = words[1] if len(words) == 2 else "monday"
        day = next((i for i, d in enumerate(WEEKDAYS) if name in (d, d[:3])), None)
        if day is not None:
            return "weekly", day, clock
    if words[:1] == ["monthly"] and len(words) <= 2:
        day = int(words[1]) if len(words) == 2 and words[1].isdigit() else 1 if len(words) == 1 else 0
        if 1 <= day <= 31:
            return "monthly", day, clock
    raise ValueError(f"unknown schedule {text!r}: use daily, weekly [mon..sun], or monthly [1-31], "
                     "each with an optional HH:MM")


def due_period(schedule, when):
    """The period `when` (a local time) is in, e.g. 2026-10-17, 2026-W42, or 2026-10, once its day and time have
    come; else None. A day past the month's end (monthly 31) is its last day."""
    period, day, (hour, minute) = schedule
    date = when.date()
    if period == "daily":
        key, start = date.isoformat(), date
    elif period == "weekly":
        year, week, _ = date.isocalendar()
        key, start = f"{year}-W{week:02d}", date + datetime.timedelta(days=day - date.weekday())
    else:
        import calendar
        key, start = date.strftime("%Y-%m"), date.replace(day=min(day, calendar.monthrange(date.year, date.month)[1]))
    return key if when >= datetime.datetime.combine(start, datetime.time(hour, minute)) else None


def parse_recurring(name, value):
    """A recurring goal, `<schedule> <owner/repo> <goal>`, as a dict."""
    words = value.split()
    at = next((i for i, w in enumerate(words) if re.fullmatch(r"[\w.-]+/[\w.-]+", w)), None)
    if not at or at == len(words) - 1:
        raise ValueError(f"[triggers] {name} must be `<schedule> <owner/repo> <goal>`, "
                         f"e.g. `weekly mon jyoka/app Bump the dependencies`; got {value!r}")
    try:
        schedule = parse_schedule(" ".join(words[:at]))
    except ValueError as e:
        raise ValueError(f"[triggers] {name}: {e}") from None
    return {"name": name, "schedule": schedule, "repo": words[at], "goal": " ".join(words[at + 1:])}


def trigger_config():
    """[triggers] as a dict, or None when nothing is configured there. ValueError says what is wrong."""
    if not config().has_section("triggers"):
        return None
    s = config()["triggers"]
    repos = {}
    for k in ("ci", "issues"):  # a repo named twice, in any case, is asked once: one card per occurrence
        firsts = {}
        for r in re.split(r"[\s,]+", s.get(k, "")):
            if r:
                firsts.setdefault(r.lower(), r)
        repos[k] = list(firsts.values())
    for k, names in repos.items():
        for r in names:
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", r):
                raise ValueError(f"[triggers] {k} takes repos written owner/name; got {r!r}")
    if repos["issues"] and board_config()[2].lower() in (r.lower() for r in repos["issues"]):
        raise ValueError(f"[triggers] issues names the board's own Issue repo {board_config()[2]}: "
                         "its Issues are tasks already")
    recurring = [parse_recurring(k, v) for k, v in s.items() if k not in TRIGGER_KEYS]
    ready, drift = ({n for n in re.split(r"[\s,]+", s.get(k, "").lower()) if n} for k in ("ready", "drift_report"))
    for n in ready - {r["name"] for r in recurring}:
        raise ValueError(f"[triggers] ready names {n!r}, which is not a recurring goal in [triggers]: only those can "
                         "go to Ready (ci and issues cards always wait in Backlog for you)")
    for n in drift - {r["name"] for r in recurring}:
        raise ValueError(f"[triggers] drift_report names {n!r}, which is not a recurring goal in [triggers]: only "
                         "those can be drift reports (`<schedule> <owner/repo> <documents> against <code>`)")
    if not (repos["ci"] or repos["issues"] or recurring):
        return None
    return {**repos, "label": s.get("issue_label", "").strip(), "recurring": recurring, "ready": ready,
            "drift": drift}


def default_branch(repo, state):
    cached = state.setdefault("default_branch", {}).get(repo)
    if isinstance(cached, list) and len(cached) == 2 and isinstance(cached[1], (int, float)) \
            and 0 <= time.time() - cached[1] < DEFAULT_BRANCH_MAX_AGE:
        return cached[0]
    name = gh_json("repo", "view", repo, "--json", "defaultBranchRef")["defaultBranchRef"]["name"]
    state["default_branch"][repo] = [name, time.time()]
    return name


def ci_occurrences(repo, state, open_):
    """The newly failed runs on repo's default branch, as one card: the latest completed run of each workflow."""
    title = f"Fix failing CI on {repo}"
    if any(t["title"] == title for t in open_):  # being fixed already: its run, or a later one, waits for that card
        return []
    branch = default_branch(repo, state)
    latest = {}
    for r in gh_json("run", "list", "--repo", repo, "--branch", branch, "--limit", "20",
                     "--json", "databaseId,workflowName,status,conclusion,url,displayTitle") or []:
        if r.get("status") == "completed":  # newest first
            latest.setdefault(r.get("workflowName"), r)
    failed = [r for r in latest.values() if r.get("conclusion") in CI_FAILED
              and f"ci:{repo}:{r['databaseId']}" not in state["seen"]]
    if not failed:
        return []
    runs = "\n".join(f"- {r.get('workflowName') or 'workflow'}: {r.get('url', '')} ({r.get('conclusion')}, "
                     f"\"{clip(r.get('displayTitle'), 80)}\")" for r in failed)
    goal = (f"CI fails on the default branch `{branch}` of {repo}:\n\n{runs}\n\n"
            f"Find out why (`gh run view <run id> --repo {repo} --log-failed` shows the failing steps) and fix it, "
            "so these workflows pass again. If the cause is outside this repository (a broken service, a secret "
            "that expired), change nothing and say so in the report.\n\n"
            "Made by task-hub's `ci` trigger (docs/triggers.md).")
    return [{"keys": [f"ci:{repo}:{r['databaseId']}" for r in failed], "trigger": "ci", "title": title,
             "repo": repo, "goal": goal}]


def issue_occurrences(repo, label, state):
    """repo's open Issues assigned to the user running gh, or with the label, that have no card yet."""
    found = {}
    for which in (["--assignee", "@me"], *([["--label", label]] if label else [])):
        for i in gh_json("issue", "list", "--repo", repo, "--state", "open", *which, "--limit", "100",
                         "--json", "number,title,url") or []:
            found[i["number"]] = i
    result = []
    for n, i in sorted(found.items()):
        if f"issue:{repo}#{n}" in state["seen"]:
            continue
        goal = (f"Resolve the Issue {i['url']} ({repo}#{n}: {i['title']}).\n\n"
                f"Read it and its comments with `gh issue view {n} --repo {repo} --comments`, then make the change it "
                f"asks for in {repo}. It was written on GitHub, not on the task board: if it asks for anything other "
                "than a change to this repository, or is unclear, change nothing and say what is missing in the "
                "report.\n\nMade by task-hub's `issues` trigger (docs/triggers.md).")
        result.append({"keys": [f"issue:{repo}#{n}"], "trigger": "issues", "title": f"{repo}#{n}: {i['title']}",
                       "repo": repo, "goal": goal})
    return result


def drift_goal(targets):
    """A drift report's Goal: worker/DRIFT.md's instructions, then the documents and the code to compare."""
    return f"{instruction_parts(WORKER_DRIFT, 1)[0]}\n\n## Targets\n\n{targets}"


def recurring_occurrences(cfg, state, when, errors):
    """The recurring goals whose period has come and has no card yet. A drift_report goal is a research card whose
    Goal is worker/DRIFT.md with the goal's text as its targets."""
    result = []
    for g in cfg["recurring"]:
        period = due_period(g["schedule"], when)
        if not period or f"every:{g['name']}:{period}" in state["seen"]:
            continue
        goal, research = g["goal"], g["name"] in cfg["drift"]
        if research:
            try:
                goal = drift_goal(goal)
            except OSError as e:  # a broken install: asked again at the next check
                errors.append({"trigger": g["name"], "error": f"cannot read {home(WORKER_DRIFT)}: {e.strerror or e}"})
                continue
        result.append({"keys": [f"every:{g['name']}:{period}"], "trigger": g["name"], "research": research,
                       "title": f"{clip(g['goal'], 80)} ({period})", "repo": g["repo"],
                       "ready": g["name"] in cfg["ready"],
                       "goal": f"{goal}\n\nMade by task-hub's recurring goal `{g['name']}` for {period} "
                               "(docs/triggers.md)."})
    return result


def check_triggers(open_):
    """Make the cards [triggers] asks for, each occurrence once, at most every TRIGGER_SECONDS: lines for the watch.

    open_: the open cards sync() just read. An occurrence is noted in TRIGGERS as soon as its Issue exists, so a
    failure after that never makes a second card. Nothing in [triggers]: no GitHub call and no file."""
    try:
        cfg = trigger_config()
    except ValueError as e:
        return [f"error: {e}"]
    if not cfg:
        return []
    state = read_json(TRIGGERS)
    state["seen"] = state.get("seen") if isinstance(state.get("seen"), dict) else {}
    last = state.get("checked_at")
    if isinstance(last, (int, float)) and 0 <= time.time() - last < TRIGGER_SECONDS:
        return []
    state["checked_at"] = time.time()  # also after errors: a failing repo is asked again next time, not every minute
    made, errors, occurrences = [], [], []
    for kind, repo, find in [*(("ci", r, lambda r=r: ci_occurrences(r, state, open_)) for r in cfg["ci"]),
                             *(("issues", r, lambda r=r: issue_occurrences(r, cfg["label"], state))
                               for r in cfg["issues"])]:
        try:
            occurrences += find()
        except (RuntimeError, KeyError, TypeError, ValueError) as e:  # gh failed, or answered in another shape
            errors.append({"trigger": kind, "error": f"{repo}: {e}"})
    occurrences += recurring_occurrences(cfg, state, datetime.datetime.now(), errors)
    try:
        write_atomic(TRIGGERS, json.dumps(state))
        for o in occurrences:
            if any(k in state["seen"] for k in o["keys"]):  # noted by an earlier occurrence in this check
                continue
            def noted(url, o=o):  # before the card exists: never a second Issue for this occurrence
                state["seen"].update({k: {"at": now(), "issue": url} for k in o["keys"]})
                write_atomic(TRIGGERS, json.dumps(state))
            t = None
            try:
                labels = [RESEARCH_LABEL] if o.get("research") else []
                if labels:
                    research_label()
                t, _ = create_task(o["title"], o["repo"], o["goal"], labels=labels, created=noted)
                if o.get("ready"):
                    set_status(t, READY)
            except RuntimeError as e:
                where = f" (Issue #{t['id']} is on the board in {t['status']})" if t else \
                    f" (its Issue was made but is not on the board: {state['seen'][o['keys'][0]]['issue']})" \
                    if o["keys"][0] in state["seen"] else ""
                errors.append({"trigger": o["trigger"], "error": f"{o['title']}: {e}{where}"})
                continue
            made.append({"id": t["id"], "trigger": o["trigger"], "status": t["status"], "title": o["title"]})
    except OSError as e:  # nowhere to note what was made: making more could make them again at every check
        return [f"error: triggers: cannot write {home(TRIGGERS)}: {e}"]
    return (table("triggered", made, ["id", "trigger", "status", "title"]) if made else []) \
        + (table("trigger_errors", errors, ["trigger", "error"]) if errors else [])


# ---------- updates: this clone and the releases on its origin (docs/release.md) ----------

def version_key(name):
    """(major, minor, patch) of "v1.2.3" or "1.2.3", or None for any other name (task-rs-v0.2.0, v1.2)."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", name or "")
    return tuple(map(int, m.groups())) if m else None


def newest_release(names):
    """The newest v<MAJOR>.<MINOR>.<PATCH> tag among names, or ""."""
    return max((n for n in names if n.startswith("v") and version_key(n)), key=version_key, default="")


def quiet_git_env():
    """git that fails instead of asking for a password: nobody may be there to type it."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def lib_branch():
    """The branch LIB is on, or "" (the easy setup's installers keep their clone on a release tag; or LIB is not a
    clone)."""
    return run("git", "-C", LIB, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()


def lib_version():
    """The VERSION of LIB's bin/task now: after `task update` it is not the one this process runs."""
    return launcher_version(LIB / "bin" / "task")


def lib_release_tag():
    """The release tag LIB is on, or "": the easy setup's installers (kiro/install.sh, windows\\install.ps1) keep
    their clone on the newest release from EASY_SETUP_FIRST, not on a branch (docs/release.md)."""
    if lib_branch():
        return ""
    names = run("git", "-C", LIB, "tag", "--points-at", "HEAD").stdout.split()
    return newest_release(n for n in names if (version_key(n) or ()) >= EASY_SETUP_FIRST)


def read_update():
    try:
        d = json.loads(UPDATE.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_update(**changes):
    """A failure to note it only means origin is asked again next time."""
    temp = UPDATE.with_name(f".{UPDATE.name}.{os.getpid()}.tmp")
    try:
        UPDATE.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps({**read_update(), **changes}))
        temp.replace(UPDATE)
    except OSError:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)


class UpdateCheck:
    """Whether origin has a newer release than this VERSION, as gh and Homebrew tell of theirs.

    origin is asked (`git ls-remote`: the clone's own access, no GitHub token) at most once a day, while the command
    does its own work, and waited for at most UPDATE_TIMEOUT. When it cannot be reached, nothing is said and it is
    asked again after UPDATE_RETRY. A clone on a release tag (an installer's) is told too: `task update` installs the
    newer one by its installer. Nothing for another clone that is not on a branch.
    """

    def __init__(self):
        self.proc = None
        quiet = os.environ.get("TASK_NO_UPDATE_NOTIFIER")
        self.wanted = not quiet and bool(lib_release_tag() or lib_branch())
        if not self.wanted or not self.due():
            return
        try:
            self.proc = subprocess.Popen(["git", "-C", str(LIB), "ls-remote", "--tags", "--refs", "origin", "v*"],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         text=True, env=quiet_git_env(), **DETACHED)
            self.began = time.monotonic()
        except OSError:
            pass

    @staticmethod
    def due():
        last = read_update()
        try:
            age = seconds_since(last["checked"])
        except (KeyError, TypeError, ValueError):
            return True
        return not 0 <= age < (UPDATE_EVERY if last.get("ok") else UPDATE_RETRY)

    def newer(self):
        """The newest release when it is newer than this VERSION, else ""."""
        if not self.wanted:
            return ""
        if self.proc:
            try:
                stdout, _ = self.proc.communicate(timeout=max(0.1, UPDATE_TIMEOUT - (time.monotonic() - self.began)))
                ok = self.proc.returncode == 0
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):  # its own session: git's https helper goes too
                    self.proc.kill() if WINDOWS else os.killpg(self.proc.pid, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.proc.wait(timeout=1)
                stdout, ok = "", False
            self.proc = None
            names = [line.split("\trefs/tags/", 1)[1] for line in stdout.splitlines() if "\trefs/tags/" in line]
            write_update(checked=now(), ok=ok, **({"newest": newest_release(names)} if ok else {}))
        newest = read_update().get("newest") or ""
        return newest if version_key(newest) and version_key(newest) > version_key(VERSION) else ""


def update_line(newest):
    return f"update: {newest} が出ています。`task update` で更新(今は v{VERSION})"


def update_notice(check):
    """`task watch`'s line and notification of a new release: once per release, not at every check."""
    newest = check.newer()
    if not newest or read_update().get("notified") == newest:
        return []
    write_update(notified=newest)
    notify({"event": "update", "version": newest, "reason": update_line(newest).removeprefix("update: ")})
    return [update_line(newest)]


def lib_repo():
    """owner/repo of the clone's origin on GitHub (jyoka/task-hub when origin is not on GitHub)."""
    url = run("git", "-C", LIB, "remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else "jyoka/task-hub"


def releases_url(tag):
    return f"https://github.com/{lib_repo()}/releases/tag/{tag}"


def restart_watch():
    """Restart the `task watch` launchd keeps running, so it runs the new code. Runs in progress keep theirs."""
    if WINDOWS:  # no launchd: the watch is windows/install.ps1 -Watch's scheduled task (or Startup shortcut)
        return restart_windows_watch()
    job = f"gui/{os.getuid()}/{WATCH_LABEL}"
    if not shutil.which("launchctl") or run("launchctl", "print", job).returncode != 0:
        return "watch: not under launchd; if `task watch` runs in a pane, stop it (Ctrl-C) and start it again"
    r = run("launchctl", "kickstart", "-k", job)
    if r.returncode != 0:
        return f"watch: could not restart {WATCH_LABEL} ({(r.stderr or r.stdout).strip()[-200:]}); " \
               f"run `launchctl kickstart -k {job}`"
    return f"watch: restarted {WATCH_LABEL} (launchd)"


def windows_command_path(p):
    """A path for a command line that cmd.exe and PowerShell both run as it is: unquoted (a quoted first word is a
    string to PowerShell), with / (no escapes), and its short 8.3 name when it has a space. Quoted when that fails."""
    p = str(p)
    if " " in p:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(p, buf, len(buf)) and " " not in buf.value:
            p = buf.value
    p = p.replace("\\", "/")
    return f'"{p}"' if " " in p else p


# kiro/workflows/task-hub-events.workflow.json's advice for a slow run; Windows has no herdr tabs
HERDR_STOP = "and that if they want to stop it, Ctrl-C in that task's herdr tab."
WINDOWS_STOP = "and that `task log <id>` shows what it is doing."


def kiro_copy_bytes(key, python=None):
    """What Kiro gets of LIB's hook or workflow (KIRO_COPIES[key]): the file itself; on Windows, each command is
    Python and the script as full paths (Kiro runs it with neither sh nor $HOME, and Windows reads no #! line)."""
    data = (LIB / KIRO_COPIES[key][0]).read_bytes()
    if not WINDOWS:
        return data
    text = data.decode("utf-8")
    py = windows_command_path(python or sys.executable)
    for name in ("task-events-since", "task-events-watch"):
        text = text.replace(json.dumps(f"$HOME/.local/lib/task-hub/kiro/{name}"),
                            json.dumps(f"{py} {windows_command_path(LIB / 'kiro' / name)}", ensure_ascii=False))
    return text.replace(HERDR_STOP, WINDOWS_STOP).encode("utf-8")


# The loop of windows/task-watch.ps1 and the `task watch` it started, stopped (runs in progress go on: they left its
# job), then started again as windows/install.ps1 -Watch registered it. The loop is found by its script's long or
# short name (a shortcut keeps the short one, windows/install.ps1)
WINDOWS_RESTART_WATCH = r"""
$found = @(Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" | Where-Object { $_.CommandLine -and
  ($_.CommandLine.Contains($env:TASK_HUB_WATCH) -or $_.CommandLine.Contains($env:TASK_HUB_WATCH_SHORT)) })
foreach ($p in $found) {
  Get-CimInstance Win32_Process -Filter "ParentProcessId = $($p.ProcessId)" |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
$task = Get-ScheduledTask -TaskName 'task-hub watch' -ErrorAction SilentlyContinue
$lnk = [IO.Path]::Combine([Environment]::GetFolderPath('Startup'), 'task-hub watch.lnk')
if ($task) {
  for ($i = 0; $i -lt 20 -and (Get-ScheduledTask -TaskName 'task-hub watch').State -eq 'Running'; $i++) { Start-Sleep -Milliseconds 250 }
  Start-ScheduledTask -TaskName 'task-hub watch'
  'scheduled'
} elseif ([IO.File]::Exists($lnk)) {
  Invoke-Item -LiteralPath $lnk
  'startup'
} else {
  'none'
}
"""


def restart_windows_watch():
    import ctypes
    script = str(LIB / "windows" / "task-watch.ps1")
    buf = ctypes.create_unicode_buffer(1024)
    short = buf.value if ctypes.windll.kernel32.GetShortPathNameW(script, buf, len(buf)) else script
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_RESTART_WATCH],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       env={**os.environ, "TASK_HUB_WATCH": script, "TASK_HUB_WATCH_SHORT": short})
    how = (r.stdout.strip().splitlines() or [""])[-1]
    if how == "scheduled":
        return "watch: restarted the scheduled task 'task-hub watch'"
    if how == "startup":
        return "watch: restarted from the Startup folder"
    if how == "none":
        return "watch: not set up; windows\\install.ps1 -Watch starts Ready cards without a terminal (docs/windows.md)"
    return f"watch: could not restart it ({(r.stderr or r.stdout).strip()[-200:]}); run windows\\install.ps1 -Watch"


def copy_kiro():
    """Copy Kiro's hook and workflow again where they are installed, when they differ from LIB's."""
    copied = []
    for key, (src, dest) in KIRO_COPIES.items():
        src, dest = LIB / src, Path.home() / dest
        if not src.is_file() or not (dest.exists() or dest.is_symlink()):
            continue  # not installed: Kiro is not used here, or not this part of it
        want = kiro_copy_bytes(key)
        if not dest.is_symlink() and dest.is_file() and dest.read_bytes() == want:
            continue
        temp = dest.with_name(f".{dest.name}.tmp")
        try:
            temp.write_bytes(want)
            temp.replace(dest)  # a link of an earlier manual install becomes a copy too, as Kiro requires
        except OSError as e:
            return [f"kiro: could not copy {home(src)} to {home(dest)} ({e}); copy it by hand (docs/setup.md)"]
        note_install_copy(key, dest)
        copied.append(home(dest))
    return [f"kiro: copied again {', '.join(copied)}"] if copied else []


def cmd_kiro_copy(a):
    import hashlib
    if a["key"] not in KIRO_COPIES:
        fail(f"unknown key {a['key']!r}", "kiro-hook or kiro-workflow", 2)
    want = kiro_copy_bytes(a["key"])
    if not a["to"]:
        print(hashlib.sha256(want).hexdigest())
        return
    dest = Path(a["to"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(f".{dest.name}.tmp")
    temp.write_bytes(want)
    temp.replace(dest)


def note_install_copy(key, dest):
    """kiro/install.sh replaces only the copies whose SHA-256 it recorded: record the new one of a copy it owns."""
    import hashlib
    try:
        m = json.loads(INSTALL_MANIFEST.read_text())
        if not isinstance(m, dict) or (m.get("installed") or {}).get(key) != str(dest):
            return
        m.setdefault("sha256", {})[key] = hashlib.sha256(dest.read_bytes()).hexdigest()
        temp = INSTALL_MANIFEST.with_name(f".{INSTALL_MANIFEST.name}.tmp")
        temp.write_text(json.dumps(m, indent=2) + "\n")
        temp.replace(INSTALL_MANIFEST)
    except (OSError, ValueError, AttributeError):
        pass


# ---------- commands ----------

def cmd_home(_):
    lines, board_ = sync(started_here=True)
    counts = {s: sum(t["status"] == s for t in board_) for s in STATUSES if s != DONE}  # Done is not fetched
    active = board_
    out(f"bin: {home(BIN)}",
        f"description: runs coding agents on the tasks of a GitHub Project, max {parallel()} at once",
        f"board: {board()['url']}",
        "counts: " + ", ".join(f"{s}={n}" for s, n in counts.items()), *lines)
    out(*table("tasks", active, ["id", "title", "status", "agent", "waits_for"]) if active else ["tasks: 0 open tasks"])
    needs_you = StatusLifecycle.needs_user_count(counts)
    out("help[3]:",
        f"  {needs_you} task(s) need you (Backlog to approve, In review, Blocked)",
        "  Move a card to Ready, or run `task start`, to have an agent work on it",
        "  Run `task watch` in a herdr pane to start Ready cards automatically")


def cmd_list(a):
    """The open cards, read only: unlike `task`, it starts nothing and changes nothing (for the /chief agent)."""
    max_age = a["max_age"] if a["max_age"] is not None else str(LIST_MAX_AGE)
    if not max_age.isdigit():
        fail(f"--max-age takes a number of seconds, got {max_age!r}", f"usage: {COMMANDS['list'][3]}", 2)
    max_age = int(max_age)
    if not max_age:  # also the Project's ids: after renaming a field or an option on the board
        forget_board()
    if a["watch"]:
        return list_watch(max_age)
    check = UpdateCheck()  # asks origin while GitHub is read
    lines = list_lines(listed(tasks(max_age=max_age)))
    newest = check.newer()
    out(*lines, *([update_line(newest)] if newest else []))


def listed(board_):
    """The board as `task list` shows it: with [runner] readiness on, each Ready card's readiness as this machine last
    read it (never read here: `task` or `task watch` reads it), and with require why it waits; each card's last
    review (review_findings)."""
    readiness_gate(board_, readiness_mode(), autopilot_repos(), read=False)
    review_findings(board_)
    return board_


def review_findings(board_):
    """Each card's Review field with what its review found, from the digest of its newest Status event on this machine
    (digest reads it from the report's review line), when that review gave the verdict the field has: `needs changes
    (2 blocking, 1 minor)`. A card that ran elsewhere shows the field alone."""
    if not any(t.get("review") for t in board_):
        return
    newest = {}
    for e in all_events():
        if e["event"] in StatusLifecycle.all:
            newest[e.get("id")] = e
    for t in board_:
        d = (newest.get(t["id"]) or {}).get("digest") or {}
        if t.get("review") and d.get("findings") and d.get("verdict") == t["review"]:
            t["review"] += f" ({d['findings'].split(' (')[0]})"


def list_lines(board_):
    """`task list`'s lines; the row of board_[i] is line i + 2. A readiness column only with [runner] readiness on, a
    review column only when the Project has the Review field (a run's review makes it)."""
    counts = {s: sum(t["status"] == s for t in board_) for s in STATUSES if s != DONE}
    cols = ["id", "title", "status", "repo", "agent", "waits_for", *["readiness"] * (readiness_mode() != "off"),
            *["review"] * bool(board(saved_ok=True).get("review"))]
    return ["counts: " + ", ".join(f"{s}={n}" for s, n in counts.items()),
            *(table("tasks", [{**t, "status": shown_status(t)} for t in board_], cols)
              if board_ else ["tasks: 0 open tasks"]),
            f"needs_you: {StatusLifecycle.needs_user_count(counts)} (Backlog to approve, In review, Blocked)"]


CLEAR_SCREEN, MARK, UNMARK = "\033[H\033[2J", "\033[1;33m", "\033[0m"  # ANSI: home + clear, bold yellow, reset


def list_watch(max_age):
    """`task list` again every WATCH_SECONDS, for a pane next to any agent. Read only like `task list`: never sync().

    On a terminal each look redraws the screen, and the rows whose status changed since the last look stand out.
    Piped, each look is appended after an `== <time>` line, without ANSI codes.
    """
    terminal = sys.stdout.isatty()
    last = None  # id -> shown status at the last look that read the board
    try:
        while True:
            try:
                board_ = listed(tasks(max_age=max_age))
                lines = list_lines(board_)
                for i, t in enumerate(board_, 2):
                    if terminal and last is not None and last.get(t["id"]) != shown_status(t):
                        lines[i] = f"{MARK}{lines[i]}{UNMARK}"
                last = {t["id"]: shown_status(t) for t in board_}
            except RuntimeError as e:  # a GitHub hiccup must not end the watch
                lines = [f"error: {e}"]
            if terminal:
                out(f"{CLEAR_SCREEN}== {local_now()} (every {WATCH_SECONDS}s, read only; Ctrl-C to stop)", *lines)
            else:
                out(f"== {local_now()}", *lines)
            if os.environ.get("TASK_WATCH_ONCE"):  # tests
                return
            time.sleep(WATCH_SECONDS)
    except KeyboardInterrupt:
        return


def event_line(e):
    extra = [f"{k} {e[k]}" for k in ("reason", "decision", "pr") if e.get(k)]
    return " | ".join([f"event: #{e['id']} {e['event']}", e.get("title", ""), e.get("repo", ""), *extra])


def event_lines(e, with_digest=False):
    """The event's line and, with --digest, its digest below it (what the line already says is not repeated)."""
    if not with_digest:
        return [event_line(e)]
    if e.get("digest"):
        return [event_line(e), *digest_lines(e["digest"], skip=[k for k in ("reason", "decision", "pr") if e.get(k)])]
    if e.get("event") in (IN_REVIEW, BLOCKED, "replan"):  # written before events carried a digest
        return [event_line(e), f"  digest: none, run `task show {e['id']} --digest`"]
    return [event_line(e)]


def cmd_events(a):
    """What task-hub did lately; with --follow, each new event as one line the moment it is written.

    --follow is for a monitor that wakes its agent on every line it prints.
    --next waits for the next wanted events, prints them and the command that continues from there, and exits:
    for a harness that wakes its agent when a background command ends (the /chief skill uses it). The cursor is a
    line number in the append-only EVENTS file, so nothing that happens between two runs is missed.
    --after N alone does not wait: the wanted events after line N, if any, and the `next:` line, for a hook that
    must return at once (kiro/task-events-since).
    """
    only = {e.strip().lower() for e in (a["only"] or "").split(",") if e.strip()}
    wanted = lambda e: not only or e.get("event", "").lower() in only
    if a["next"] or (a["after"] is not None and not a["follow"]):  # --follow keeps ignoring --after
        return events_next(a, wanted)
    if not a["follow"]:
        recent = event_lines_of(EVENTS.read_text(errors="replace"))[-20:] if EVENTS.exists() else []
        events = []
        for line in recent:
            with contextlib.suppress(ValueError):  # a line a crash cut short
                e = json.loads(line)
                if isinstance(e, dict) and wanted(e):
                    events.append(e)
        out(*([line for e in events for line in event_lines(e, a["digest"])] or [f"events: none yet in {home(EVENTS)}"]))
        return
    pos = EVENTS.stat().st_size if EVENTS.exists() else 0  # only what happens from now on
    # stderr: a monitor wakes its agent for each stdout line, and this one is not an event
    print(f"events: following {home(EVENTS)} (Ctrl-C to stop)", file=sys.stderr, flush=True)
    try:
        while True:
            if EVENTS.exists() and EVENTS.stat().st_size > pos:
                with EVENTS.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                whole = chunk[:chunk.rfind(b"\n") + 1]  # a line still being written waits for the next look
                pos += len(whole)
                for line in event_lines_of(whole.decode(errors="replace")):
                    try:
                        e = json.loads(line)
                        if wanted(e):  # one print: a monitor must see the event and its digest together
                            print("\n".join(event_lines(e, a["digest"])), flush=True)
                    except (ValueError, KeyError):
                        continue
            time.sleep(1)
    except KeyboardInterrupt:
        return


def events_next(a, wanted):
    def whole_lines():  # a line still being written is not counted until it is complete
        return event_lines_of(EVENTS.read_text(errors="replace")) if EVENTS.exists() else []

    if a["after"] is not None and not a["after"].isdigit():
        fail(f"--after takes the number printed on the last `next:` line, got {a['after']!r}", code=2)
    cursor = int(a["after"]) if a["after"] is not None else len(whole_lines())  # none given: from now on
    try:
        while True:
            lines = whole_lines()
            found = []
            for line in lines[cursor:]:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if wanted(e):
                    found += event_lines(e, a["digest"])
            if found or not a["next"]:  # --after alone: what is there now, even nothing
                only = f' --only "{a["only"]}"' if a["only"] else ""
                more = " --digest" if a["digest"] else ""
                wait = " --next" if a["next"] else ""
                out(*found, f"next: task events{wait} --after {len(lines)}{only}{more}")
                return
            cursor = max(cursor, len(lines))
            time.sleep(1)
    except KeyboardInterrupt:
        return


def cmd_watch(_):
    board(), parallel(), autopilot_config()  # fail fast on a bad config
    try:
        trigger_config()
    except ValueError as e:
        fail(str(e), f"fix [triggers] in {home(CONFIG)} (see docs/triggers.md)")
    out(f"watch: checking {board()['url']} every {WATCH_SECONDS}s (Ctrl-C to stop)")
    try:  # afterwards, each card that gets Done checks again
        out(*archive_lines(archive_overflow()))
    except RuntimeError as e:
        out(f"error: archiving old Done cards: {e}")
    while True:
        config.cache_clear()  # pick up edits between checks, while each check uses one configuration
        check = UpdateCheck()
        try:
            lines, board_ = sync()
            lines += check_triggers(board_)  # after the starts: a Ready card made now starts at the next check
        except RuntimeError as e:  # a GitHub hiccup must not end the watch
            lines = [f"error: {e}"]
        except SystemExit:  # a config edited into a bad state meanwhile: fail() said why; the next check reads it again
            lines = []
        except Exception as e:  # a bug must not end it either: under launchd it would fail the same way at every start
            import traceback
            lines = [f"error: unexpected {type(e).__name__}: {e} (please report it with this log)"]
            traceback.print_exc()
        lines += update_notice(check)
        if lines:
            out(f"== {now()}", *lines)
        if os.environ.get("TASK_WATCH_ONCE"):  # tests
            return
        try:
            time.sleep(WATCH_SECONDS)
        except KeyboardInterrupt:
            return


# ---------- intake: cards from the phone (docs/operations.md) ----------

INTAKE_STATE = STATE / "intake.json"  # the last ntfy message handled, so a restart goes on after it
INTAKE_READ_TIMEOUT = 120  # seconds with nothing read: ntfy sends a keepalive every 45, so the connection is gone
INTAKE_RETRY = (5, 300)  # seconds before connecting again: the first, doubled after each failure in a row up to the second
INTAKE_SECRET_MIN = 16  # characters; a short secret can be guessed by anyone who can write to the topic
INTAKE_TITLE_MAX = 72


def intake_config():
    """[intake] as (server, topic, token, secret, default repo), or fail(): the topic is on [notify] ntfy's server."""
    target = ntfy_target()
    i = config()["intake"] if config().has_section("intake") else {}
    topic, secret, repo = (i.get(k, "").strip() for k in ("topic", "secret", "repo"))
    if not target:
        fail(f"task intake needs [notify] ntfy in {home(CONFIG)}: it replies there",
             "add:  [notify]  ntfy = https://ntfy.sh/<topic for notifications>  (see docs/operations.md)")
    if not re.fullmatch(r"[\w-]{1,64}", topic) or topic == target[1]:
        fail(f"[intake] topic must be a topic name other than [notify] ntfy's; got {topic!r}",
             "add:  [intake]  topic = <another hard-to-guess topic>  (see docs/operations.md)")
    if len(secret) < INTAKE_SECRET_MIN or re.search(r"\s", secret):
        fail(f"[intake] secret must be at least {INTAKE_SECRET_MIN} characters without spaces",
             "make one with:  python3 -c \"import secrets; print(secrets.token_urlsafe(16))\"")
    if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        fail(f"[intake] repo must look like owner/name, got {repo!r}")
    return target[0], topic, target[2], secret, repo


def parse_intake(m, secret, default_repo):
    """An ntfy message as (card, reason): card is {title, repo, goal}, or None with why it is not one.
    The message is `<secret> [owner/name:] goal`; the ntfy title, if any, is the card's title.
    reason starts with "ignored" when the secret is missing or wrong: nothing is said back to such a message."""
    import hmac
    word, rest = (re.split(r"\s+", (m.get("message") or "").strip(), maxsplit=1) + [""])[:2]
    if not hmac.compare_digest(word.encode(), secret.encode()):
        return None, "ignored: no secret" if not word else "ignored: wrong secret"
    repo, goal = default_repo, rest.strip()
    if r := re.match(r"([\w.-]+/[\w.-]+):\s*", goal):
        repo, goal = r[1], goal[r.end():].strip()
    if not goal:
        return None, "rejected: the goal is empty"
    if not repo:
        return None, "rejected: no repo (start the goal with `owner/name:`, or set [intake] repo)"
    title = " ".join((m.get("title") or "").split()) or " ".join(goal.splitlines()[0].split())
    if len(title) > INTAKE_TITLE_MAX:
        title = title[:INTAKE_TITLE_MAX - 3].rsplit(" ", 1)[0].rstrip(" ,.;:") + "..."
    sent = datetime.datetime.fromtimestamp(m["time"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") \
        if isinstance(m.get("time"), int) else now()
    return {"title": title, "repo": repo,
            "goal": f"{goal}\n\n---\nFrom the phone (`task intake`, ntfy message {m.get('id', '?')}, {sent})."}, ""


def intake_message(m, secret, default_repo):
    """Handle one ntfy message: a Backlog card and a reply with its link, or a log line saying why not."""
    if (m.get("message") or "").lstrip().startswith(ACTION_WORD):  # a button of an In review notification
        return action_message(m)
    card, reason = parse_intake(m, secret, default_repo)
    mid = m.get("id", "?")
    if reason.startswith("ignored"):  # anyone who knows the topic can write to it: say nothing back
        return [f"intake: {reason} (message {mid}, {len(m.get('message') or '')} chars)"]
    if not card:
        post = ntfy_message("task intake: not registered", reason.removeprefix("rejected: "), 4)
        line = f"intake: {reason} (message {mid})"
    else:
        try:
            t, url = create_task(card["title"], card["repo"], card["goal"], asked=remember_where_asked)
        except (RuntimeError, SystemExit) as e:  # GitHub failed, or fail() wrote why to the log
            post = ntfy_message("task intake: not registered", f"GitHub: {e}" if isinstance(e, RuntimeError)
                                else "see the intake log on the machine", 4)
            line = f"intake: error: message {mid}: {e}"
        else:
            post = ntfy_message(f"#{t['id']} {BACKLOG}: {card['title']}",
                                f"repo: {card['repo']}\nApprove it on the board or with `task start {t['id']}`\n{url}",
                                3, url)
            line = f"intake: #{t['id']} {BACKLOG} in {card['repo']}: {q(card['title'])} {url} (message {mid})"
    if post:
        detach([sys.executable, "-I", "-c", NTFY_POST], {"TASK_HUB_NTFY": json.dumps(post)})
    return [line]


# ---------- the phone's buttons: Merge and Reject on an In review notification (docs/operations.md) ----------

ACTION_KEY = STATE / "action.key"  # the local secret the buttons' tokens are signed with; never leaves this machine
ACTIONS_USED = STATE / "intake-actions.json"  # {"used": {token: time}}: the tokens already acted on, newest last
ACTIONS_USED_MAX = 2000
ACTION_WORD = "task-hub "  # a button's message starts with it; no [intake] secret can (16 characters at least)
ACTION_MESSAGE = r"task-hub (merge|reject) (\d+) ([\w.-]+/[\w.-]+)#(\d+) ([0-9a-f]{40}) ([0-9a-f]{32})"
PR_URL = r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)"


def action_target():
    """Where the buttons post: [intake] topic on [notify] ntfy's server, as (server, topic, token), or None when
    `task intake` is not set up (the notification then has no buttons)."""
    target = ntfy_target()
    try:
        i = config()["intake"] if config().has_section("intake") else {}
        topic, secret = (i.get(k, "").strip() for k in ("topic", "secret"))
    except configparser.Error:
        return None
    if not target or not re.fullmatch(r"[\w-]{1,64}", topic) or topic == target[1] or len(secret) < INTAKE_SECRET_MIN:
        return None
    return target[0], topic, target[2]


def action_key():
    """The key the tokens are signed with: made once, readable only by this user. Linked into place, so two
    processes making it at once both end up with the one that won."""
    with contextlib.suppress(FileNotFoundError):
        if key := ACTION_KEY.read_text().strip():
            return key.encode()
    import secrets
    ACTION_KEY.parent.mkdir(parents=True, exist_ok=True)
    temp = ACTION_KEY.parent / f".{ACTION_KEY.name}.{os.getpid()}.tmp"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
        with contextlib.suppress(FileExistsError):
            os.link(temp, ACTION_KEY)
    finally:
        temp.unlink(missing_ok=True)
    return ACTION_KEY.read_text().strip().encode()


def action_token(action, tid, repo, number, sha):
    """One button's token: an HMAC of what it does, to which card, PR and head commit. A new push changes the head,
    so a button from before it no longer matches."""
    import hashlib
    import hmac
    signed = "\n".join(["task-hub action 1", action, str(tid), repo.lower(), str(number), sha.lower()])
    return hmac.new(action_key(), signed.encode(), hashlib.sha256).hexdigest()[:32]


def review_actions(tid, pr, sha):
    """The In review notification's ntfy buttons: Merge (when [merge] queue = on), Reject and View PR; none without
    `task intake`. Merge and Reject post `task-hub <action> <id> <owner/name>#<n> <sha> <token>` to [intake] topic."""
    m = re.fullmatch(PR_URL, pr)
    if not m or not re.fullmatch(r"[0-9a-f]{40}", sha) or not (target := action_target()):
        return []
    server, topic, token = target

    def button(action, label):
        return {"action": "http", "label": label, "url": f"{server}/{topic}", "method": "POST",
                "headers": {"Authorization": f"Bearer {token}"} if token else {}, "clear": True,
                "body": f"task-hub {action} {tid} {m[1]}#{m[2]} {sha} {action_token(action, tid, m[1], m[2], sha)}"}
    merge = config()["merge"].get("queue", "").strip().lower() == "on"
    return [*([button("merge", "Merge")] if merge else []), button("reject", "Reject"),
            {"action": "view", "label": "View PR", "url": pr, "clear": False}]


def action_message(m):
    """Handle one button: check its token, then queue or reject the PR and say so on [notify] ntfy; a log line."""
    import hmac
    mid = m.get("id", "?")
    a = re.fullmatch(ACTION_MESSAGE, (m.get("message") or "").strip())
    if not a:  # anyone who knows the topic can write to it: say nothing back
        return [f"intake: refused: not a button's message (message {mid}, {len(m.get('message') or '')} chars)"]
    action, tid, repo, number, sha, token = a.groups()
    what = f"{action} #{tid} ({repo}#{number} at {sha[:7]}, message {mid})"
    if not hmac.compare_digest(token, action_token(action, tid, repo, number, sha)):
        return [f"intake: refused: forged token: {what}"]  # nothing said back, as to a wrong secret
    url = f"https://github.com/{repo}/pull/{number}"

    def reply(title, body, priority=3):
        if post := ntfy_message(f"#{tid} {title}", body, priority, url):
            detach([sys.executable, "-I", "-c", NTFY_POST], {"TASK_HUB_NTFY": json.dumps(post)})

    def refuse(why, kind="refused"):
        reply(f"{action} refused", f"{why}\n{url}", 4)
        return [f"intake: {kind}: {why}: {what}"]
    used = read_json(ACTIONS_USED).get("used")
    used = used if isinstance(used, dict) else {}
    if token in used:
        return refuse(f"this button was already used ({used[token]})")
    try:
        if action == "merge" and not merge_config()["queue"]:
            return refuse("the merge queue is off ([merge] queue = on)")
        t = next((x for x in tasks() if x["id"] == tid), None)
        if not t:
            return refuse("the card is not on the board, or is Done")
        pr = pr_view(url)
        if pr.get("state") != "OPEN":
            return refuse(f"the PR is {(pr.get('state') or 'gone').lower()}")
        if pr.get("headRefOid") != sha:
            return refuse("stale: the PR has new commits since this notification; use the newest one")
        e = queue_entry(t)
        if not e or e["pr"].lower() != url.lower():
            return refuse(f"the card's PR is {e['pr'] if e else 'none'}, not this one")
        queued = next((x for x in read_queue() if x["id"] == tid), None)
        if action == "merge":
            if queued:
                done = None
                reply(f"already queued: {t['title']}", f"step {queued.get('step') or 'update'}\n{url}")
            else:
                e, n = enqueue(t)
                done = f"queued {e['pr']} at position {n}"
                reply(f"PR queued: {t['title']}", f"position {n} in the merge queue of {e['repo']}\n{url}")
        else:
            if t["status"] not in (IN_REVIEW, WAIT_FOR_MERGE, BLOCKED) or t["running"]:
                return refuse(f"the card is {t['status']}{' and running' if t['running'] else ''}")
            gh("pr", "close", url, "--comment", f"Rejected from the phone (task-hub, task {board()['issues']}#{tid}).")
            if queued:
                queue_drop(tid)
            comment(t, f"{MERGE_MARK}\n\n## Rejected\n\nThe PR {url} was rejected from the phone (`task intake`) "
                       f"and closed.\n\nRun the task again with what to change (it opens a new PR), or "
                       f"`task done {tid}` to drop it.")
            set_status(t, BLOCKED, reason="rejected from the phone: the PR was closed")
            done = f"closed {url}, the card is {BLOCKED}"
            reply(f"rejected: {t['title']}", f"the PR was closed and the card is {BLOCKED}\n{url}")
    except ValueError as x:  # enqueue: it cannot be queued
        return refuse(x.args[0])
    except (RuntimeError, SystemExit) as x:  # GitHub failed, or fail() wrote why to the log
        return refuse(f"GitHub: {x}" if isinstance(x, RuntimeError) else "see the intake log on the machine", "error")
    if done:  # acted on: the same button never acts again
        used[token] = now()
        write_atomic(ACTIONS_USED, json.dumps({"used": dict(list(used.items())[-ACTIONS_USED_MAX:])}))
        return [f"intake: {done}: {what}"]
    return [f"intake: already queued: {what}"]


def intake_stream(server, topic, token, since):
    """The messages ntfy sends on topic from since (a message id or a Unix time), as they come."""
    import urllib.request
    url = f"{server}/{topic}/json?{urlencode({'since': since})}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=INTAKE_READ_TIMEOUT) as r:
        for line in r:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if isinstance(m, dict) and m.get("event") == "message":
                yield m


def cmd_intake(_):
    import http.client
    server, topic, token, secret, repo = intake_config()
    board()  # fail fast on a bad config
    since = (read_json(INTAKE_STATE) or {}).get("since") or str(int(time.time()))  # the first start: from now on
    out(f"intake: listening on {server}/{topic} for new cards (Ctrl-C to stop)")
    delay = INTAKE_RETRY[0]
    while True:
        try:
            for m in intake_stream(server, topic, token, since):
                delay = INTAKE_RETRY[0]
                since = str(m.get("id") or since)
                write_atomic(INTAKE_STATE, json.dumps({"since": since}))  # before the card: never two of one message
                out(*intake_message(m, secret, repo))
            why = "the server closed the connection"
        except (OSError, http.client.HTTPException) as e:  # down, no network, a wrong token (HTTPError), a timeout
            why = f"{type(e).__name__}: {e}"
        except KeyboardInterrupt:
            return
        if os.environ.get("TASK_WATCH_ONCE"):  # tests
            return out(f"intake: {why}")
        out(f"intake: {why}; connecting again in {delay}s")
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            return
        delay = min(delay * 2, INTAKE_RETRY[1])


def cmd_update(_):
    """Bring LIB to origin's newest release, then do what an update needs (docs/setup.md): restart the launchd
    `task watch` and copy Kiro's hook and workflow again. Changes nothing when the clone has changes of its own."""
    lib = home(LIB)
    if run("git", "-C", LIB, "rev-parse", "--show-prefix").stdout.strip() or not (LIB / ".git").exists():
        fail(f"{lib} is not a git clone of task-hub; nothing changed", "install it as docs/setup.md says")
    branch = lib_branch()
    if not branch:
        current = lib_release_tag()
        if not current:
            fail(f"{lib} is not on a branch or on a release tag from v{'.'.join(map(str, EASY_SETUP_FIRST))}; "
                 "nothing changed",
                 f"see `git -C {lib} status`, or install it again as docs/setup.md says")
        return update_by_installer(current)
    dirty = run("git", "-C", LIB, "status", "--porcelain", "--untracked-files=no").stdout.splitlines()
    if dirty:
        fail(f"{lib} has uncommitted changes ({', '.join(line[3:] for line in dirty[:5])}); nothing changed",
             f"see them with `git -C {lib} status`; commit them or `git -C {lib} stash` them, "
             "then run `task update` again")
    fetch_lib()
    newest = newest_release(run("git", "-C", LIB, "tag", "-l", "v*").stdout.split())
    if not newest:
        fail("origin has no v<MAJOR>.<MINOR>.<PATCH> tag yet; nothing changed", "releases: docs/release.md")
    write_update(checked=now(), ok=True, newest=newest)
    target = run("git", "-C", LIB, "rev-parse", f"refs/tags/{newest}^{{commit}}").stdout.strip()
    contains = lambda a, b: run("git", "-C", LIB, "merge-base", "--is-ancestor", a, b).returncode == 0
    before = lib_version()
    if contains(target, "HEAD"):  # at the release, or past it on main
        lines = [f"up_to_date: {before} (newest release {newest})"]
    elif contains("HEAD", target):
        r = run("git", "-C", LIB, "merge", "--ff-only", "-q", target)
        if r.returncode != 0:
            fail(f"could not move {branch} to {newest}: {(r.stderr or r.stdout).strip()[-300:]}; nothing changed",
                 f"see `git -C {lib} status`")
        lines = [f"updated: {before} -> {lib_version()} ({newest})", restart_watch()]
    else:
        base = run("git", "-C", LIB, "merge-base", "HEAD", target).stdout.strip()
        own = run("git", "-C", LIB, "log", "--format=%h %s", f"{target}..HEAD").stdout.splitlines()
        fail(f"{lib} has {len(own)} commit(s) of its own that {newest} does not have "
             f"({'; '.join(own[:3])}{'; ...' if len(own) > 3 else ''}); nothing changed",
             f"keep them on a branch and take {branch} back to where it left the releases, then run `task update` "
             f"again: git -C {lib} branch local-changes && git -C {lib} reset -q --hard {base[:12]}")
    out(*lines, *copy_kiro(), f"release_notes: {releases_url(newest)}")


def fetch_lib():
    """origin's commits and tags into LIB, or fail: nothing is changed then."""
    lib = home(LIB)
    try:
        r = subprocess.run(["git", "-C", str(LIB), "fetch", "-q", "--tags", "origin"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=quiet_git_env(), timeout=120)
        why = "" if r.returncode == 0 else ((r.stderr or r.stdout).strip().splitlines() or ["git fetch failed"])[-1]
    except subprocess.TimeoutExpired:
        why = "timed out"
    if why:
        fail(f"could not fetch from origin: {why}; nothing changed",
             f"check the network (VPN, proxy) and that `git -C {lib} fetch` works, then run `task update` again")


def update_by_installer(current):
    """An installer's clone (on the release tag current): the newest release's own installer does the update,
    as 「セットアップして」 again would. It runs from a copy of that release (a shared clone of LIB, nothing
    downloaded), not from LIB, which it changes while it runs. The watch is kept as it was (the installer starts it
    again with the new code). Its lines are the person's to read; it says itself what to do when it stops."""
    lib = home(LIB)
    fetch_lib()
    newest = newest_release(run("git", "-C", LIB, "tag", "-l", "v*").stdout.split()) or current
    write_update(checked=now(), ok=True, newest=newest)
    if version_key(newest) <= version_key(current):
        out(f"up_to_date: {current} (newest release {newest})")
        return
    try:
        installed = json.loads(INSTALL_MANIFEST.read_text()).get("installed") or {}
    except (OSError, ValueError, AttributeError):
        installed = {}
    import tempfile
    snapshot = Path(tempfile.mkdtemp(prefix="task-hub-update-"))
    try:
        copy = snapshot / "task-hub"
        for args in (["clone", "-q", "--shared", "--no-checkout", str(LIB), str(copy)],
                     ["-C", str(copy), "checkout", "-q", "--detach", f"refs/tags/{newest}"]):
            r = run("git", *args)
            if r.returncode:
                fail(f"could not take {newest} out of {lib}: {(r.stderr or r.stdout).strip()[-300:]}; nothing changed",
                     "run `task update` again; if it goes on, say 「セットアップして」 in Kiro's chat")
        if WINDOWS:
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(copy / "windows" / "install.ps1"), *(["-Watch"] if installed.get("watch") else [])]
        else:
            cmd = ["sh", str(copy / "kiro" / "install.sh"),
                   *(["--with-launchd", "--start-launchd"] if installed.get("launchd") else [])]
        print(f"update: {current} -> {newest}, by {newest}'s installer", flush=True)
        code = subprocess.run(cmd, stdin=subprocess.DEVNULL).returncode
    finally:
        shutil.rmtree(snapshot, onerror=lambda f, path, _: (os.chmod(path, 0o700), f(path)) if WINDOWS else None)
    after = lib_release_tag() or lib_version()
    if code:
        fail(f"{newest}'s installer stopped (exit {code}); {lib} is at {after}",
             "do what its 次にすること line says, then run `task update` again")
    lines = [f"updated: {current} -> {after} ({newest})"]
    if not WINDOWS and installed.get("launchd"):  # the plist may be unchanged, but the code it runs is not
        lines.append(restart_watch())
    out(*lines)


def cmd_show(a):
    if a["full"] and a["digest"]:
        fail("--full and --digest do not go together", "usage: task show <id> [--full | --digest]", 2)
    t = get(a["id"])
    i = issue(t)
    if a["digest"]:
        return show_digest(t, i)
    lines = ["task:"] + [f"  {k}: {q(shown_status(t) if k == 'status' else t.get(k))}"
                         for k in ("id", "title", "status", "repo", "base", "agent", "url", "pr") if t.get(k)] \
        + ([f"  waits_for: {q(t['waits_for'])}"] if t.get("waits_for") else [])
    body = i["body"].strip() + ("\n\n" + i["report"].replace(REPORT_MARK, "").strip() if i["report"] else "") \
        + ("\n\n" + i["replans"][-1].replace(REPLAN_MARK, "").strip() if i["replans"] else "")
    if len(body) > 1500 and not a["full"]:
        lines += ["body: |", *("  " + l for l in body[:1500].splitlines()),
                  f"  ... (truncated, {len(body)} chars total)",
                  f"help: Run `task show {t['id']} --full` for the full text"]
    else:
        lines += ["body: |", *("  " + l for l in body.splitlines())]
    out(*lines)


def show_digest(t, i):
    """The same digest the events carry, rebuilt from the Issue: for events written without one, or to check later."""
    report = i["report"]
    blocked = section(report, "Blocked").split("\n")[0].strip()
    replan = i["replans"][-1] if i["replans"] else ""
    if not blocked or f"\nBlocked: {blocked}\n" not in replan:  # a replan of an earlier block is out of date
        replan = ""
    d = digest(report=report, replan=replan)
    out("task:", *[f"  {k}: {q(t.get(k))}" for k in ("id", "title", "status", "repo") if t.get(k)],
        *(["digest:", *digest_lines(d)] if d else ["digest: none, no report on the Issue yet"]))


def cmd_log(a):
    t = {"id": a["id"], **load_run(a["id"])}
    if not t.get("log") or not Path(t["log"]).exists():
        out(f"log: task {t['id']} has not run on this machine")
        return
    lines = Path(t["log"]).read_text(errors="replace").splitlines()
    shown = lines if a["full"] else lines[-40:]
    out(f"log: {home(t['log'])} ({len(lines)} lines)", *shown,
        *([f"help: Run `task log {t['id']} --full` for all lines"] if len(lines) > len(shown) else []))


def cmd_open(a):
    """Open this task's worktree in the IDE named by [ide] open, or, if none is set, print its path."""
    t = {"id": a["id"], **load_run(a["id"])}
    wt = t.get("worktree")
    if not wt:
        fail(f"task {t['id']} has no worktree on this machine (it has not run here)",
             f"run it here with `task start {t['id']}`, or open it on the machine that ran it")
    if not Path(wt).exists():
        fail(f"the worktree for task {t['id']} is gone: {home(wt)}",
             "it was cleaned up after the task finished; re-run the task to recreate it")
    template = config()["ide"].get("open", "").strip()
    if not template:
        out(home(wt), f"help: set  [ide]  open = code {{path}}  in {home(CONFIG)} to open it in your IDE")
        return
    try:
        cmd = [wt if part == "{path}" else part for part in shlex.split(template)]
    except ValueError as e:  # a quote left open
        fail(f"[ide] open in {home(CONFIG)} cannot be read: {e}", "check the quotes in  [ide]  open")
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **DETACHED)
    except OSError as e:
        fail(f"could not run [ide] open ({cmd[0]}): {e}", f"check  [ide]  open  in {home(CONFIG)}")
    out(f"opening {home(wt)} with: {template}")


def os_description():
    """This machine for a bug report: the OS, its version and CPU, and the Python that runs task."""
    import platform
    if sys.platform == "darwin":
        name = f"macOS {platform.mac_ver()[0]}"
    elif WINDOWS:
        name = f"Windows {platform.release()} ({platform.version()})"
    else:
        name = f"{platform.system()} {platform.release()}"
    return f"{name} {platform.machine()}, Python {platform.python_version()}"


def open_in_browser(url):
    """Open the URL in the default browser; False when this machine has nothing to open it with."""
    try:
        if WINDOWS:
            os.startfile(url)  # not `cmd /c start`: cmd would cut the URL at its first &
            return True
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if not shutil.which(opener):
            return False
        subprocess.Popen([opener, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **DETACHED)
        return True
    except OSError:
        return False


def cmd_feedback(a):
    """Open the form for a bug report (or, with --feature, a feature request) on task-hub's own repository, with
    the version and OS filled in. The URL is always printed: an opener can fail after it starts (no display)."""
    kind = "feature" if a["feature"] else "bug"
    fields = {"template": FEEDBACK_FORMS[kind]}
    if kind == "bug":  # each name is an id in the form; GitHub fills those fields from the URL
        fields.update(version=VERSION, os=os_description())
    url = f"https://github.com/{lib_repo()}/issues/new?{urlencode(fields, quote_via=quote)}"
    opened = open_in_browser(url)
    out("feedback:", f"  form: {kind}", f"  url: {url}", f"  opened: {'true' if opened else 'false'}",
        *([] if opened else ["help: open the url in your browser to write the report"]))


def cmd_stats(_):
    """What the runs on this machine came to: outcomes, reviews, retries, why cards blocked, replanner decisions,
    and what each agent launch used."""
    runs = []
    for line in (METRICS.read_text().splitlines() if METRICS.exists() else []):
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    slow = f"slow: {len(events_named('slow'))} run(s) got a `slow` event (ran much longer than usual for their agent)"
    budget = f"over budget: {len(events_named('over budget'))} `over budget` event(s) (a run used more than its " \
             "Goal's Budget, or than usual for its agent; one event per measure and run)"
    checks = checks_line()
    if not runs:  # the first run can be slow before any run has finished
        out(f"stats: 0 runs recorded yet in {home(METRICS)} (task-hub records each run from 0.6 on)", slow, budget,
            *checks)
        return

    def counts(name, key, values):
        seen = {}
        for v in values:
            seen[v] = seen.get(v, 0) + 1
        return table(name, [{key: k, "runs": n} for k, n in sorted(seen.items(), key=lambda kv: -kv[1])], [key, "runs"])

    reviewed = [r for r in runs if r.get("reviews")]
    retried = [r for r in reviewed if r.get("retried")]
    by_agent = {}
    for r in runs:
        by_agent.setdefault(r.get("agent") or "?", []).append(r)
    agents = [{"agent": name, "runs": len(rs), "in_review": sum(r["status"] == IN_REVIEW for r in rs),
               "median_seconds": median(r.get("seconds", 0) for r in rs)}
              for name, rs in sorted(by_agent.items())]
    sized = sorted((r for r in runs if r.get("files")), key=lambda r: -(r["added"] + r["removed"]))
    largest = [{"id": r["id"], "title": r["title"], "lines": r["added"] + r["removed"], "files": r["files"]}
               for r in sized[:3]]
    sizes = sorted(r["added"] + r["removed"] for r in sized)
    # usage: one entry per agent launch; token fields only where the agent CLI's records have them (Claude Code's),
    # credits only where they have those (Kiro's): a Kiro launch is not a launch of 0 tokens
    measured = [{"id": r["id"], "title": r["title"], "tokens": sum(tokens(u) for u in r["usage"]),
                 "calls": sum(u.get("calls", 0) for u in r["usage"] if "output" in u),
                 "subagent_calls": sum(u.get("subagent_calls", 0) for u in r["usage"])}
                for r in runs if any("output" in u for u in r.get("usage") or [])]
    credited = [round(sum(u["credits"] for u in r["usage"] if "credits" in u), 2)
                for r in runs if any("credits" in u for u in r.get("usage") or [])]
    costed = [round(sum(u["cost"] for u in r["usage"] if "cost" in u), 4)
              for r in runs if any("cost" in u for u in r.get("usage") or [])]
    by_role = {}
    for u in (u for r in runs for u in r.get("usage") or []):
        by_role.setdefault(u.get("role") or "?", []).append(u)
    roles = [{"role": role, "launches": len(us), "measured": sum("output" in u for u in us),
              "median_seconds": median(u.get("seconds", 0) for u in us),
              "median_tokens": median(tokens(u) for u in us if "output" in u)}
             for role, us in sorted(by_role.items(), key=lambda kv: -len(kv[1]))]
    heaviest = sorted(measured, key=lambda r: -r["tokens"])[:3]
    unmeasured = f"{len(runs) - len(measured)} runs without usage in tokens: recorded before it was, or by an " \
                 f"agent whose records have none (Claude Code's and pi's have them; Kiro's have credits)"
    out(f"stats: {len(runs)} runs since {runs[0]['started'][:10]} ({home(METRICS)})",
        *counts("outcomes", "status", [r["status"] for r in runs]),
        *table("agents", agents, ["agent", "runs", "in_review", "median_seconds"]),
        f"reviews: {len(reviewed)} reviewed runs, {len(retried)} sent back "
        f"({plural(sum(r.get('retries') or 1 for r in retried), 'retry', 'retries')} in all), "
        f"{sum(r['reviews'][-1] == 'pass' for r in retried)} of those passed after being sent back",
        *(counts("first_verdicts", "verdict", [r["reviews"][0] for r in reviewed]) if reviewed else []),
        *counts("review_stops", "why", [r["review_stop"] for r in reviewed if r.get("review_stop")]),
        *counts("blocked_by", "reason", [r["blocked_by"] for r in runs if r["status"] == BLOCKED]),
        *counts("replanner", "decision", [r["replan"] for r in runs if r.get("replan")]),
        slow,
        budget,
        *checks,
        *([f"size: median {sizes[len(sizes) // 2]} changed lines per PR over {len(sizes)} runs "
           f"(a PR you can review in 10 to 15 minutes is a few hundred lines)",
           *table("largest", largest, ["id", "title", "lines", "files"])] if sized else []),
        f"tokens: {len(measured)} of {len(runs)} runs measured"
        + (f", median {median(r['tokens'] for r in measured)} tokens and {median(r['calls'] for r in measured)} "
           f"calls per run" if measured else "") + (f" ({unmeasured})" if len(runs) > len(measured) else ""),
        *([f"credits: {len(credited)} of {len(runs)} runs measured, median {median(credited):.2f} credits per run"]
          if credited else []),
        *([f"cost: {len(costed)} of {len(runs)} runs measured, median ${median(costed):.4f} per run (as pi "
           "works it out from the model's prices)"] if costed else []),
        *(table("roles", roles, ["role", "launches", "measured", "median_seconds", "median_tokens"]) if roles else []),
        *(table("heaviest", heaviest, ["id", "title", "tokens", "calls", "subagent_calls"]) if heaviest else []))


def checks_line():
    """`task check`'s line of `task stats`, from CHECKS; none before the first check."""
    checks = []
    for line in (CHECKS.read_text(errors="replace").splitlines() if CHECKS.exists() else []):
        with contextlib.suppress(ValueError):
            r = json.loads(line)
            if isinstance(r, dict) and r.get("verdict"):
                checks.append(r)
    if not checks:
        return []
    verdicts = {v: sum(r["verdict"] == v for r in checks) for v in (*READINESS_VERDICTS, "blocked")}
    measured = [sum(tokens(u) for u in r.get("usage") or [] if "output" in u)
                for r in checks if any("output" in u for u in r.get("usage") or [])]
    return [f"checks: {len(checks)} `task check` runs ({', '.join(f'{v} {n}' for v, n in verdicts.items())}), "
            f"median {span(median(r.get('seconds') or 0 for r in checks))}"
            + (f" and {short(median(measured))} tokens" if measured else "") + f" each ({home(CHECKS)})"]


def median(values):
    """The middle value (the upper one of an even count), or "" when there are none."""
    values = sorted(values)
    return values[len(values) // 2] if values else ""


def cmd_new(a):
    if not a["title"] or not a["repo"]:
        fail("--title and --repo are required",
             'task new --title "..." --repo owner/name [--base branch] [--agent name] [--research] [--blocked-by 12,14] (--goal "..." | --goal-file path)', 2)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", a["repo"]):
        fail(f"--repo must look like owner/name, got {a['repo']!r}", code=2)
    if a["base"] and check_base(a["base"]):
        fail(check_base(a["base"]), code=2)
    check_agent(a["agent"])
    blockers = [x.strip().lstrip("#") for x in (a["blocked_by"] or "").split(",") if x.strip()]
    if not all(x.isdigit() for x in blockers):
        fail(f"--blocked-by takes task numbers, e.g. 12 or 12,14; got {a['blocked_by']!r}", code=2)
    try:  # a goal written with PowerShell 5.1's `>` is UTF-16
        goal = read_agent_file(Path(a["goal_file"])) if a["goal_file"] else (a["goal"] or "")
    except OSError as e:
        fail(f"cannot read --goal-file {a['goal_file']}: {e.strerror or e}", code=2)
    if not goal.strip():
        fail("goal is empty", "pass --goal \"...\" or --goal-file path", 2)
    b = board()
    blocker_ids = {}
    for n in blockers:  # checked before the Issue exists: a typo must not leave a task that waits for nothing
        try:
            blocker_ids[n] = gh_json("issue", "view", n, "--repo", b["issues"], "--json", "id")["id"]
        except RuntimeError:
            fail(f"--blocked-by {n}: no Issue #{n} in {b['issues']}")
    if a["research"]:
        research_label()
    t, url = create_task(a["title"], a["repo"], goal, base=a["base"], agent=a["agent"],
                         labels=[RESEARCH_LABEL] if a["research"] else [], blocker_ids=blocker_ids,
                         asked=remember_where_asked)
    out("task:", f"  id: {t['id']}", f"  status: {BACKLOG}", f"  url: {url}",
        *([f"  blocked_by: {', '.join('#' + n for n in blockers)} (it starts only after they are done)"] if blockers else []),
        "help[1]:", "  Move the card to Ready, or run `task start`, when you want an agent to pick it up")


def research_label():
    """Make sure the board's Issue repo has the research label (`--force`: the same call when it is there)."""
    gh("label", "create", RESEARCH_LABEL, "--repo", board()["issues"], "--force",
       "--description", "task-hub: the deliverable is the agent's report", "--color", "0E8A16")


def create_task(title, repo, goal, base="", agent="", labels=(), blocker_ids=None, asked=None, created=None):
    """Make the Issue, put it on the Project in Backlog, and fill its fields: `task new` and the triggers.

    asked(t): just after the card exists (where it was asked for); created(url): just after the Issue exists, before
    anything else can fail, so a trigger notes its occurrence even when the card is not complete."""
    b = board()
    f = DATA / f"new-issue-{os.getpid()}.md"  # `task new` and the watch's triggers may make one at the same time
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(goal.strip() + "\n")
    try:
        url = gh("issue", "create", "--repo", b["issues"], "--title", title, "--body-file", f,
                 *(a for label in labels for a in ("--label", label))).strip().splitlines()[-1]
    finally:
        f.unlink(missing_ok=True)
    if created:
        created(url)
    item = gh_json("project", "item-add", b["number"], "--owner", b["owner"], "--url", url, "--format", "json")
    t = {"id": url.rstrip("/").rsplit("/", 1)[-1], "item": item["id"], "title": title, "repo": repo, "status": None}
    if asked:
        asked(t)
    if blocker_ids:
        this = gh_json("issue", "view", t["id"], "--repo", b["issues"], "--json", "id")["id"]
        for blocker in blocker_ids.values():
            graphql(ADD_BLOCKED_BY, issue=this, blocker=blocker)
    set_status(t, BACKLOG)
    set_text(t, "Target repo", repo)
    if base:
        set_text(t, "Base branch", base)
    if agent:
        set_text(t, "Agent", agent)
    return t, url


def pick(candidates):
    """Let the human choose a task in the terminal: fzf if installed, else a numbered menu."""
    if shutil.which("fzf"):
        lines = "\n".join(f"{t['id']}\t{t['status']:<8}\t{t['title']}\t{t['repo']}" for t in candidates)
        r = subprocess.run(["fzf", "--height", "40%", "--reverse", "--prompt", "start task> ",
                            "--delimiter", "\t", "--with-nth", "2.."], input=lines, stdout=subprocess.PIPE, text=True)
        return r.stdout.split("\t", 1)[0].strip() or None
    for n, t in enumerate(candidates, 1):
        print(f"  {n}) #{t['id']} [{t['status']}] {t['title']} ({t['repo']})")
    try:
        choice = input("start which? (number, empty to cancel): ").strip()
    except EOFError:  # Ctrl-D
        return None
    return candidates[int(choice) - 1]["id"] if choice.isdigit() and 0 < int(choice) <= len(candidates) else None


def cmd_start(a):
    check_agent(a["agent"])
    tid = a.get("id")
    if tid is None:
        candidates = [t for t in tasks() if t["status"] in StatusLifecycle.startable_by_human]
        if not candidates:
            out("start: 0 Backlog or Blocked tasks to start")
            return
        if len(candidates) == 1:
            tid = candidates[0]["id"]
        elif sys.stdin.isatty() and sys.stdout.isatty():
            tid = pick(candidates)
            if not tid:
                out("start: cancelled")
                return
        else:
            out(*table("candidates", candidates, ["id", "title", "status"]))
            fail("several tasks can be started; say which", "task start <id>", 2)
    t = get(tid)
    if t["status"] in (READY, IN_PROGRESS) and not a["agent"]:
        out(f"task: #{t['id']} already {t['status']} (no-op)")
        return
    if t["status"] not in StatusLifecycle.startable_explicitly:
        fail(f"task {t['id']} is {t['status']}; only Backlog or Blocked tasks can be started")
    parallel()  # a bad config stops before the card moves
    if a["agent"]:
        set_text(t, "Agent", a["agent"])
    set_status(t, READY)
    lines, board_ = sync(started_here=True)
    t = next((card for card in board_ if card["id"] == t["id"]), t)
    out("task:", f"  id: {t['id']}", f"  title: {q(t['title'])}", f"  status: {t['status']}",
        *([f"  waits_for: {t['waits_for']} (it starts by itself once they are done)"] if t["waits_for"] else []), *lines)


def cmd_done(a):
    t = get(a["id"])
    if t["status"] == DONE:
        out(f"task: #{t['id']} already Done (no-op)")
        return
    # the lock: a sync may be resuming the run (its pane was closed) right now
    with launch_lock(t["id"]) as mine:
        if t["running"] or not mine or alive(load_run(t["id"])):  # whatever the Status: a replanner runs after Blocked
            fail(f"task {t['id']} is still running ({t.get('stage') or 'starting'})",
                 "stop the agent in its herdr workspace first, then retry")
        left = cleanup(t)
    i = issue(t)
    t["link"] = i["link"]  # read anyway: closing the team's copy too costs no other read
    t["link_project"] = i["link_project"]
    if i["state"] != "CLOSED":
        gh("issue", "close", t["id"], "--repo", board()["issues"])
    to_team(t, "the close", lambda team, n: team.close(n))
    set_status(t, DONE)
    try:
        archived = archive_lines(archive_overflow())
    except RuntimeError as e:  # the next card that gets Done tries again
        archived = [f"error: archiving old Done cards: {e}"]
    out("task:", f"  id: {t['id']}", f"  status: {DONE}",
        *([f"cleanup: {left}; `task` or `task watch` tries again"] if left else []), *archived)


def enqueue(t):
    """`task merge <id>` and the phone's Merge button: the card's PR joins the merge queue, as (entry, position).
    Raises ValueError(why, what to do) when it cannot; the caller has made sure it is not queued yet."""
    if t["status"] not in (IN_REVIEW, WAIT_FOR_MERGE, BLOCKED):
        raise ValueError(f"task {t['id']} is {t['status']}; only In review, {WAIT_FOR_MERGE} or Blocked tasks with a PR "
                         "can be queued")
    if t["running"]:
        raise ValueError(f"task {t['id']} is still running ({t.get('stage') or 'starting'})",
                         "queue it once it has finished")
    e = queue_entry(t)
    if not e:
        raise ValueError(f"task {t['id']} has no open PR to merge",
                         "a research task's report has nothing to merge: `task done` it")
    n = change_queue(lambda q: q.append(e) or position(q, e))
    column = queue_column()
    if t["status"] != column:
        set_status(t, column)
    emit(t, "queued", pr=e["pr"], reason=f"position {n} in the merge queue of {e['repo']}")
    return e, n


def cmd_merge(a):
    """Approve a PR for the merge queue (or, with --cancel, take it out); no id: the queue as it is."""
    if not merge_config()["queue"]:
        fail("the merge queue is off", f"set  [merge]  queue = on  in {home(CONFIG)} (docs/operations.md)")
    if a.get("id") is None:
        q = read_queue()
        out(*(table("queue", [{**e, "position": position(q[:n + 1], e)} for n, e in enumerate(q)],
                    ["position", "id", "repo", "step", "pr"]) if q else ["queue: empty"]))
        return
    t = get(a["id"])
    queued = next((e for e in read_queue() if e["id"] == t["id"]), None)
    if a["cancel"]:
        if not queued:
            out(f"merge: #{t['id']} is not queued (no-op)")
            return
        queue_drop(t["id"])
        if t["status"] == WAIT_FOR_MERGE:
            set_status(t, IN_REVIEW)
        out("merge:", f"  id: {t['id']}", "  queued: no", f"  status: {t['status']}")
        return
    if queued:
        out(f"merge: #{t['id']} already queued, step {queued.get('step') or 'update'} (no-op)")
        return
    try:
        e, n = enqueue(t)
    except ValueError as x:
        fail(*x.args)
    out("merge:", f"  id: {t['id']}", f"  pr: {e['pr']}", f"  status: {t['status']}", f"  position: {n}",
        "help[1]:", f"  `task watch` keeps it up to date with its base and merges it once its checks pass; "
                    f"`task merge {t['id']} --cancel` takes it out")


def cmd_share(a):
    to, project = a["to"] or "", a["project"] or ""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", to):
        fail(f"--to must be the team's repo as owner/name, got {to!r}", f"usage: {COMMANDS['share'][3]}", 2)
    if project and not re.fullmatch(r"[\w.-]+/\d+", project):
        fail(f"--project must look like owner/number, got {project!r}", f"usage: {COMMANDS['share'][3]}", 2)
    t = get(a["id"])
    i = issue(t)
    if i["link"]:  # the same share again changes nothing; one task has one copy
        out(f"share: #{t['id']} already shared as {i['link']} (no-op)",
            f"  issue: https://github.com/{i['link'].replace('#', '/issues/')}", *share_pr(t, i["link"]))
        return
    try:
        settings = share_config(to)
    except RuntimeError as e:
        fail(str(e), f"fix it in {home(CONFIG)}")
    team = TeamGitHub(to, project or settings["project"])
    column = team.prepare(t["status"], settings)
    try:
        number, url = team.create_issue(settings["title"] + t["title"], share_body(i["body"]))
    except RuntimeError as e:
        fail(f"cannot create an Issue in {to}: {e}",
             f"check that `gh auth status` shows an account that can open Issues in {to}; nothing was changed")
    ref = team.ref(number)
    try:  # first: from now on `task share` finds the copy, whatever fails after it
        comment(t, f"{LINK_MARK}\nShared to {ref}: {url}\n" +
                (f"Project: {team.project}\n" if team.project else ""))
    except RuntimeError as e:
        fail(f"made {url}, but could not note it on #{t['id']}: {e}",
             f"close {url} and run this again, or comment `{LINK_MARK} {ref}` on #{t['id']} by hand")
    try:
        for body in i["own_comments"]:
            team.comment(number, body)
        team.add_card(url)
        lines = share_pr(t, ref)
    except RuntimeError as e:
        fail(f"made and linked {url}, but then: {e}",
             "add the rest by hand on GitHub (task-hub's reports, the card on the Project); "
             "`task share` will not make another Issue")
    out("share:", f"  id: {t['id']}", f"  issue: {url}", f"  comments: {len(i['own_comments'])}",
        *([f"  project: {team.project}", f"  status: {column or '(none)'}"] if team.card else []), *lines,
        *([f"help: the team's Project has no column for {t['status']}: set  [share]  status.{t['status']} = <column>"]
          if team.card and not column else []))


COMMANDS = {
    # name: (handler, positional args (optional ones end with ?), flags(name -> takes_value), help)
    "start": (cmd_start, ["id?"], {"agent": True},
              "task start [<id>] [--agent name]  # approve a Backlog task or re-run a Blocked one; no id = pick one"),
    "watch": (cmd_watch, [], {}, f"task watch  # start Ready cards automatically (checks every {WATCH_SECONDS}s)"),
    "intake": (cmd_intake, [], {}, "task intake  # turn messages on the [intake] ntfy topic into Backlog cards (from "
               "the phone)"),
    "show": (cmd_show, ["id"], {"full": False, "digest": False},
             "task show <id> [--full | --digest]  # the Issue and its latest report; --digest: only what to decide from"),
    "log": (cmd_log, ["id"], {"full": False}, "task log <id> [--full]  # the run's output on this machine"),
    "open": (cmd_open, ["id"], {},
             "task open <id>  # open the task's worktree in your IDE ([ide] open), or print its path"),
    "new": (cmd_new, [], {"title": True, "repo": True, "base": True, "agent": True, "goal": True, "goal-file": True,
                          "research": False, "blocked-by": True},
            'task new --title "..." --repo owner/name [--base branch] [--agent name] [--research] [--blocked-by 12,14] '
            '(--goal "..." | --goal-file path)'),
    "done": (cmd_done, ["id"], {}, "task done <id>  # close or cancel by hand (a merged PR closes it automatically)"),
    "merge": (cmd_merge, ["id?"], {"cancel": False},
              "task merge [<id>] [--cancel]  # approve the task's PR for the merge queue ([merge] queue = on): `task watch` "
              "merges its base into it (an agent fixes conflicts), waits for its checks and merges it, one PR per repo at "
              "a time; --cancel takes it out; no id: the queue"),
    "share": (cmd_share, ["id"], {"to": True, "project": True},
              "task share <id> --to owner/name [--project owner/number]  # copy a task to a team's GitHub: an Issue "
              "with its Goal and task-hub's reports, and a card on the team's Project ([share] in the config); "
              "its PR then closes both"),
    "check": (cmd_check, ["id"], {"no-write": False, "ref": True, "goal-file": True},
              "task check <id> [--no-write [--ref commit] [--goal-file path]]  # Goldfish agents read only the card's "
              "Goal and its repo's base branch and say GO or NO-GO: on the Issue and in the Project's Readiness field "
              "([runner] readiness gates starting on it); --no-write prints the verdict and writes nothing (any card), "
              "--ref checks against that commit of the repo, --goal-file checks that text as the Goal (a past card's "
              "Goal before it was edited)"),
    "review": (cmd_review, ["id"], {"no-write": False, "ref": True, "base": True, "mode": True, "goal-file": True,
                                    "report-file": True},
               "task review <id> --no-write --ref <commit> [--base <commit>] [--mode agent|goldfish] [--report-file path] "
               "[--goal-file path]  # a trial of the automated review of a card's code at --ref (from --base, else "
               "where it left the base branch), in [runner] review_mode or --mode: prints the verdict and writes "
               "nothing; --mode agent needs the agent's report as --report-file"),
    "list": (cmd_list, [], {"watch": False, "max-age": True},
             "task list [--watch] [--max-age seconds]  # the open cards, read only: starts nothing (use `task` to start "
             f"Ready cards); --watch redraws them every {WATCH_SECONDS}s; the board read by any task-hub command in the "
             f"last --max-age seconds (default {LIST_MAX_AGE}) is shown without asking GitHub, 0 always asks"),
    "events": (cmd_events, [], {"follow": False, "next": False, "after": True, "only": True, "digest": False},
               "task events [--follow | --next [--after N] | --after N] [--only \"In review,Blocked\"] [--digest]  # what "
               "task-hub did lately; --follow prints each new event as it happens, --next waits for the next ones and "
               "exits, --after N alone prints those after line N without waiting, "
               "--digest adds each event's digest below it"),
    "stats": (cmd_stats, [], {}, "task stats  # outcomes of the runs on this machine: reviews, retries, blocks, replanner, "
              "tokens"),
    "update": (cmd_update, [], {}, "task update  # update task-hub to its newest release (an installer's clone: by "
               "that release's installer), restart the launchd "
               "`task watch`, copy Kiro's hook and workflow again"),
    "feedback": (cmd_feedback, [], {"feature": False},
                 "task feedback [--feature]  # report a bug (or ask for a feature) on task-hub's GitHub: opens the "
                 "form with the version and OS filled in, or prints its URL"),
    "_run": (cmd_run, ["id"], {}, "task _run <id>  # internal: one agent run, started by task-hub"),
    "_fix": (cmd_fix, ["id", "base"], {}, "task _fix <id> <base>  # internal: one conflict fix, started by the merge queue"),
    "_kiro-copy": (cmd_kiro_copy, ["key"], {"to": True},
                   "task _kiro-copy kiro-hook|kiro-workflow [--to FILE]  # internal, for windows/install.ps1 and "
                   "doctor.ps1: writes Kiro's hook or workflow as Kiro on this OS runs it, or without --to prints the "
                   "SHA-256 of that"),
    "_home": (cmd_home, [], {}, "task  # sync with the board, start Ready tasks, show what needs you"),
}


def main(argv):
    if argv in (["-v"], ["-V"], ["--version"]):
        print(VERSION)
        return
    if not argv:
        argv = ["_home"]
    if argv[0] in ("-h", "--help", "help"):
        out("commands:", "  task  # sync with the board, start Ready tasks, show what needs you",
            *("  " + c[3] for n, c in COMMANDS.items() if not n.startswith("_")))
        return
    name, rest = argv[0], argv[1:]
    if name not in COMMANDS:
        fail(f"unknown command {name!r}", "commands: " + ", ".join(n for n in COMMANDS if not n.startswith("_")), 2)
    handler, positional, flags, usage = COMMANDS[name]
    if "--help" in rest:
        out(f"usage: {usage}")
        return
    a = {f.replace("-", "_"): (None if takes else False) for f, takes in flags.items()}
    pos = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("--"):
            f = tok[2:]
            if f not in flags:
                fail(f"unknown flag {tok} for `{name}`", f"usage: {usage}", 2)
            if flags[f]:
                if i + 1 >= len(rest):
                    fail(f"{tok} needs a value", f"usage: {usage}", 2)
                a[f.replace("-", "_")] = rest[i + 1]
                i += 1
            else:
                a[f.replace("-", "_")] = True
        else:
            pos.append(tok)
        i += 1
    required = [p for p in positional if not p.endswith("?")]
    if not len(required) <= len(pos) <= len(positional):
        fail(f"`{name}` takes {len(positional)} argument(s), got {len(pos)}", f"usage: {usage}", 2)
    a.update(zip((p.rstrip("?") for p in positional), pos))
    try:
        handler(a)
    except RuntimeError as e:  # GitHub or git failed: say what, never a traceback
        fail(str(e), hint(e))
    except KeyboardInterrupt:  # Ctrl-C: the person knows why it stopped
        sys.exit(130)


def hint(e):
    """The help line for a GitHub failure, when there is a known next step."""
    if "gh not found (" in str(e):  # also inside "cannot read GitHub Project ...": not a permissions problem
        return "install GitHub CLI (https://cli.github.com, docs/setup.md), then run `gh auth login`"
    if "rate limit" in str(e).lower():  # not a permissions problem: waiting fixes it
        return "GitHub limits GraphQL calls per hour; wait for the limit to reset and run again"
    if str(e).startswith("cannot read GitHub Project"):
        return "run `gh auth refresh -s project` and check [board] project in the config"
