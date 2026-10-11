#!/usr/bin/env python3
"""Compare bin/task (Python) and task-rs (Rust) on the same local files, without GitHub.

Builds a throwaway HOME with a config and a fresh board cache of N fake cards, checks that both print the same
lines, then measures each command's time and peak memory, and the resident memory of `list --watch`.

    python3 rust/bench.py [--cards 12,100,1000] [--runs 20]

Never touches your real board, config or state: everything lives in a temporary directory.
"""
import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = [sys.executable, str(ROOT / "bin" / "task")]
RS = [str(ROOT / "rust" / "target" / "release" / "task-rs")]
STATUSES = ["Backlog", "Ready", "In Progress", "In review", "Blocked"]
TITLES = ["Fix login", "設計: ボードをつなぐ", 'Quote "this", and: that', "#12 first", "true", "123", " padded ",
          "[runner] parallel", "Add tab E2E note"]


def fake_items(n):
    rng = random.Random(n)
    items = []
    for i in range(1, n + 1):
        blockers = [{"number": b, "title": f"task {b}", "state": rng.choice(["OPEN", "CLOSED"]),
                     "stateReason": rng.choice([None, "COMPLETED", "NOT_PLANNED"]),
                     "repository": {"nameWithOwner": rng.choice(["me/tasks", "other/repo"])}}
                    for b in rng.sample(range(1, n + 1), k=min(n, rng.choice([0, 0, 1, 2])))]
        body = "### Goal\n\nDo it.\n\n### Ready conditions\n\n" + " ".join(
            f"- #{rng.randint(1, n)} gives the API" for _ in range(rng.choice([0, 1, 2]))) + "\n\nsee a/b#9\n"
        items.append({
            "id": f"PVTI_{i}", "updatedAt": f"2026-10-{rng.randint(1, 11):02d}T{rng.randint(0, 23):02d}:00:00Z",
            "content": {"number": i, "title": f"{rng.choice(TITLES)} {i}" if i % 3 else rng.choice(TITLES),
                        "url": f"https://github.com/me/tasks/issues/{i}", "body": body * rng.randint(1, 20),
                        "state": "OPEN", "repository": {"nameWithOwner": "me/tasks" if i % 17 else "me/other"},
                        "blockedBy": {"nodes": blockers}},
            "status": {"name": rng.choice(STATUSES)}, "repo": {"text": rng.choice(["me/app", "me/web", ""])},
            "agent": rng.choice([None, {"text": "claude"}, {"text": "codex"}]), "base": None})
    return items


def make_home(tmp, n):
    home = Path(tmp) / f"home-{n}"
    (home / ".config" / "task-hub").mkdir(parents=True)
    (home / ".config" / "task-hub" / "config.ini").write_text(
        "[board]\nproject = me/7  ; the test board\nissues = me/tasks\n")
    st = home / ".local" / "state" / "task-hub"
    (st / "runs").mkdir(parents=True)
    # a run that is still going on this machine: our own pid stands in for `task _run`, so ps finds no `_run`
    (st / "runs" / "2.json").write_text(json.dumps({"stage": "review", "pid": os.getpid()}))
    (st / "runs" / "3.json").write_text(json.dumps({"stage": "agent", "started": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    events = [{"time": "2026-10-11T00:00:00Z", "id": str(i), "title": f"task {i}", "repo": "me/app",
               "event": random.Random(i).choice(["In review", "Blocked", "Done", "replan"]),
               **({"reason": "needs a key"} if i % 4 == 0 else {}), **({"pr": f"https://x/{i}"} if i % 5 == 0 else {})}
              for i in range(200)]
    (st / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
    return home, st


def refresh(st, items):
    """A board cache read 'just now', so both read it instead of GitHub."""
    (st / "board-cache.json").write_text(json.dumps({"key": ["me", "7", "me/tasks"], "fetched_at": time.time(),
                                                     "items": items}, ensure_ascii=False))


def env_for(home):
    return {**os.environ, "HOME": str(home), "TASK_NO_UPDATE_NOTIFIER": "1", "TASK_GH": "/bin/false"}


def measure(cmd, env, runs):
    """Median seconds and median peak memory (MB) of runs of cmd."""
    times, rss = [], []
    for _ in range(runs):
        began = time.perf_counter()
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _, status, usage = os.wait4(p.pid, 0)
        times.append(time.perf_counter() - began)
        if os.waitstatus_to_exitcode(status) != 0:
            raise SystemExit(f"{cmd} failed")
        rss.append(usage.ru_maxrss / (1 if sys.platform == "darwin" else 1 / 1024) / 1048576)  # bytes on macOS
    return statistics.median(times), statistics.median(rss)


def resident_mb(cmd, env):
    """Resident memory of a `list --watch` after its first draw (the process that would stay running)."""
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    rss = int(subprocess.run(["ps", "-o", "rss=", "-p", str(p.pid)], capture_output=True, text=True).stdout or 0)
    p.kill()
    p.wait()
    return rss / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", default="12,100,1000")
    ap.add_argument("--runs", type=int, default=20)
    a = ap.parse_args()
    if not Path(RS[0]).exists():
        raise SystemExit("build first: (cd rust && cargo build --release)")
    print(f"python: {sys.version.split()[0]} | runs per cell: {a.runs} (median) | no GitHub calls\n")
    print("| cards | command | Python time | Rust time | Python memory | Rust memory |")
    print("|---|---|---|---|---|---|")
    with tempfile.TemporaryDirectory() as tmp:
        for n in (int(c) for c in a.cards.split(",")):
            home, st = make_home(tmp, n)
            items = fake_items(n)
            env = env_for(home)
            for args in (["list"], ["events"], ["events", "--only", "Blocked,replan"]):
                refresh(st, items)
                py = subprocess.run(PY + args, env=env, capture_output=True, text=True).stdout
                rs = subprocess.run(RS + args, env=env, capture_output=True, text=True).stdout
                if py != rs:
                    (Path(tmp) / "py.txt").write_text(py)
                    (Path(tmp) / "rs.txt").write_text(rs)
                    subprocess.run(["diff", str(Path(tmp) / "py.txt"), str(Path(tmp) / "rs.txt")])
                    raise SystemExit(f"outputs differ for {args} with {n} cards")
                refresh(st, items)
                pt, pm = measure(PY + args, env, a.runs)
                rt, rm = measure(RS + args, env, a.runs)
                print(f"| {n} | {' '.join(args)} | {pt * 1000:.1f} ms | {rt * 1000:.1f} ms | {pm:.1f} MB | {rm:.1f} MB |")
            refresh(st, items)
            watch = ["list", "--watch"]
            print(f"| {n} | list --watch (resident) | | | {resident_mb(PY + watch[:2], env):.1f} MB | "
                  f"{resident_mb(RS + watch, env):.1f} MB |")
    print(f"\nbinary: task-rs {Path(RS[0]).stat().st_size / 1024:.0f} KB; outputs identical in every case")


if __name__ == "__main__":
    main()
