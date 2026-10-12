#!/usr/bin/env python3
"""Run the tests in parallel, each in its own process: python3 tests/run.py [-j N] [name ...]

The tests are black-box (each has its own temporary HOME and fakes), so they run side by side;
most of their time is spent waiting on subprocesses. A name keeps the tests whose id contains it
(e.g. test_task, TaskTest.test_list). `python3 -m unittest discover -s tests` still runs them one by one.
They run gently, so the machine stays usable for a person and their agents: 2 at a time by default,
at a low priority, and one full run (no names) per machine at a time; a second one waits for it.
"""
import concurrent.futures
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
JOBS = 2
WINDOWS = os.name == "nt"


def lock_path():
    return Path(tempfile.gettempdir()) / "task-hub-tests.lock"


def alive(pid, since):
    """Whether pid is still the process that wrote a lock at `since` (a pid handed out again is not)."""
    if not WINDOWS:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            pass  # someone else's process: it exists
        return True
    import ctypes  # os.kill(pid, 0) would end the process on Windows
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: it exists
    try:
        code, times = wintypes.DWORD(), [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return False
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return True
        created = ((times[0].dwHighDateTime << 32) + times[0].dwLowDateTime - 116444736000000000) / 1e7
        return created <= since + 2  # Windows hands out pids again soon
    finally:
        kernel32.CloseHandle(handle)


def take_lock():
    """Hold the full run's lock, waiting while a live process holds it; a dead one's lock is taken over."""
    lock, waited = lock_path(), False
    mine = lock.with_name(f"{lock.name}.{os.getpid()}")
    mine.write_text(str(os.getpid()))
    try:
        while True:
            try:
                os.link(mine, lock)  # creates the lock with its pid already in it, or fails if it exists
                return
            except FileExistsError:
                pass
            try:
                owner, since = lock.read_text().strip(), lock.stat().st_mtime
            except FileNotFoundError:
                continue  # its owner just finished
            if owner.isdigit() and owner != str(os.getpid()) and alive(int(owner), since):
                if not waited:
                    print(f"waiting for the full test run in process {owner} to finish ({lock})", flush=True)
                    waited = True
                time.sleep(1)
            else:
                remove(lock, owner)  # still the dead owner's: not one just taken over
    finally:
        remove(mine, str(os.getpid()))


def drop_lock():
    remove(lock_path(), str(os.getpid()))


def remove(path, owner):
    """Delete path if it still holds owner's pid. Windows refuses while another process reads it: try again."""
    for _ in range(50):
        try:
            if path.read_text().strip() == owner:
                path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.1)


def ids(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from ids(t)
        else:
            yield t.id()


def run(test_id):
    began = time.time()
    # low priority (Unix: main's nice, which they inherit), so the person and their agents stay responsive
    # not the code page: a Windows in Chinese (gbk) cannot read the Japanese a failing test prints
    r = subprocess.run([sys.executable, "-m", "unittest", test_id], cwd=TESTS, capture_output=True,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                       creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS if WINDOWS else 0)
    return test_id, r.returncode, r.stderr, time.time() - began


def main(argv):
    jobs = JOBS
    if argv[:1] == ["-j"]:
        jobs, argv = int(argv[1]), argv[2:]
    sys.path.insert(0, str(TESTS))
    wanted = [i for i in ids(unittest.defaultTestLoader.discover(str(TESTS)))
              if not argv or any(name in i for name in argv)]
    if not wanted:
        print(f"no tests match {' '.join(argv)}")
        return 1
    if not WINDOWS:
        os.nice(10)
    if argv:
        return run_tests(wanted, jobs)
    take_lock()
    try:
        return run_tests(wanted, jobs)
    finally:
        drop_lock()


def run_tests(wanted, jobs):
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
