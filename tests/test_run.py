"""tests/run.py, the parallel runner: run on a copy beside one small probe test, with its own temporary directory
(where the full run's lock lives), so it never waits on the real full run that may be running these tests."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RUN = Path(__file__).resolve().parent / "run.py"
WINDOWS = os.name == "nt"
PROBE = '''
import ctypes, os, time, unittest

class Probe(unittest.TestCase):
    def test_priority(self):  # when it ran and at what priority, for the test that asks
        began = time.time()
        time.sleep(float(os.environ.get("PROBE_SLEEP", 0)))
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
            value = kernel32.GetPriorityClass(kernel32.GetCurrentProcess())
        else:
            value = os.getpriority(os.PRIO_PROCESS, 0)
        with open(os.environ["PROBE_OUT"], "a") as f:
            f.write(f"{value} {began} {time.time()}\\n")
'''


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.tests, self.temp = root / "tests", root / "temp"
        self.tests.mkdir()
        self.temp.mkdir()
        shutil.copy(RUN, self.tests / "run.py")
        (self.tests / "test_probe.py").write_text(PROBE)
        self.out = root / "probe.txt"
        self.lock = self.temp / "task-hub-tests.lock"
        self.env = {**os.environ, "TMPDIR": str(self.temp), "TEMP": str(self.temp), "TMP": str(self.temp),
                    "PROBE_OUT": str(self.out)}

    def start(self, *args):
        p = subprocess.Popen([sys.executable, str(self.tests / "run.py"), *args], cwd=self.tests, env=self.env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        return p

    def runner(self, *args):
        p = self.start(*args)
        out, _ = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, out)
        return out

    def free(self):
        """The other full run finishes. Windows refuses while a waiting run reads the lock: try again."""
        for _ in range(50):
            try:
                return self.lock.unlink()
            except PermissionError:
                time.sleep(0.1)

    def dead_pid(self):
        p = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
        return int(p.stdout)

    def test_two_jobs_by_default(self):
        self.assertTrue(self.runner("probe").rstrip().splitlines()[-1].endswith("with 2 jobs"))
        self.assertTrue(self.runner("-j", "4", "probe").rstrip().splitlines()[-1].endswith("with 4 jobs"))

    def test_tests_run_at_a_low_priority(self):
        self.runner("probe")
        value = int(self.out.read_text().split()[0])
        if WINDOWS:
            self.assertEqual(value, 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
        else:  # a nicer process than this one, unless this one is already as nice as it gets
            mine = os.getpriority(os.PRIO_PROCESS, 0)
            self.assertGreaterEqual(value, min(mine + 10, 19))

    def test_a_full_run_waits_for_a_live_one(self):
        self.lock.write_text(str(os.getpid()))  # this test, alive, holds the full run's lock
        p = self.start()
        line = p.stdout.readline()
        self.assertIn("waiting for the full test run", line)
        self.assertIn(str(os.getpid()), line)
        time.sleep(2)
        self.assertIsNone(p.poll())
        self.assertFalse(self.out.exists())  # no test started
        self.free()
        out, _ = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, line + out)
        self.assertNotIn("waiting", out)  # said once
        self.assertTrue(out.rstrip().endswith("with 2 jobs"), out)
        self.assertTrue(self.out.exists())
        self.assertFalse(self.lock.exists())  # let go when done
        self.assertEqual(sorted(os.listdir(self.temp)), [])

    def test_a_full_run_takes_over_a_dead_ones_lock(self):
        dead = self.dead_pid()
        self.lock.write_text(str(dead))  # left by a run that was killed
        out = self.runner()
        self.assertNotIn("waiting", out)
        self.assertTrue(self.out.exists())
        self.assertFalse(self.lock.exists())

    def test_a_named_run_does_not_wait(self):
        self.lock.write_text(str(os.getpid()))
        out = self.runner("probe")
        self.assertNotIn("waiting", out)
        self.assertTrue(self.out.exists())
        self.assertEqual(self.lock.read_text(), str(os.getpid()))  # not its lock to take

    def test_only_one_full_run_at_a_time(self):
        self.lock.write_text(str(os.getpid()))
        self.env["PROBE_SLEEP"] = "1"
        first, second = self.start(), self.start()
        self.assertIn("waiting", first.stdout.readline())
        self.assertIn("waiting", second.stdout.readline())
        self.free()
        outs = [first.communicate(timeout=60)[0], second.communicate(timeout=60)[0]]
        self.assertEqual([first.returncode, second.returncode], [0, 0], outs)
        (_, _, a_ended), (_, b_began, _) = sorted(
            tuple(map(float, line.split())) for line in self.out.read_text().splitlines())
        self.assertGreaterEqual(b_began, a_ended)  # one after the other


if __name__ == "__main__":
    unittest.main()
