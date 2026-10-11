"""tests/bench.py, run the way a colleague runs it: it measures in a throwaway HOME and leaves the real one alone.

The "real" HOME here is a temporary one with a config, state and a cache, and a `gh` on PATH (and in TASK_GH) that
notes each call: after the bench, every file is as it was and that `gh` never ran. test_windows.py runs it on Windows.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BENCH = Path(__file__).resolve().parent / "bench.py"
WINDOWS = os.name == "nt"


def snapshot(root):
    """Every directory and file under root, with each file's size, mtime and contents."""
    seen = {}
    for parent, dirs, files in os.walk(root):
        for d in dirs:
            seen[os.path.relpath(os.path.join(parent, d), root)] = "dir"
        for f in files:
            path = Path(parent, f)
            seen[os.path.relpath(path, root)] = (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
    return seen


class BenchTest(unittest.TestCase):
    def test_quick_bench_reports_and_leaves_the_real_home_alone(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            real = root / "real-home"
            config = real / ".config" / "task-hub" / "config.ini"
            config.parent.mkdir(parents=True)
            config.write_text("[board]\nproject = someone/7\nissues = someone/tasks\n")
            state = real / ".local" / "state" / "task-hub"
            state.mkdir(parents=True)
            (state / "events.jsonl").write_text('{"id": "1", "event": "Done"}\n')
            (state / "board-cache.json").write_text('{"items": []}')
            fakebin, calls, temp = root / "bin", root / "gh-calls.txt", root / "temp"
            fakebin.mkdir()
            temp.mkdir()
            if WINDOWS:  # an .exe: Windows finds no other kind of program by the name gh
                from test_windows import write_exe
                gh = fakebin / "gh.exe"
                write_exe(gh, f"import sys\nopen({str(calls)!r}, 'a').write(repr(sys.argv) + '\\n')\nsys.exit(1)\n")
            else:
                gh = fakebin / "gh"
                gh.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nexit 1\n')
                gh.chmod(0o755)
            before = snapshot(real)
            env = {**os.environ, "HOME": str(real), "USERPROFILE": str(real), "TASK_GH": str(gh),
                   "XDG_DATA_HOME": str(real / ".local" / "share"), "CLAUDE_CONFIG_DIR": str(real / ".claude"),
                   "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}", "TMPDIR": str(temp), "TEMP": str(temp),
                   "TMP": str(temp)}
            r = subprocess.run([sys.executable, str(BENCH), "--quick", "--runs", "1", "--watch-seconds", "2"],
                               env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
            self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)  # 1: a target missed, on a busy test machine
            self.assertRegex(r.stdout, r"^machine: .+ \| CPU: .+ \| memory: .+ GB \| Python 3\.")
            for row in (r"`task list` \| 12 \| \d+ ms \| [\d.]+ MB", r"`task list` \| 1000 \| \d+ ms",
                        r"`task events` \| - \| \d+ ms", r"`task list --watch` \| 12 \| - \| - \| [\d.]+ MB",
                        r"`task watch` \| 12 \| - \| - \| [\d.]+ MB \| [\d.]+ s \([\d.]+%\)"):
                self.assertRegex(r.stdout, row)
            self.assertEqual(len(re.findall(r"^(PASS|FAIL): ", r.stdout, re.M)), 4, r.stdout)
            self.assertEqual(snapshot(real), before)
            self.assertFalse(calls.exists(), "the bench ran the gh on PATH or in TASK_GH")
            self.assertEqual(list(temp.iterdir()), [])  # its throwaway HOME is gone too


if __name__ == "__main__":
    unittest.main()
