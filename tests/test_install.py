"""Black-box tests of kiro/install.sh: run it with `sh`, with HOME a temporary folder.

- GitHub Releases is a local HTTP server (TASK_INSTALL_GITHUB) with fake gh and uv archives and their checksums,
  so nothing is downloaded for real. releases/latest redirects to a tag, as on github.com.
- task-hub is cloned from a local bare repo (TASK_INSTALL_REPO), whose bin/task only prints its arguments.
- PATH has a fake bin folder first, then only the system folders (no Homebrew, pyenv, ...). The fakes:
  xcode-select (points to a folder whose usr/bin/git is the real git), scutil (no proxy), open (logs what it opens),
  kiro-cli (logged in while the file kiro-logged-in exists), and per test python3 / gh.
- gh (the one in the release zip, or one on PATH) is FAKE_GH: GitHub (the login, repos, Projects) is one JSON file.
"""
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent / "kiro" / "install.sh"
TASK = INSTALL.parent.parent / "bin" / "task"
GH_TAG, UV_TAG = "v2.0.0", "0.9.0"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
ZPROFILE_LINE = 'export PATH="$HOME/.local/bin:$PATH"'
FAKE_TASK = '#!/usr/bin/env python3\nimport sys\nprint("task", sys.executable, *sys.argv[1:])\n'
NO_PROXY_SCUTIL = "<dictionary> {\n  ExceptionsList : <array> {\n    0 : *.local\n  }\n}\n"
TASK_HUB_STATUS = ["Backlog", "Ready", "In progress", "In review", "wait for merge", "Blocked", "Done"]
TEXT_FIELDS = ["Target repo", "Agent", "Base branch"]
# what a new Project has (seen on github.com, 2026-10-02)
NEW_WORKFLOWS = ["Auto-add sub-issues to project", "Auto-close issue", "Item added to project", "Item closed",
                 "Pull request linked to issue", "Pull request merged"]
STATUS_WORKFLOWS = ["Item added to project", "Pull request linked to issue", "Pull request merged"]

FAKE_GH = r'''#!@PYTHON@
import fcntl, json, os, sys, time
a = sys.argv[1:]
if a == ["--version"]:
    print("gh version @VERSION@ (fake)")
    sys.exit(0)
DB = os.environ["TASK_TEST_GH_DB"]

def opt(name):
    return a[a.index(name) + 1] if name in a else None

class Fail(Exception):
    pass

def load():
    return json.load(open(DB))

def save(db):
    with open(DB + ".tmp", "w") as f:
        json.dump(db, f)
    os.replace(DB + ".tmp", DB)

def lock():
    f = open(DB + ".lock", "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f

def project(db, owner=None, number=None, pid=None):
    for p in db["projects"]:
        if p["id"] == pid or (p["owner"] == owner and str(p["number"]) == str(number)):
            return p
    raise Fail(f"Could not resolve to a ProjectV2 with the number {number}.")

if a[:2] in (["auth", "login"], ["auth", "refresh"]):
    # like gh without a terminal: the code on stderr, then wait for the approval (the test sets "approve")
    with lock():
        db = load()
        db["calls"].append(a)
        save(db)
    print(f"! One-time code ({db['code']}) copied to clipboard", file=sys.stderr)
    print("Open this URL to continue in your web browser: https://github.com/login/device", file=sys.stderr, flush=True)
    for _ in range(300):
        time.sleep(0.1)
        if not os.path.exists(DB):
            sys.exit(1)
        with lock():
            db = load()
            if db.get("approve"):
                scopes = (db["auth"] or {}).get("scopes", "repo")
                db["auth"] = {"login": db["approve"], "scopes": scopes if "project" in scopes.split(", ")
                              else scopes + ", project"}
                db["approve"] = None
                save(db)
                sys.exit(0)
    sys.exit(1)

def handle(db):
    auth = db["auth"]
    if a[:2] == ["auth", "status"]:
        if not auth:
            raise Fail("You are not logged into any GitHub hosts. To log in, run: gh auth login")
        return f"github.com\n  Logged in to github.com account {auth['login']}"
    if not auth:
        raise Fail("To get started with GitHub CLI, please run:  gh auth login")
    if a == ["api", "-i", "user"]:
        return (f"HTTP/2.0 200 OK\r\nContent-Type: application/json\r\nX-Oauth-Scopes: {auth['scopes']}\r\n\r\n"
                + json.dumps({"login": auth["login"], "id": 1}, separators=(",", ":")))
    if a[:2] == ["auth", "setup-git"]:
        with open(os.path.join(os.environ["HOME"], ".gitconfig"), "a") as f:
            f.write(f'[credential "https://github.com"]\n\thelper =\n\thelper = !{sys.argv[0]} auth git-credential\n')
        return ""
    if a[:2] == ["repo", "view"]:
        if a[2] not in db["repos"]:
            raise Fail(f"GraphQL: Could not resolve to a Repository with the name '{a[2]}'. (repository)")
        return json.dumps({"name": a[2].split("/")[1]})
    if a[:2] == ["repo", "create"]:
        if a[2] in db["repos"]:
            raise Fail("GraphQL: Name already exists on this account (createRepository)")
        db["repos"][a[2]] = {"private": "--private" in a, "description": opt("--description")}
        return f"https://github.com/{a[2]}"
    if a[:2] == ["project", "list"]:
        ps = [{k: p[k] for k in ("number", "title", "id", "url")} for p in db["projects"] if p["owner"] == opt("--owner")]
        return json.dumps({"projects": ps, "totalCount": len(ps)})
    if a[:2] == ["project", "create"]:
        owner = opt("--owner")
        n = max([p["number"] for p in db["projects"] if p["owner"] == owner], default=0) + 1
        p = {"owner": owner, "number": n, "title": opt("--title"), "id": f"PVT_{owner}_{n}", "items": 0,
             "url": f"https://github.com/users/{owner}/projects/{n}", "repos": [], "views": [{"layout": "TABLE_LAYOUT"}],
             "fields": [{"id": f"F{n}_title", "name": "Title", "dataType": "TITLE"},
                        {"id": f"F{n}_status", "name": "Status", "dataType": "SINGLE_SELECT", "options": [
                            {"id": "todo1", "name": "Todo", "color": "GREEN", "description": "This item hasn't been started"},
                            {"id": "prog1", "name": "In Progress", "color": "YELLOW", "description": "Being worked on"},
                            {"id": "done1", "name": "Done", "color": "PURPLE", "description": "This has been completed"}]},
                        {"id": f"F{n}_labels", "name": "Labels", "dataType": "LABELS"}],
             "workflows": [{"id": f"W{n}_{i}", "name": w, "enabled": True} for i, w in enumerate(@WORKFLOWS@)]}
        db["projects"].append(p)
        return json.dumps({k: p[k] for k in ("number", "title", "id", "url")})
    if a[:2] == ["project", "view"]:
        p = project(db, opt("--owner"), a[2])
        return json.dumps({k: p[k] for k in ("number", "title", "id", "url")})
    if a[:2] == ["project", "field-create"]:
        p = project(db, opt("--owner"), a[2])
        assert opt("--data-type") == "TEXT", a
        p["fields"].append({"id": f"F{p['number']}_{len(p['fields'])}", "name": opt("--name"), "dataType": "TEXT"})
        return json.dumps(p["fields"][-1])
    if a[:2] == ["project", "link"]:
        p = project(db, opt("--owner"), a[2])
        p["repos"].append(f"{opt('--owner')}/{opt('--repo')}")
        return ""
    if a[:3] == ["api", "-X", "POST"]:
        _, owner, _, number, _ = a[3].strip("/").split("/")
        p = project(db, owner, number)
        p["views"].append({"layout": "BOARD_LAYOUT", "name": a[a.index("-f", 4) + 1]})
        return "{}"
    if a[:2] == ["api", "graphql"]:
        if "--input" in a:
            body = json.load(sys.stdin)
            q, v = body["query"], body["variables"]
        else:  # bin/task: -f name=value
            pairs = dict(x.split("=", 1) for x in a[3::2])
            q, v = pairs.pop("query"), pairs
        kind = next(k for k, word in (("set-options", "updateProjectV2Field"), ("delete-workflow", "deleteProjectV2Workflow"),
                                      ("board-state", "workflows("), ("items", "items("), ("fields", "fields("), ("?", ""))
                    if word in q)
        db["calls"][-1] = ["api", "graphql", kind]  # what it asked, not how
        if "updateProjectV2Field" in q:
            for p in db["projects"]:
                for f in p["fields"]:
                    if f["id"] == v["field"]:
                        for i, o in enumerate(v["options"]):
                            assert set(o) - {"id"} == {"name", "color", "description"}, o
                            o.setdefault("id", f"opt{len(db['calls'])}_{i}")
                        f["options"] = v["options"]
                        return json.dumps({"data": {"updateProjectV2Field": {"clientMutationId": None}}})
            raise Fail("GraphQL: Could not resolve to a node")
        if "deleteProjectV2Workflow" in q:
            for p in db["projects"]:
                if any(w["id"] == v["id"] for w in p["workflows"]):
                    p["workflows"] = [w for w in p["workflows"] if w["id"] != v["id"]]
                    return json.dumps({"data": {"deleteProjectV2Workflow": {"deletedWorkflowId": v["id"]}}})
            raise Fail("GraphQL: Could not resolve to a node")
        p = project(db, pid=v["id"])
        if "workflows(" in q:  # kiro/install-board
            return json.dumps({"data": {"node": {
                "url": p["url"], "items": {"totalCount": p["items"]}, "fields": {"nodes": p["fields"]},
                "workflows": {"nodes": p["workflows"]},
                "repositories": {"nodes": [{"nameWithOwner": r} for r in p["repos"]]},
                "views": {"nodes": [{"layout": x["layout"]} for x in p["views"]]}}}})
        if "items(" in q:  # bin/task: the cards (none)
            return json.dumps({"data": {"node": {"items": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                                           "nodes": []}}}})
        if "fields(" in q:  # bin/task: the fields
            return json.dumps({"data": {"node": {"fields": {"nodes": p["fields"]}}}})
    raise Fail(f"fake gh: unknown command {a}")

with lock():
    db = load()
    db["calls"].append(a)
    try:
        out = handle(db)
    except Fail as e:
        save(db)
        print(e, file=sys.stderr)
        sys.exit(1)
    save(db)
print(out)
'''.replace("@PYTHON@", sys.executable).replace("@WORKFLOWS@", repr(NEW_WORKFLOWS))


def fake_gh(version):
    return FAKE_GH.replace("@VERSION@", version)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o755 << 16
            z.writestr(info, text)
    return buf.getvalue()


def tar_bytes(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Releases(http.server.ThreadingHTTPServer):
    """A tiny GitHub: `files` maps a path to bytes, `redirects` a path to another path. Logs every path asked for."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), ReleasesHandler)
        self.files, self.redirects, self.log = {"/": b"github"}, {}, []
        self.url = f"http://127.0.0.1:{self.server_address[1]}"


class ReleasesHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.reply(body=False)

    def do_GET(self):
        self.reply(body=True)

    def reply(self, body):
        srv = self.server
        srv.log.append(self.path)
        if self.path in srv.redirects:
            self.send_response(302)
            self.send_header("Location", srv.url + srv.redirects[self.path])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = srv.files.get(self.path)
        self.send_response(200 if data is not None else 404)
        data = data if data is not None else b"not found"
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)

    def log_message(self, *args):
        pass


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.root = Path(self.tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.fakebin = root / "fakebin"
        self.fakebin.mkdir()
        # xcode-select -p -> a developer folder with a working git, unless the test removes it
        self.dev = root / "dev"
        (self.dev / "usr/bin").mkdir(parents=True)
        (self.dev / "usr/bin/git").symlink_to(shutil.which("git"))
        self.script("xcode-select", f'#!/bin/sh\n[ -d "{self.dev}" ] || exit 2\necho "{self.dev}"\n')
        self.set_scutil(NO_PROXY_SCUTIL)
        self.opened = root / "opened.txt"
        self.script("open", f'#!/bin/sh\necho "$*" >> "{self.opened}"\n')
        self.kiro_logged_in = root / "kiro-logged-in"
        self.kiro_logged_in.touch()
        self.script("kiro-cli", f'#!/bin/sh\n[ "$1" = whoami ] || exit 2\n[ -e "{self.kiro_logged_in}" ] && exit 0\n'
                                'echo "Not logged in" >&2\nexit 1\n')
        self.gh_db = root / "gh.json"
        self.gh_db.write_text(json.dumps({"auth": {"login": "alice", "scopes": "gist, project, read:org, repo"},
                                          "code": "ABCD-1234", "approve": None, "repos": {}, "projects": [],
                                          "calls": []}))
        self.addCleanup(self.stop_gh_login)
        self.uv_calls = root / "uv-calls.txt"
        self.server = Releases()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.publish_gh()
        self.publish_uv()
        git_id = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
                  "GIT_COMMITTER_EMAIL": "t@e"}
        self.git_env = {**os.environ, **git_id}
        self.make_origin()
        self.env = {k: v for k, v in os.environ.items()
                    if k.lower() not in ("https_proxy", "http_proxy", "all_proxy", "no_proxy", "gh_token",
                                         "github_token", "task_install_gh_login")}
        self.env.update(git_id, HOME=str(self.home), PATH=f"{self.fakebin}:{SYSTEM_PATH}",
                        TASK_INSTALL_GITHUB=self.server.url, TASK_INSTALL_REPO=f"file://{root}/origin.git",
                        TASK_TEST_GH_DB=str(self.gh_db))

    # --- helpers ---

    def script(self, name, text):
        (self.fakebin / name).write_text(text)
        (self.fakebin / name).chmod(0o755)

    def set_scutil(self, text):
        self.script("scutil", f"#!/bin/sh\ncat <<'EOF'\n{text}EOF\n")

    def use_python3(self):
        """Put a Python 3.10+ on PATH as python3 (a link to the one running the tests)."""
        (self.fakebin / "python3").symlink_to(sys.executable)
        return str(self.fakebin / "python3")

    def publish_gh(self, sums_for=None):
        ver = GH_TAG.removeprefix("v")
        base = f"/cli/cli/releases/download/{GH_TAG}"
        self.server.redirects["/cli/cli/releases/latest"] = f"/cli/cli/releases/tag/{GH_TAG}"
        self.server.files[f"/cli/cli/releases/tag/{GH_TAG}"] = b"release page"
        sums = []
        for arch in ("arm64", "amd64"):
            name = f"gh_{ver}_macOS_{arch}"
            data = zip_bytes({f"{name}/bin/gh": fake_gh(ver),
                              f"{name}/LICENSE": "MIT\n"})
            self.server.files[f"{base}/{name}.zip"] = data
            sums.append(f"{sha256((sums_for or {}).get(arch, data))}  {name}.zip")
        sums.append(f"{sha256(b'other')}  gh_{ver}_linux_amd64.tar.gz")
        self.server.files[f"{base}/gh_{ver}_checksums.txt"] = ("\n".join(sums) + "\n").encode()

    def publish_uv(self):
        base = f"/astral-sh/uv/releases/download/{UV_TAG}"
        self.server.redirects["/astral-sh/uv/releases/latest"] = f"/astral-sh/uv/releases/tag/{UV_TAG}"
        self.server.files[f"/astral-sh/uv/releases/tag/{UV_TAG}"] = b"release page"
        # The fake uv: `uv python install 3.12` links python3.12 to the Python running the tests.
        uv = (f'#!/bin/sh\necho "$* UV_SYSTEM_CERTS=${{UV_SYSTEM_CERTS:-}} HTTPS_PROXY=${{HTTPS_PROXY:-}}"'
              f' >> "{self.uv_calls}"\n'
              '[ "$1 $2" = "python install" ] || exit 2\n'
              'dir=${UV_PYTHON_BIN_DIR:-$HOME/.local/bin}\n'
              f'mkdir -p "$dir" && ln -sf "{sys.executable}" "$dir/python$3"\n')
        for triple in ("aarch64-apple-darwin", "x86_64-apple-darwin"):
            name = f"uv-{triple}.tar.gz"
            data = tar_bytes({f"uv-{triple}/uv": uv, f"uv-{triple}/uvx": "#!/bin/sh\n"})
            self.server.files[f"{base}/{name}"] = data
            self.server.files[f"{base}/{name}.sha256"] = f"{sha256(data)}  {name}\n".encode()

    def make_origin(self, task=FAKE_TASK):
        src = self.root / "src"
        (src / "bin").mkdir(parents=True)
        (src / "bin/task").write_text(task)
        (src / "bin/task").chmod(0o755)
        for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"], ["git", "commit", "-qm", "init"],
                    ["git", "clone", "-q", "--bare", str(src), str(self.root / "origin.git")]):
            subprocess.run(cmd, cwd=src, env=self.git_env, check=True, capture_output=True)

    def install(self, code=0):
        r = subprocess.run(["sh", str(INSTALL)], env=self.env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertTrue(lines[-1].startswith("次にすること: "), lines)  # one next step, on the last line
        self.assertEqual(sum(line.startswith("次にすること") for line in lines), 1, lines)
        return lines

    def downloads(self):
        return [p for p in self.server.log if p != "/"]  # "/": the reachability check

    def manifest(self):
        return json.loads((self.home / ".local/state/task-hub/install-manifest.json").read_text())

    def snapshot(self):
        """Every file under HOME with its content (links as their target), to see that a run changed nothing.
        Not git's own files in the clone (`pull` writes FETCH_HEAD even when there is nothing new)."""
        out = {}
        for p in sorted(self.home.rglob("*")):
            rel = str(p.relative_to(self.home))
            if rel.startswith(".local/lib/task-hub/.git/"):
                continue
            if p.is_symlink():
                out[rel] = "-> " + os.readlink(p)
            elif p.is_file():
                out[rel] = p.read_bytes()
        return out

    def stage_lines(self, lines):
        return [line for line in lines if line[:2] in ("1.", "2.", "3.", "5.", "6.", "7.", "8.")]

    def github(self):
        return json.loads(self.gh_db.read_text())

    def change_github(self, change):
        db = self.github()
        change(db)
        self.gh_db.write_text(json.dumps(db))

    def gh_calls(self):
        return [c for c in self.github()["calls"] if c != ["api", "-i", "user"]]

    def writes(self):
        """The gh calls that change GitHub (or the login)."""
        reads = (["repo", "view"], ["project", "list"], ["project", "view"], ["auth", "status"])
        return [c for c in self.gh_calls() if c[:2] not in reads
                and c not in (["api", "graphql", k] for k in ("board-state", "items", "fields"))]

    def project(self, owner="alice", number=1):
        return next(p for p in self.github()["projects"] if p["owner"] == owner and p["number"] == number)

    def field(self, project, name):
        return next(f for f in project["fields"] if f["name"] == name)

    def config(self):
        return (self.home / ".config/task-hub/config.ini").read_text()

    def login_pid(self):
        f = self.home / ".local/state/task-hub/gh-login.pid"
        return int(f.read_text()) if f.exists() else None

    def stop_gh_login(self):
        """The fake `gh auth login` an install left in the background (it would end by itself after 30 s)."""
        pid = self.login_pid()
        if pid:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

    def wait_gone(self, pid):
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        self.fail(f"process {pid} is still running")

    # --- tests ---

    def test_installs_everything_and_a_second_run_changes_nothing(self):
        lines = self.install()
        local = self.home / ".local"
        self.assertTrue(any(line.startswith("2. Python: 入れました") for line in lines), lines)
        self.assertTrue(any(line.startswith("3. gh: 入れました") for line in lines), lines)
        self.assertTrue(any(line.startswith("5. task-hub 本体: 入れました") for line in lines), lines)
        self.assertIn("6. GitHub のログイン: 設定しました(alice、git も gh のログインを使います)", lines)
        self.assertIn("6. kiro-cli のログイン: 済み", lines)
        self.assertTrue(any(line.startswith("7. ボード: 作りました(https://github.com/users/alice/projects/1、alice/tasks: "
                                            "private の alice/tasks、Project alice/1、") for line in lines), lines)
        self.assertTrue(any(line.startswith("8. 設定: 作りました(~/.config/task-hub/config.ini。task list で確かめました)")
                            for line in lines), lines)
        self.assertEqual(lines[-1], "次にすること: Kiro との連携(docs/kiro-ide.md)を進めてください。"
                                    "この段階はまだインストーラにありません")
        # uv from its release, then Python through uv (trusting the keychain); /usr/bin/python3 was not used
        self.assertEqual(self.uv_calls.read_text().splitlines(), ["python install 3.12 UV_SYSTEM_CERTS=1 HTTPS_PROXY="])
        self.assertTrue((local / "bin/uv").is_file())
        python = str(local / "bin/python3.12")
        # gh from the zip, checked against checksums.txt
        gh = subprocess.run([str(local / "bin/gh"), "--version"], capture_output=True, text=True)
        self.assertIn("gh version 2.0.0 (fake)", gh.stdout)
        # task-hub cloned; ~/.local/bin/task runs bin/task with the chosen Python, not through its #! line
        self.assertTrue((local / "lib/task-hub/bin/task").is_file())
        wrapper = local / "bin/task"
        self.assertFalse(wrapper.is_symlink())
        self.assertIn(f"exec '{python}' '{local}/lib/task-hub/bin/task' \"$@\"", wrapper.read_text())
        out = subprocess.run([str(wrapper), "hello", "a b"], capture_output=True, text=True, env=self.env)
        self.assertEqual(out.stdout.split()[:1] + out.stdout.split()[2:], ["task", "hello", "a", "b"], out.stderr)
        self.assertEqual((self.home / ".zprofile").read_text().count(ZPROFILE_LINE), 1)
        self.assertEqual(self.manifest(), {
            "version": 1, "python": python,
            "installed": {"uv": str(local / "bin/uv"), "uv-python": "3.12", "gh": str(local / "bin/gh"),
                          "task-hub": str(local / "lib/task-hub"), "task": str(wrapper), "zprofile": ZPROFILE_LINE,
                          "config": str(self.home / ".config/task-hub/config.ini")}})
        self.assertEqual([p for p in (self.home / ".local/state/task-hub").iterdir() if p.name.startswith("install.")],
                         [], "the work folder is removed")

        head = lambda: subprocess.run(["git", "-C", str(local / "lib/task-hub"), "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout
        before, head_before, self.server.log[:] = self.snapshot(), head(), []
        self.change_github(lambda db: db["calls"].clear())
        lines = self.install()
        stages = self.stage_lines(lines)
        self.assertEqual([line.split(":")[0] for line in stages],
                         ["1. 前提の確認", "2. Python", "3. gh", "5. task-hub 本体", "6. GitHub のログイン",
                          "6. kiro-cli のログイン", "7. ボード", "8. 設定"])
        self.assertTrue(all(line.split(": ", 1)[1].startswith("済み") for line in stages), stages)
        self.assertIn("すべて済みです。変えたものはありません。", lines)
        self.assertEqual(self.downloads(), [])
        self.assertEqual(len(self.uv_calls.read_text().splitlines()), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(head(), head_before)
        self.assertEqual(self.writes(), [], "nothing on GitHub is made or changed again")

    def test_uses_a_python3_of_3_10_or_later_on_path(self):
        self.script("python3.13", "#!/bin/sh\nexit 1\n")  # a pyenv shim of a version that is not installed
        python = self.use_python3()
        lines = self.install()
        self.assertIn(f"2. Python: 済み({python} を使います)", lines)
        self.assertFalse([p for p in self.downloads() if "astral-sh" in p], "uv is not downloaded")
        self.assertFalse((self.home / ".local/bin/uv").exists())
        self.assertFalse(self.uv_calls.exists())
        self.assertIn(f"exec '{python}' ", (self.home / ".local/bin/task").read_text())
        m = self.manifest()
        self.assertEqual(m["python"], python)
        self.assertEqual(sorted(m["installed"]), ["config", "gh", "task", "task-hub", "zprofile"])  # not the Python

    def test_uses_a_gh_already_on_path(self):
        self.use_python3()
        self.script("gh", fake_gh("9.9.9"))
        lines = self.install()
        self.assertIn(f"3. gh: 済み({self.fakebin}/gh)", lines)
        self.assertFalse([p for p in self.downloads() if "/cli/cli/" in p])
        self.assertFalse((self.home / ".local/bin/gh").exists())
        self.assertNotIn("gh", self.manifest()["installed"])

    def test_stops_when_a_checksum_does_not_match(self):
        self.use_python3()
        self.publish_gh(sums_for={"arm64": b"tampered", "amd64": b"tampered"})
        lines = self.install(code=1)
        self.assertTrue(any(line.startswith("3. gh: 止まりました。") and "チェックサムが合いません" in line
                            for line in lines), lines)
        self.assertFalse((self.home / ".local/bin/gh").exists())
        self.assertFalse((self.home / ".local/lib/task-hub").exists(), "later stages do not run")
        # and uv's
        (self.fakebin / "python3").unlink()
        triple = "aarch64-apple-darwin" if os.uname().machine == "arm64" else "x86_64-apple-darwin"
        self.server.files[f"/astral-sh/uv/releases/download/{UV_TAG}/uv-{triple}.tar.gz.sha256"] = \
            f"{sha256(b'tampered')}  uv-{triple}.tar.gz\n".encode()
        lines = self.install(code=1)
        self.assertTrue(any(line.startswith("2. Python: 止まりました。") and "チェックサムが合いません" in line
                            for line in lines), lines)
        self.assertFalse((self.home / ".local/bin/uv").exists())

    def test_stops_with_a_request_to_it_when_git_is_missing(self):
        for case in ("no developer tools", "no git in them"):
            with self.subTest(case):
                if case == "no developer tools":
                    shutil.rmtree(self.dev)
                else:
                    (self.dev / "usr/bin").mkdir(parents=True)
                lines = self.install(code=1)
                self.assertTrue(lines[1].startswith("1. 前提の確認: 止まりました。git がありません"), lines)
                self.assertIn("情シスへの依頼文:", lines)
                self.assertTrue(any("Command Line Tools を入れてください" in line for line in lines), lines)
                self.assertEqual(lines[-1], "次にすること: 上の依頼文を情シスに送り、入ったらもう一度実行してください")
                self.assertEqual(self.server.log, [])
                self.assertFalse((self.home / ".local/bin").exists())
                self.assertFalse((self.home / ".local/state/task-hub/install-manifest.json").exists())

    def test_takes_the_https_proxy_from_the_system_settings(self):
        self.set_scutil("<dictionary> {\n  HTTPSEnable : 1\n  HTTPSPort : 8080\n  HTTPSProxy : proxy.example\n}\n")
        lines = self.install()  # the test server is http://, so curl does not go through it
        self.assertIn("1. 前提の確認: 済み(macOS " + ("arm64" if os.uname().machine == "arm64" else "x86_64")
                      + "、git、GitHub に接続、プロキシ http://proxy.example:8080)", lines)
        self.assertIn("HTTPS_PROXY=http://proxy.example:8080", self.uv_calls.read_text())

    def test_stops_when_github_is_unreachable_behind_a_pac_file(self):
        self.set_scutil("<dictionary> {\n  ProxyAutoConfigEnable : 1\n"
                        "  ProxyAutoConfigURLString : http://wpad/proxy.pac\n}\n")
        self.env["TASK_INSTALL_GITHUB"] = "http://127.0.0.1:9"  # nothing listens there
        lines = self.install(code=1)
        self.assertTrue(lines[1].startswith("1. 前提の確認: 止まりました。GitHub に届きません。"), lines)
        self.assertIn("PAC", lines[1])
        self.assertIn("HTTPS_PROXY=http://ホスト:ポート", lines[-1])

    def test_replaces_the_link_of_the_manual_install_but_not_a_file_of_its_own(self):
        python = self.use_python3()
        bindir = self.home / ".local/bin"
        bindir.mkdir(parents=True)
        (bindir / "task").write_text("#!/bin/sh\necho mine\n")
        lines = self.install(code=1)
        self.assertTrue(lines[-2].startswith("5. task-hub 本体: 止まりました。~/.local/bin/task が既にあります"), lines)
        self.assertEqual((bindir / "task").read_text(), "#!/bin/sh\necho mine\n")
        # docs/setup.md's `ln -sfn ~/.local/lib/task-hub/bin/task ~/.local/bin/task`
        (bindir / "task").unlink()
        (bindir / "task").symlink_to(self.home / ".local/lib/task-hub/bin/task")
        self.install()
        self.assertFalse((bindir / "task").is_symlink())
        self.assertIn(f"exec '{python}' ", (bindir / "task").read_text())

    def test_does_not_touch_zprofile_when_local_bin_is_on_path(self):
        self.use_python3()
        self.env["PATH"] = f"{self.home}/.local/bin:{self.env['PATH']}"
        self.install()
        self.assertFalse((self.home / ".zprofile").exists())
        self.assertNotIn("zprofile", self.manifest()["installed"])


    # --- login, board, config.ini ---

    def test_a_new_user_gets_the_repo_the_project_with_its_fields_and_config_ini(self):
        self.use_python3()
        self.install()
        gh = self.github()
        self.assertEqual(gh["repos"], {"alice/tasks": {"private": True,
                                                       "description": "task-hub のタスク(kiro/install.sh が作りました)"}})
        p = self.project()
        self.assertEqual(p["title"], "task-hub")
        status = self.field(p, "Status")
        self.assertEqual([o["name"] for o in status["options"]], TASK_HUB_STATUS)
        self.assertEqual(next(o["id"] for o in status["options"] if o["name"] == "Done"), "done1",
                         "Done keeps its id: Item closed moves cards to it")
        self.assertEqual([self.field(p, n)["dataType"] for n in TEXT_FIELDS], ["TEXT"] * 3)
        self.assertEqual(p["repos"], ["alice/tasks"])
        self.assertEqual(sorted(w["name"] for w in p["workflows"]),
                         sorted(set(NEW_WORKFLOWS) - set(STATUS_WORKFLOWS)))
        self.assertIn("BOARD_LAYOUT", [v["layout"] for v in p["views"]])
        self.assertEqual(self.config(), "; task-hub の設定。kiro/install.sh が作りました(書き方は docs/setup.md)\n"
                                        "[board]\nproject = alice/1\nissues = alice/tasks\n\n[runner]\nagent = kiro\n\n"
                                        "[check]\nkiro = kiro-cli whoami\n\n[ide]\nopen = kiro {path}\n")
        self.assertIn('helper = !', (self.home / ".gitconfig").read_text())
        self.assertFalse(self.opened.exists(), "nothing to do by hand")

    def test_task_list_works_on_the_board_it_made(self):
        """With the real bin/task, which checks the Status options and the text fields of the board."""
        self.use_python3()
        shutil.rmtree(self.root / "src")
        shutil.rmtree(self.root / "origin.git")
        self.make_origin(task=TASK.read_text())
        lines = self.install()
        self.assertTrue(any(line.startswith("8. 設定: 作りました(") and "task list で確かめました" in line
                            for line in lines), lines)
        self.assertIn(["api", "graphql", "items"], self.github()["calls"])
        # a board in use that lost a column it needs: the column is added back, and task list works again
        def drop_blocked(db):
            status = next(f for f in db["projects"][0]["fields"] if f["name"] == "Status")
            status["options"] = [o for o in status["options"] if o["name"] != "Blocked"]
            db["projects"][0]["items"] = 1
        self.change_github(drop_blocked)
        self.install()
        self.assertIn("Blocked", [o["name"] for o in self.field(self.project(), "Status")["options"]])

    def test_stops_until_gh_is_logged_in_and_goes_on_from_there(self):
        self.use_python3()
        self.change_github(lambda db: db.update(auth=None))
        lines = self.install(code=1)
        self.assertEqual(lines[-2], "6. GitHub のログイン: 止まりました。GitHub にログインしていません。ブラウザで "
                                    "https://github.com/login/device を開きました。コード ABCD-1234 を入れて承認してください")
        self.assertEqual(lines[-1], "次にすること: 承認が終わったら、もう一度実行してください")
        self.assertEqual(self.opened.read_text(), "https://github.com/login/device\n")
        self.assertIn(["auth", "login", "--web", "-s", "project", "-h", "github.com", "-p", "https"], self.gh_calls())
        self.assertEqual(self.github()["repos"], {}, "later stages do not run")
        pid = self.login_pid()
        os.kill(pid, 0)  # still waiting, after the install ended
        # run again before the approval: no second login, the same code
        lines = self.install(code=1)
        self.assertEqual(lines[-1], "次にすること: https://github.com/login/device でコード ABCD-1234 を入れて承認してから、"
                                    "もう一度実行してください")
        self.assertEqual(self.login_pid(), pid)
        self.assertEqual(sum(c[:2] == ["auth", "login"] for c in self.gh_calls()), 1)
        # approved in the browser: gh gets the token and ends; the next run goes on
        self.change_github(lambda db: db.update(approve="alice"))
        self.wait_gone(pid)
        lines = self.install()
        self.assertIn("6. GitHub のログイン: 設定しました(alice、git も gh のログインを使います)", lines)
        self.assertIn("alice/tasks", self.github()["repos"])
        self.assertIsNone(self.login_pid())
        self.assertFalse((self.home / ".local/state/task-hub/gh-login.log").exists())

    def test_adds_the_project_scope_when_gh_lacks_it(self):
        self.use_python3()
        self.change_github(lambda db: db["auth"].update(scopes="gist, read:project, repo"))
        lines = self.install(code=1)
        self.assertIn("Projects の権限(project)が要ります", lines[-2])
        self.assertIn(["auth", "refresh", "-h", "github.com", "-s", "project"], self.gh_calls())
        self.change_github(lambda db: db.update(approve="alice"))
        self.wait_gone(self.login_pid())
        self.install()
        self.assertEqual(self.github()["auth"]["scopes"], "gist, read:project, repo, project")

    def test_logs_in_in_a_terminal_when_the_background_login_is_gone(self):
        self.use_python3()
        self.change_github(lambda db: db.update(auth=None))
        self.install(code=1)
        pid = self.login_pid()
        os.kill(pid, 9)  # as if it was stopped with the command that ran the installer
        self.wait_gone(pid)
        lines = self.install(code=1)
        self.assertEqual(lines[-2], "6. GitHub のログイン: 止まりました。GitHub にログインしていません。"
                                    "開いたターミナルで、案内に沿ってブラウザで承認してください")
        command = self.home / ".local/state/task-hub/gh-login.command"
        self.assertEqual(self.opened.read_text().splitlines()[-1], str(command))
        self.assertTrue(os.access(command, os.X_OK))
        self.assertIn(f"'{self.home}/.local/bin/gh' 'auth' 'login' '--web' '-s' 'project' '-h' 'github.com' '-p' 'https'",
                      command.read_text())
        self.assertEqual(sum(c[:2] == ["auth", "login"] for c in self.gh_calls()), 1, "no second background login")
        # logged in there: the next run goes on and tidies up
        self.change_github(lambda db: db.update(auth={"login": "alice", "scopes": "project, repo"}))
        self.install()
        self.assertFalse(command.exists())
        # TASK_INSTALL_GH_LOGIN=terminal: in a terminal from the start
        self.change_github(lambda db: db.update(auth=None))
        self.env["TASK_INSTALL_GH_LOGIN"] = "terminal"
        self.install(code=1)
        self.assertTrue(command.exists())
        self.assertIsNone(self.login_pid())

    def test_stops_when_a_gh_token_is_set_and_gh_cannot_log_in(self):
        self.use_python3()
        self.change_github(lambda db: db.update(auth=None))
        self.env["GH_TOKEN"] = "ghp_x"
        lines = self.install(code=1)
        self.assertIn("環境変数 GH_TOKEN(または GITHUB_TOKEN)があるので、gh ではログインできません", lines[-2])
        self.assertNotIn("auth", [c[0] for c in self.gh_calls()])
        self.assertFalse(self.opened.exists())

    def test_stops_until_kiro_cli_is_logged_in(self):
        self.use_python3()
        self.kiro_logged_in.unlink()
        lines = self.install(code=1)
        self.assertEqual(lines[-2], "6. kiro-cli のログイン: 止まりました。kiro-cli にログインしていません。"
                                    "開いたターミナルで、ログインの方法を選んでブラウザで承認してください")
        command = self.home / ".local/state/task-hub/kiro-login.command"
        self.assertEqual(self.opened.read_text(), f"{command}\n")
        self.assertIn(f"'{self.fakebin}/kiro-cli' 'login'", command.read_text())
        self.assertEqual(self.github()["projects"], [], "later stages do not run")
        self.kiro_logged_in.touch()
        lines = self.install()
        self.assertIn("6. kiro-cli のログイン: 済み", lines)
        self.assertFalse(command.exists())
        # no kiro-cli at all: what works without it goes on (installing it is a stage of its own)
        (self.fakebin / "kiro-cli").unlink()
        lines = self.install()
        self.assertIn("6. kiro-cli のログイン: 飛ばしました(kiro-cli が見つかりません。Kiro IDE だけで使う範囲は進めます)", lines)

    def test_keeps_an_existing_board_and_config_ini_and_only_adds_what_is_missing(self):
        self.use_python3()
        def board_in_use(db):  # alice's own board, in use: some columns, one text field, her workflows
            p = {"owner": "alice", "number": 1, "title": "my board", "id": "PVT_alice_1", "items": 3,
                 "url": "https://github.com/users/alice/projects/1", "repos": [], "views": [{"layout": "TABLE_LAYOUT"}]}
            db["projects"].append(p)
            p["fields"] = [{"id": "S", "name": "Status", "dataType": "SINGLE_SELECT", "options": [
                {"id": "b1", "name": "backlog", "color": "GRAY", "description": ""},
                {"id": "r1", "name": "Ready", "color": "BLUE", "description": "go"},
                {"id": "p1", "name": "In progress", "color": "YELLOW", "description": ""},
                {"id": "v1", "name": "In review", "color": "ORANGE", "description": ""},
                {"id": "s1", "name": "Someday", "color": "GRAY", "description": ""},
                {"id": "d1", "name": "Done", "color": "GREEN", "description": ""}]},
                {"id": "T", "name": "target repo", "dataType": "TEXT"}]
            p["workflows"] = [{"id": "W1", "name": "Item closed", "enabled": False},
                              {"id": "W2", "name": "Pull request merged", "enabled": True}]
        self.change_github(board_in_use)
        ini = self.home / ".config/task-hub/config.ini"
        ini.parent.mkdir(parents=True)
        mine = ("; mine\n[board]\nproject = alice/1   ; my board\nissues = alice/work\n\n[runner]\nagent = claude\n"
                "reviewer = agent\n\n[setup]\nalice/app = uv venv -q .venv\n  uv pip install -q -r requirements.txt\n")
        ini.write_text(mine)
        lines = self.install()

        p = self.project()
        self.assertEqual([(o["id"], o["name"]) for o in self.field(p, "Status")["options"]],
                         [("b1", "backlog"), ("r1", "Ready"), ("p1", "In progress"), ("v1", "In review"),
                          ("s1", "Someday"), ("d1", "Done"), (self.field(p, "Status")["options"][6]["id"], "Blocked")])
        self.assertEqual(self.field(p, "Status")["options"][1]["description"], "go")
        self.assertEqual([f["name"] for f in p["fields"]], ["Status", "target repo", "Agent", "Base branch"])
        self.assertEqual([(w["name"], w["enabled"]) for w in p["workflows"]],
                         [("Item closed", False), ("Pull request merged", True)], "the user's workflows: said, not changed")
        self.assertEqual(p["repos"], [], "no link to the issues repo of the config")
        self.assertEqual(self.github()["repos"], {})
        self.assertFalse([c for c in self.writes() if c[:2] in (["repo", "create"], ["project", "create"],
                                                                ["project", "link"], ["api", "-X"])], self.writes())
        todo = ("https://github.com/users/alice/projects/1/workflows を開き、「Item closed」を有効に、"
                "「Pull request merged」を無効にしてください(task-hub が動かす Status を変えないため)")
        self.assertIn(f"7. ボード: 画面での操作が残っています。{todo}", lines)
        self.assertEqual(lines[-1], f"次にすること: {todo}")
        self.assertTrue(any(line.startswith("7. ボード: 足しました(https://github.com/users/alice/projects/1、alice/work: "
                                            "Status の選択肢 Blocked、テキスト欄 Agent・Base branch)") for line in lines), lines)

        self.assertEqual(ini.read_text(), "; mine\n[board]\nproject = alice/1   ; my board\nissues = alice/work\n\n"
                                          "[runner]\nagent = claude\nreviewer = agent\n\n[setup]\nalice/app = uv venv -q .venv\n"
                                          "  uv pip install -q -r requirements.txt\n\n[check]\nkiro = kiro-cli whoami\n\n"
                                          "[ide]\nopen = kiro {path}\n")
        backups = list(ini.parent.glob("config.ini.bak-*"))
        self.assertEqual([b.read_text() for b in backups], [mine])
        self.assertTrue(any(line.startswith(f"8. 設定: 足しました(~/.config/task-hub/config.ini に [check] kiro、[ide] open。"
                                            f"元の内容は ~/.config/task-hub/{backups[0].name}。") for line in lines), lines)
        self.assertNotIn("config", self.manifest()["installed"], "the user's file, not the installer's")

        # again: nothing more to add, the same by-hand step
        self.change_github(lambda db: db["calls"].clear())
        before = ini.read_text()
        lines = self.install()
        self.assertEqual(self.writes(), [])
        self.assertEqual(ini.read_text(), before)
        self.assertEqual(len(list(ini.parent.glob("config.ini.bak-*"))), 1)
        self.assertEqual(lines[-1], f"次にすること: {todo}")

    def test_adds_a_missing_option_to_a_section_and_keeps_the_values_there(self):
        self.use_python3()
        ini = self.home / ".config/task-hub/config.ini"
        ini.parent.mkdir(parents=True)
        ini.write_text("[runner]\nagent = kiro\n\n[ide]\nopen =\n[check]\n  ; nothing yet\n")
        self.install()
        self.assertEqual(ini.read_text(), "[runner]\nagent = kiro\n\n[ide]\nopen =\n[check]\n  ; nothing yet\n"
                                          "kiro = kiro-cli whoami\n\n[board]\nproject = alice/1\nissues = alice/tasks\n")

    def test_stops_on_a_board_config_it_cannot_use(self):
        self.use_python3()
        ini = self.home / ".config/task-hub/config.ini"
        ini.parent.mkdir(parents=True)
        for text, why in (("[board]\nproject = https://github.com/users/alice/projects/1\n", "[board] が正しくありません"),
                          ("[board]\nproject = alice/1\nproject = alice/2\n", "を読めません")):
            with self.subTest(why):
                ini.write_text(text)
                lines = self.install(code=1)
                self.assertTrue(lines[-2].startswith("7. ボード: 止まりました。~/.config/task-hub/config.ini "), lines)
                self.assertIn(why, lines[-2])
                self.assertEqual(ini.read_text(), text)
                self.assertEqual(self.github()["projects"], [])


if __name__ == "__main__":
    unittest.main()
