#!/usr/bin/env python3
"""Run the tests in parallel, each in its own process: python3 tests/run.py [-j N] [name ...]

The tests are black-box (each has its own temporary HOME and fakes), so they run side by side;
most of their time is spent waiting on subprocesses. A name keeps the tests whose id contains it
(e.g. test_task, TaskTest.test_list). `python3 -m unittest discover -s tests` still runs them one by one.
"""
import concurrent.futures
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def ids(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from ids(t)
        else:
            yield t.id()


def run(test_id):
    began = time.time()
    r = subprocess.run([sys.executable, "-m", "unittest", test_id], cwd=TESTS, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    return test_id, r.returncode, r.stderr, time.time() - began


def main(argv):
    jobs = os.cpu_count() or 4
    if argv[:1] == ["-j"]:
        jobs, argv = int(argv[1]), argv[2:]
    sys.path.insert(0, str(TESTS))
    wanted = [i for i in ids(unittest.defaultTestLoader.discover(str(TESTS)))
              if not argv or any(name in i for name in argv)]
    if not wanted:
        print(f"no tests match {' '.join(argv)}")
        return 1
    began, failed, skipped, slowest = time.time(), [], 0, []
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        done = concurrent.futures.as_completed([pool.submit(run, i) for i in wanted])
        for n, (test_id, code, err, seconds) in enumerate((f.result() for f in done), 1):
            slowest.append((seconds, test_id))
            skipped += int((re.search(r"skipped=(\d+)", err) or [0, 0])[1])
            if code:
                failed.append(test_id)
                print(f"FAIL {test_id}\n{err}", flush=True)
            elif n % 25 == 0:
                print(f"{n}/{len(wanted)} done", flush=True)
    slowest.sort(reverse=True)
    print("slowest:", *(f"  {s:5.1f}s {i}" for s, i in slowest[:5]), sep="\n")
    print(f"{len(wanted)} tests, {len(failed)} failed, {skipped} skipped, {time.time() - began:.0f}s with {jobs} jobs")
    for i in failed:
        print(f"failed: {i}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
