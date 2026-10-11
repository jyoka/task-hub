#!/usr/bin/env python3
"""How heavy task-hub feels on a slow PC: python3 tests/bench.py [--quick] [--efficiency-cores] (docs/benchmark.md)

Measures what a person notices, not throughput: how long `task list` and `task events` take to print, the most memory
they use, and what the always-on `task list --watch` and `task watch` hold (resident memory, CPU time per minute).
One process at a time, never in parallel: a run never uses up the CPU.

Everything runs in a throwaway HOME with its own config, state and a fake GitHub (test_task.py's FAKE_GH, the one the
tests use): the real config, state and board are never read or written, and GitHub is never called.
Not a test (the name does not start with test_): run it by hand when asked, and before a release.
"""
import argparse
import contextlib
import json
import os
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
BIN = TESTS.parent / "bin" / "task"
WINDOWS = os.name == "nt"


def stop(msg):
    """The bench itself failed: exit 2 (1 is a missed target)."""
    print(msg, file=sys.stderr, flush=True)
    sys.exit(2)


sys.path.insert(0, str(TESTS))
try:
    if WINDOWS:  # test_windows sets up the fcntl stand-in test_task needs, and makes the fake gh an .exe (with pip's)
        from test_windows import FCNTL, write_exe  # noqa: E402
    from test_task import FAKE_GH, STATUS_OPTIONS  # noqa: E402
except ImportError as e:
    stop(f"error: cannot load the fake GitHub of the tests: {e}")
# Windows: a venv's python.exe only starts the base one as its child, which our handle would not see
PYTHON = getattr(sys, "_base_executable", sys.executable) if WINDOWS and sys.prefix != sys.base_prefix \
    else sys.executable

# first guesses, to be corrected by measurements on the PCs it is meant for (docs/benchmark.md)
TARGET_WATCH_MB, TARGET_WATCH_CPU, TARGET_LIST_MS = 50, 1.0, 300
MB = 1024 * 1024
# statuses of the fake cards: no Ready (task watch would start it), no In review (it would look for a PR)
STATUSES = ["Backlog", "Backlog", "Blocked", "Done"]


# ---------- the machine ----------

def capture(*argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def machine():
    """OS, CPU name, cores, memory and Python, as one line."""
    cores, memory, cpu = f"{os.cpu_count()} cores", 0, platform.processor() or platform.machine()
    if sys.platform == "darwin":
        name = f"macOS {platform.mac_ver()[0]}"
        cpu = capture("sysctl", "-n", "machdep.cpu.brand_string") or cpu
        memory = int(capture("sysctl", "-n", "hw.memsize") or 0)
        fast, slow = (capture("sysctl", "-n", f"hw.perflevel{level}.logicalcpu") for level in (0, 1))
        if fast and slow:  # Apple Silicon: performance and efficiency cores
            cores += f" ({fast} performance, {slow} efficiency)"
    elif WINDOWS:
        import ctypes
        import winreg
        name = f"Windows {platform.release()} ({platform.version()})"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        *((n, ctypes.c_ulonglong) for n in ("total", "avail", "pagetotal", "pageavail", "virttotal",
                                                            "virtavail", "extended"))]
        status = MemoryStatus(dwLength=ctypes.sizeof(MemoryStatus))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            memory = status.total
    else:
        name = f"{platform.system()} {platform.release()}"
        with contextlib.suppress(OSError, ValueError, StopIteration):
            os_release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines()
                              if "=" in line)
            name = os_release.get("PRETTY_NAME", "").strip('"') or name
        with contextlib.suppress(OSError, ValueError, StopIteration):
            cpu = next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                       if line.startswith("model name"))
        with contextlib.suppress(OSError, ValueError, StopIteration):
            memory = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                              if line.startswith("MemTotal"))) * 1024
    return (f"machine: {name}, {platform.machine()} | CPU: {cpu}, {cores} | "
            f"memory: {memory / 1024 ** 3:.1f} GB | Python {platform.python_version()}")


# ---------- one process: its time, CPU and memory ----------

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    *((n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                     "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                     "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage"))]

    kernel32, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    QUERY = 0x1000 | 0x0010  # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ


class Process:
    """A started process, and what it uses: CPU seconds, resident bytes, and at the end its peak.

    POSIX: the peak is ru_maxrss from os.wait4 (bytes on macOS, KB on Linux); while it runs, /proc on Linux, else ps.
    Windows: a handle of our own (held from the start, so it stays readable after the process ends) for
    GetProcessTimes and GetProcessMemoryInfo (WorkingSetSize, PeakWorkingSetSize)."""

    def __init__(self, argv, env, stdout):
        self.began = time.perf_counter()
        self.popen = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.STDOUT,
                                      **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS
                                         else {"start_new_session": True}))
        self.handle = None
        if WINDOWS:
            self.handle = kernel32.OpenProcess(QUERY, False, self.popen.pid)
            if not self.handle:
                self.popen.kill()
                stop(f"error: OpenProcess failed (Windows error {ctypes.get_last_error()})")
        self.peak = None

    def usage(self):
        """(CPU seconds, resident bytes) now, or None once it has ended."""
        pid = self.popen.pid
        if self.popen.poll() is not None:
            return None
        if WINDOWS:
            times = [wintypes.FILETIME() for _ in range(4)]
            counters = self.counters()
            if not counters or not kernel32.GetProcessTimes(self.handle, *map(ctypes.byref, times)):
                return None
            ticks = lambda t: (t.dwHighDateTime << 32) + t.dwLowDateTime  # in 100 ns
            return (ticks(times[2]) + ticks(times[3])) / 1e7, counters.WorkingSetSize
        if Path(f"/proc/{pid}/stat").exists():
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                rss = int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
            except (OSError, IndexError, ValueError):
                return None
            return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"), rss
        line = capture("ps", "-o", "time=,rss=", "-p", str(pid)).split()
        if len(line) != 2:
            return None
        seconds = 0.0
        for part in line[0].replace("-", ":").split(":"):  # [[dd-]hh:]mm:ss.cc
            seconds = seconds * 60 + float(part)
        return seconds, int(line[1]) * 1024

    def counters(self):
        c = MemoryCounters(cb=ctypes.sizeof(MemoryCounters))
        return c if psapi.GetProcessMemoryInfo(self.handle, ctypes.byref(c), c.cb) else None

    def wait(self):
        """Wait for it to end: (exit code, seconds since it started, peak resident bytes)."""
        if WINDOWS:
            code = self.popen.wait()
            seconds = time.perf_counter() - self.began
            counters = self.counters()
            kernel32.CloseHandle(self.handle)
            if not counters:
                stop(f"error: GetProcessMemoryInfo failed (Windows error {ctypes.get_last_error()})")
            self.peak = counters.PeakWorkingSetSize
        else:
            _, status, rusage = os.wait4(self.popen.pid, 0)
            seconds = time.perf_counter() - self.began
            code = self.popen.returncode = os.waitstatus_to_exitcode(status)
            self.peak = rusage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        return code, seconds, self.peak

    def stop(self):
        if WINDOWS:  # with the fake gh it may be running: a gh.exe launcher and its Python
            subprocess.run(["taskkill", "/PID", str(self.popen.pid), "/T", "/F"], capture_output=True)
            self.popen.wait()
            kernel32.CloseHandle(self.handle)
            return
        try:
            os.killpg(self.popen.pid, signal.SIGTERM)  # with the fake gh it may be running
        except (ProcessLookupError, PermissionError):  # macOS: EPERM when it has ended but is not reaped yet
            pass
        self.popen.wait()


# ---------- the throwaway HOME ----------

class Sandbox:
    """A HOME with a config, a board of `cards` fake cards in a fake GitHub, and no way to reach the real ones."""

    def __init__(self, root, cards, wrap):
        self.root, self.cards, self.wrap = root, cards, wrap
        self.home = root / "home"
        cfg = self.home / ".config" / "task-hub" / "config.ini"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("[board]\nproject = jyoka/2\nissues = jyoka/tasks\n\n[runner]\nagent = fake\n\n"
                       "[agents]\nfake = fake-agent {prompt}\n", encoding="utf-8")
        self.state = self.home / ".local" / "state" / "task-hub"
        self.state.mkdir(parents=True)
        self.db = root / "gh.json"
        issues, items = {}, {}
        for n in range(1, cards + 1):
            issues[str(n)] = {"title": f"Card number {n}: a title about as long as a real one", "state": "OPEN",
                              "body": f"## Goal\n\nDo thing {n}.\n" + "A line of the goal, about this long.\n" * 40,
                              "comments": []}
            items[f"PVTI_{n}"] = {"number": n, "updated": f"2026-01-01T{n:08d}Z",
                                  "values": {"status": STATUSES[n % len(STATUSES)], "target repo": "jyoka/app",
                                             "agent": "fake"}}
        self.db.write_text(json.dumps({
            "issues_repo": "jyoka/tasks", "issues": issues, "items": items, "prs": {}, "clock": cards,
            "fields": [{"id": "F_status", "name": "Status", "type": "ProjectV2SingleSelectField",
                        "dataType": "SINGLE_SELECT",
                        "options": [{"id": f"O_{i}", "name": n} for i, n in enumerate(STATUS_OPTIONS)]},
                       {"id": "F_title", "name": "Title", "type": "ProjectV2Field", "dataType": "TITLE"},
                       *({"id": f"F_{n}", "name": n, "type": "ProjectV2Field", "dataType": "TEXT"}
                         for n in ("Target repo", "Agent", "Base branch"))]}))
        if WINDOWS:  # Windows runs no #! line: the fake behind an .exe launcher, with its fcntl stand-in
            gh = root / "gh.exe"
            (root / "fakes").mkdir()
            (root / "fakes" / "fcntl.py").write_text(FCNTL)
            write_exe(gh, FAKE_GH)
        else:
            gh = root / "gh"
            gh.write_text(FAKE_GH)
            gh.chmod(0o755)
        # nothing of the caller's task-hub, GitHub or Claude Code settings: they could point outside this HOME
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("TASK_", "XDG_", "CLAUDE_", "GH_", "GITHUB_", "HERDR_"))}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home), TASK_GH=str(gh), TASK_TEST_GH_DB=str(self.db),
                        TASK_HERDR="0", TASK_NO_UPDATE_NOTIFIER="1",
                        PYTHONUTF8="1")  # as windows/install.ps1's task.cmd: else bin/task runs itself again
        if WINDOWS:
            self.env["PYTHONPATH"] = str(root / "fakes")

    def argv(self, *args):
        return [*self.wrap, PYTHON, str(BIN), *args]

    def start(self, *args, stdout=subprocess.DEVNULL):
        return Process(self.argv(*args), self.env, stdout)

    def run(self, *args):
        """Run one command to its end: (seconds, peak bytes). Its output goes to a file: a full pipe would stop it."""
        with open(self.root / "out.txt", "w+b") as f:
            p = self.start(*args, stdout=f)
            code, seconds, peak = p.wait()
            if code != 0:
                f.seek(0)
                stop(f"error: `task {' '.join(args)}` exited {code}:\n{f.read().decode(errors='replace')[-2000:]}")
        return seconds, peak

    def github_reads(self):
        return json.loads(self.db.read_text()).get("graphql_calls", 0)


# ---------- the measurements ----------

def timed(box, runs, *args):
    """Median seconds and peak bytes of `runs` runs, one after another."""
    results = [box.run(*args) for _ in range(runs)]
    return statistics.median(s for s, _ in results), statistics.median(p for _, p in results)


def resident(box, seconds, *args):
    """Start an always-on command, look at it every so often for `seconds`, stop it.
    (most resident bytes seen, CPU seconds used, seconds it ran)."""
    p = box.start(*args)
    began, most, cpu = time.perf_counter(), 0, 0.0
    step = 0.5 if seconds <= 10 else 2.0
    try:
        while time.perf_counter() - began < seconds:
            time.sleep(min(step, max(seconds - (time.perf_counter() - began), 0)))
            seen = p.usage()
            if seen is None:
                stop(f"error: `task {' '.join(args)}` ended by itself (exit {p.popen.poll()})")
            cpu, most = seen[0], max(most, seen[1])
        return most, cpu, time.perf_counter() - began
    finally:
        p.stop()


def measure(root, quick, runs, watch_seconds, wrap, say):
    rows, notes = [], []
    small, big = (Sandbox(root / f"board-{n}", n, wrap) for n in (12, 1000))
    for box in (small, big):
        box.run("list")  # reads the fake GitHub once: the board's ids and the open cards are now saved
        before = box.github_reads()
        seconds, peak = timed(box, runs, "list")
        if box.github_reads() != before:
            notes.append(f"note: `task list` with {box.cards} cards read the fake GitHub: its cache was not fresh")
        rows.append({"command": "task list", "cards": box.cards, "ms": seconds * 1000, "peak": peak})
        say(f"  task list, {box.cards} cards: {seconds * 1000:.0f} ms")
    (small.state / "events.jsonl").write_text("".join(
        json.dumps({"time": f"2026-10-11T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}+09:00", "id": str(i % 12 + 1),
                    "title": f"Card number {i % 12 + 1}", "repo": "jyoka/app", "event": STATUSES[i % 3]}) + "\n"
        for i in range(500)))
    seconds, peak = timed(small, runs, "events")
    rows.append({"command": "task events", "cards": "-", "ms": seconds * 1000, "peak": peak})
    say(f"  task events: {seconds * 1000:.0f} ms")
    most, _, _ = resident(small, 3 if quick else 5, "list", "--watch")
    rows.append({"command": "task list --watch", "cards": small.cards, "resident": most})
    say(f"  task list --watch: {most / MB:.1f} MB")
    say(f"  task watch: {watch_seconds} s ...")
    before = small.github_reads()
    most, cpu, ran = resident(small, watch_seconds, "watch")
    # it checks GitHub once a minute: a run shorter than a minute counts as that minute. Its start and first check
    # are included, so it shows a bit more than a later minute takes
    per_minute = cpu * 60 / max(ran, 60)
    rows.append({"command": "task watch", "cards": small.cards, "resident": most, "cpu_s": per_minute,
                 "cpu_pct": per_minute / 60 * 100})
    notes.append(f"note: task watch read the fake GitHub {small.github_reads() - before} time(s) in {ran:.0f} s; "
                 "the CPU of its gh calls is not counted, only task watch's own")
    return rows, notes


# ---------- the report ----------

def report(rows):
    def cell(r, key, show):
        return "-" if r.get(key) is None else show(r[key])

    mb = lambda v: f"{v / MB:.1f} MB"
    lines = ["| command | cards | time (median) | peak memory | resident memory | CPU per minute |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        cpu = f"{r['cpu_s']:.2f} s ({r['cpu_pct']:.2f}%)" if "cpu_s" in r else "-"
        lines.append(f"| `{r['command']}` | {r['cards']} | {cell(r, 'ms', lambda v: f'{v:.0f} ms')} | "
                     f"{cell(r, 'peak', mb)} | {cell(r, 'resident', mb)} | {cpu} |")
    return lines


def verdicts(rows):
    """One line per target: PASS or FAIL, and the value."""
    watch = next(r for r in rows if r["command"] == "task watch")
    checks = [(f"task watch resident memory < {TARGET_WATCH_MB} MB", watch["resident"] / MB < TARGET_WATCH_MB,
               f"{watch['resident'] / MB:.1f} MB"),
              (f"task watch CPU < {TARGET_WATCH_CPU:g}% on average", watch["cpu_pct"] < TARGET_WATCH_CPU,
               f"{watch['cpu_pct']:.2f}%")]
    checks += [(f"task list ({r['cards']} cards, fresh cache) < {TARGET_LIST_MS} ms", r["ms"] < TARGET_LIST_MS,
                f"{r['ms']:.0f} ms") for r in rows if r["command"] == "task list"]
    lines = [f"{'PASS' if ok else 'FAIL'}: {what}: {value}" for what, ok, value in checks]
    return lines, all(ok for _, ok, _ in checks)


def main(argv):
    p = argparse.ArgumentParser(prog="tests/bench.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--quick", action="store_true", help="about 30 seconds: 3 runs each, task watch for 15 s")
    p.add_argument("--efficiency-cores", action="store_true",
                   help="macOS: run task-hub on the efficiency cores only (taskpolicy -b), closer to a slow PC")
    p.add_argument("--runs", type=int, help="runs of each command (default 5, --quick 3)")
    p.add_argument("--watch-seconds", type=int,
                   help="how long task watch runs (default 125: three checks; --quick 15: one)")
    a = p.parse_args(argv)
    runs = a.runs if a.runs is not None else 3 if a.quick else 5
    watch_seconds = a.watch_seconds if a.watch_seconds is not None else 15 if a.quick else 125
    if runs < 1 or watch_seconds < 1:
        p.error("--runs and --watch-seconds take a number of 1 or more")
    wrap = []
    if a.efficiency_cores:
        if sys.platform != "darwin" or not shutil.which("taskpolicy"):
            p.error("--efficiency-cores needs macOS (taskpolicy)")
        wrap = ["taskpolicy", "-b"]  # background QoS: on Apple Silicon, the efficiency cores only
    began = time.perf_counter()
    say = lambda line: print(line, flush=True)
    say(machine())
    say(f"bench: {'quick, ' if a.quick else ''}{runs} run(s) each, task watch for {watch_seconds} s, one process at a"
        f" time{', efficiency cores only (taskpolicy -b)' if wrap else ''}; a throwaway HOME and a fake GitHub")
    tmp = Path(tempfile.mkdtemp(prefix="task-hub-bench-"))
    try:
        rows, notes = measure(tmp, a.quick, runs, watch_seconds, wrap, say)
    except (Exception, KeyboardInterrupt) as e:  # SystemExit (stop) passes through
        stop(f"error: {e!r}")
    finally:
        for _ in range(40):  # Windows: a process ended by taskkill may hold its files for a moment
            shutil.rmtree(tmp, ignore_errors=True)
            if not tmp.exists():
                break
            time.sleep(0.25)
    say("")
    lines, ok = verdicts(rows)
    say("\n".join([*report(rows), "", "targets (first guesses, docs/benchmark.md):", *lines, *notes,
                   f"done in {time.perf_counter() - began:.0f} s"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
