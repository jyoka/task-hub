#!/usr/bin/env python3
"""What a change needs from CI (CONTRIBUTING.md, テスト): all the tests, or only the docs tests.

python3 tests/ci/scope.py <base>   docs_only=true when every file changed since the merge base with <base> is docs
                                   (is_doc), else docs_only=false; also appended to $GITHUB_OUTPUT when it is set.
                                   No <base> (a push to main, a run by hand) or no change is never docs only.
python3 tests/ci/scope.py --tests  the tests that read the docs, one per line, for tests/run.py

The first step of each job in .github/workflows: a docs-only change runs only the docs tests, in the same jobs, so
the checks the merge queue and the branch rules wait for (test, standard-user) report either way.
"""
import os
import subprocess
import sys

# docs: everything in these, and Markdown at the top of the repository (README.md, CONTRIBUTING.md, ...). Not the
# Markdown elsewhere: worker/, skills/, claude/, kiro/, .claude/ and .kiro/ hold the prompts and the instructions
# task-hub and its agents run on, and the tests read them as such
DOCS_DIRS = ("docs/", "site/", "assets/")

# the tests that read the docs, as tests/run.py names (each keeps the test ids that contain it). A new test that reads
# README, docs/, site/ or assets/ goes here too: a docs-only PR runs only these
DOCS_TESTS = (
    "test_brand.",
    "test_site.",
    "test_media.",
    "test_task.TaskTest.test_readme_lists_every_command",
    "test_task.TaskTest.test_design_diagram_matches_the_transitions",
    "test_task.TaskTest.test_the_drift_report_example_in_docs_triggers_is_read_as_documented",
    "test_task.ArchitectureBriefTest.",
)


def is_doc(path):
    return path.startswith(DOCS_DIRS) or "/" not in path and path.endswith(".md")


def changed(base):
    """The files changed on HEAD's side since its merge base with base: added, changed, deleted, both sides of a
    rename."""
    r = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        sys.exit(f"git diff {base}...HEAD failed: {r.stderr.strip()}")
    return [p for p in r.stdout.split("\0") if p]


def docs_only(base):
    """(docs only or not, why)"""
    if not base:
        return False, "no base to compare with (a push to main or a run by hand): all the tests"
    files = changed(base)
    if not files:
        return False, f"no change since {base}: all the tests"
    code = [p for p in files if not is_doc(p)]
    if code:
        more = f" and {len(code) - 5} more" if len(code) > 5 else ""
        return False, f"{len(files)} file(s) changed, not only docs ({', '.join(code[:5])}{more}): all the tests"
    return True, f"{len(files)} file(s) changed, all docs: only the docs tests"


def main(argv):
    if argv == ["--tests"]:
        print("\n".join(DOCS_TESTS))
        return 0
    if len(argv) > 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    only, why = docs_only(argv[0] if argv else "")
    line = f"docs_only={'true' if only else 'false'}"
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as out:  # no \r on Windows
            out.write(line + "\n")
    print(f"{line}  # {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
