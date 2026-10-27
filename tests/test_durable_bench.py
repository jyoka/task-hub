"""tests/durable_bench.py without a model: its 63 trials, and the tables --report makes of its results.

The trials themselves need pi, the B runner and the ChatGPT login: they are run by hand (docs/durable-runs-comparison.md).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

BENCH = Path(__file__).resolve().parent / "durable_bench.py"


def bench(*args):
    r = subprocess.run([sys.executable, str(BENCH), *args], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise AssertionError(r.stdout + r.stderr)
    return r.stdout


class DurableBenchTest(unittest.TestCase):
    def test_the_63_trials_of_the_design_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids = bench("--list", "--out", str(Path(tmp) / "results.jsonl")).split()
        self.assertEqual(len(ids), 63)
        self.assertEqual(len(set(ids)), 63)
        self.assertEqual(Counter(i[0] for i in ids), {"A": 21, "B": 21, "C": 21})
        cuts = Counter("-".join(i.split("-")[1:3]) for i in ids if "none" not in i)
        self.assertEqual(cuts, {**{f"{t}-{k}": 6 for t in ("T1", "T2", "T3", "T4") for k in ("K1", "K2")}, "T2-K3": 6})
        self.assertEqual(ids[:3], ["A-none-1", "B-none-1", "C-none-1"])  # one cut's A, B and C run next to each other

    def test_report_counts_a_trial_run_again_once_and_skips_it_when_done(self):
        row = {"kind": "trial", "method": "A", "agent": "pi-a", "timing": "", "kill": "", "rep": 1,
               "status": "In review", "seconds": 60, "cut": "", "tool_calls": 10, "turns": 5,
               "tokens": {"input": 1, "output": 1, "cacheRead": 1, "total": 50000}, "test_runs": 1,
               "test_parallel": 1, "changelog_runs": 1, "changelog_lines": 1, "pushed": True, "tests_pass": True,
               "compiles": True, "diff_ok": True, "leftover": [], "resumed": []}
        cut = {**row, "id": "A-T2-K1-1", "timing": "T2", "kill": "K1", "cut": "cut", "cut_phase": "tool",
               "cut_at": 20.0, "resumed": ["agent"], "test_runs": 2, "test_parallel": 2,
               "tokens": {**row["tokens"], "total": 90000}}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.jsonl"
            out.write_text("".join(json.dumps(r) + "\n" for r in (
                {"kind": "conditions", "model": "m"}, {**row, "id": "A-none-1", "tests_pass": False},
                {**row, "id": "A-none-1"}, cut)))
            report = bench("--report", "--out", str(out))
            listed = bench("--list", "--only", "^A-(none-1|T2-K1-1|T2-K1-2)$", "--out", str(out)).split("\n")
        self.assertIn("| A-T2-K1-1 | cut | tool | 20.0 | In review | agent | yes | 2 (2) | 1 (1) | no |", report)
        self.assertIn("| A | 2 | 1 | 2 | 2/2 (1/1 / 1/1) | 0 | 1 | +1 | +0 | +40k | +0.0 | 50k |", report)
        self.assertIn('conditions: {"model": "m"}', report)
        self.assertEqual(listed[:3], ["A-none-1  (done)", "A-T2-K1-1  (done)", "A-T2-K1-2"])


if __name__ == "__main__":
    unittest.main()
