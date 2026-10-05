"""Black-box tests of kiro/install.sh: run it with `sh`, with HOME a temporary folder.

- GitHub Releases is a local HTTP server (TASK_INSTALL_GITHUB) with fake gh and uv archives and their checksums,
  so nothing is downloaded for real. releases/latest redirects to a tag, as on github.com.
- task-hub is cloned from a local bare repo (TASK_INSTALL_REPO), whose bin/task only prints its arguments.
- PATH has a fake bin folder first, then only the system folders (no Homebrew, pyenv, ...). The fakes:
  xcode-select (points to a folder whose usr/bin/git is the real git), scutil (no proxy), open (logs what it opens),
  kiro-cli (logged in while the file kiro-logged-in exists), hdiutil (a "disk image" is a tar), codesign,
  launchctl (never the real one: it logs, and keeps "loaded" in a file), security (no keychain), and per test python3 / gh.
  For slack-triage/hotkey/build.sh: xcrun (finds the fake swiftc while it is there), swiftc (the "program" it builds is
  a script that exits 2 when run without arguments, as the real one does, with its source in it) and lipo.
- Kiro CLI's download server is the same local server (TASK_INSTALL_KIRO_CLI), with a manifest.json and a "DMG".
  /Applications is a folder of the test (TASK_INSTALL_APPLICATIONS), so the Mac's own Kiro CLI.app is not found.
- gh (the one in the release zip, or one on PATH) is FAKE_GH: GitHub (the login, repos, Projects) is one JSON file.
"""
import base64
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
import unittest
import zipfile
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent / "kiro" / "install.sh"
DOCTOR, UNINSTALL = INSTALL.with_name("doctor.sh"), INSTALL.with_name("uninstall.sh")
REPO = INSTALL.parent.parent
TASK = REPO / "bin" / "task"
# what stage 9 puts in ~/.kiro, from the clone: (in the clone, in ~/.kiro)
KIRO_LINKS = [("skills/task", "skills/task"), ("skills/chief", "skills/chief"),
              ("kiro/steering/task-hub.md", "steering/task-hub.md")]
KIRO_COPIES = [("kiro/hooks/task-hub-events.json", "hooks/task-hub-events.json"),
               ("kiro/workflows/task-hub-events.workflow.json", "workflows/task-hub-events.workflow.json")]
KIRO_SETTINGS = "Library/Application Support/Kiro/User/settings.json"
PLIST = "Library/LaunchAgents/com.task-hub.watch.plist"
ST_PLIST = "Library/LaunchAgents/com.task-hub.slack-triage.plist"
KIRO_CLI_VERSION = "2.26.1"
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
import fcntl, json, os, sys
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
    # The test runs the Terminal .command with an explicit fake browser approval. Never opens a real GUI.
    with lock():
        db = load()
        db["calls"].append(a)
        if any(os.environ.get(k) != v for k, v in db.get("required_login_env", {}).items()):
            print("Required login environment is missing", file=sys.stderr)
            sys.exit(1)
        if not db.get("approve"):
            print("Browser approval is required", file=sys.stderr)
            sys.exit(1)
        scopes = (db["auth"] or {}).get("scopes", "repo")
        db["auth"] = {"login": db["approve"], "scopes": scopes if "project" in scopes.split(", ")
                      else scopes + ", project"}
        db["approve"] = None
        save(db)
    print(f"! One-time code ({db['code']}) copied to clipboard", file=sys.stderr)
    print("Open this URL to continue in your web browser: https://github.com/login/device", file=sys.stderr, flush=True)
    sys.exit(0)

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
        # for github.com, and for the test's GitHub (TASK_INSTALL_GITHUB), which plays it
        with open(os.path.join(os.environ["HOME"], ".gitconfig"), "a") as f:
            for host in ("https://github.com", os.environ.get("TASK_INSTALL_GITHUB")):
                if host:
                    f.write(f'[credential "{host}"]\n\thelper =\n\thelper = !{sys.argv[0]} auth git-credential\n')
        return ""
    if a[:2] == ["auth", "git-credential"]:  # git asks for the login (get), or tells how it went (store, erase)
        sys.stdin.read()
        return f"username=x-access-token\npassword=gho_{auth['login']}" if a[2:] == ["get"] else ""
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
        if "repositoryOwner(" in q:  # bin/task: the Project and its fields
            p = project(db, v["owner"], v["number"])
            return json.dumps({"data": {"repositoryOwner": {"projectV2": {
                "id": p["id"], "url": p["url"], "fields": {"nodes": p["fields"]}}}}})
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
    """A tiny GitHub: `files` maps a path to bytes, `redirects` a path to another path. Logs every path asked for.
    /git/<path>: the files of git_root/<path>, for git's dumb HTTP, and only with the token the fake gh gives git for
    alice (as a private repo on github.com)."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), ReleasesHandler)
        self.files, self.redirects, self.log = {"/": b"github"}, {}, []
        self.git_root = None
        self.git_auth = "Basic " + base64.b64encode(b"x-access-token:gho_alice").decode()
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
        if self.path.startswith("/git/") and srv.git_root:
            if self.headers.get("Authorization") != srv.git_auth:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="GitHub"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            f = srv.git_root / self.path.split("?")[0].removeprefix("/git/")
            data = f.read_bytes() if f.is_file() else None
        else:
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
        self.script("kiro-cli", self.fake_kiro_cli("on PATH"))
        self.applications = root / "Applications"
        self.hdiutil_calls, self.codesign_calls = root / "hdiutil-calls.txt", root / "codesign-calls.txt"
        self.script("hdiutil", f'#!/bin/sh\necho "$*" >> "{self.hdiutil_calls}"\nfor a; do last=$a; done\n'
                               'case $1 in\n  attach)\n'
                               f'    [ -e "{root}/hdiutil-fails" ] && {{ echo "hdiutil: attach failed - not permitted" >&2; exit 1; }}\n'
                               '    while [ $# -gt 0 ]; do [ "$1" = -mountpoint ] && mp=$2; shift; done\n'
                               '    mkdir -p "$mp" && tar -xzf "$last" -C "$mp" ;;\n'
                               '  detach) rm -rf "$last" ;;\n  *) exit 2 ;;\nesac\n')
        self.script("codesign", f'#!/bin/sh\necho "$*" >> "{self.codesign_calls}"\n'
                                f'[ -e "{root}/codesign-fails" ] && {{ echo "$4: invalid signature" >&2; exit 1; }}\nexit 0\n')
        self.swiftc_calls = root / "swiftc-calls.txt"
        self.script("xcrun", f'#!/bin/sh\n[ "$*" = "--find swiftc" ] && [ -x "{self.fakebin}/swiftc" ] && echo "{self.fakebin}/swiftc"\n')
        self.script("swiftc", f'#!/bin/sh\necho "$*" >> "{self.swiftc_calls}"\n'
                              'while [ $# -gt 1 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
                              '{ echo "#!/bin/sh"; sed "s/^/# /" "$1"; echo "exit 2"; } > "$out" && chmod 755 "$out"\n')
        self.script("lipo", '#!/bin/sh\n[ "$1" = -create ] || exit 0\ncp "$4" "$3"\n')
        self.launchctl_calls, self.launchd_loaded = root / "launchctl-calls.txt", root / "launchd-loaded"
        # Slack triage's agent (com.task-hub.slack-triage) has its own log and state; when it is bootstrapped, the
        # fake writes the status the real program writes once it holds the key
        self.st_calls, self.st_loaded = root / "slack-triage-launchctl-calls.txt", root / "slack-triage-loaded"
        self.st_status = self.home / ".local/state/task-hub/slack-triage-hotkey.status"
        self.script("launchctl", '#!/bin/sh\ncase "$*" in\n  *slack-triage*)\n'
                                 f'    echo "$*" >> "{self.st_calls}"\n    case $1 in\n'
                                 f'      print) [ -e "{self.st_loaded}" ] ;;\n'
                                 f'      bootstrap) touch "{self.st_loaded}"; echo "ok ctrl,opt+s" > "{self.st_status}" ;;\n'
                                 f'      bootout) rm -f "{self.st_loaded}" ;;\n'
                                 f'      kickstart) echo "ok ctrl,opt+s" > "{self.st_status}" ;;\n'
                                 '      *) exit 2 ;;\n    esac\n    exit ;;\nesac\n'
                                 f'echo "$*" >> "{self.launchctl_calls}"\ncase $1 in\n'
                                 f'  print) [ -e "{self.launchd_loaded}" ] ;;\n'
                                 f'  bootstrap) touch "{self.launchd_loaded}" ;;\n'
                                 f'  bootout) rm -f "{self.launchd_loaded}" ;;\n  *) exit 2 ;;\nesac\n')
        self.api_key = root / "api-key-in-keychain"
        self.script("security", f'#!/bin/sh\n[ "$1" = find-generic-password ] && [ -e "{self.api_key}" ]\n')
        self.gh_db = root / "gh.json"
        self.gh_db.write_text(json.dumps({"auth": {"login": "alice", "scopes": "gist, project, read:org, repo"},
                                          "code": "ABCD-1234", "approve": None, "repos": {}, "projects": [],
                                          "calls": []}))
        self.uv_calls = root / "uv-calls.txt"
        self.server = Releases()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.publish_gh()
        self.publish_uv()
        self.publish_kiro_cli()
        git_id = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
                  "GIT_COMMITTER_EMAIL": "t@e"}
        self.git_env = {**os.environ, **git_id}
        self.make_origin()
        self.env = {k: v for k, v in os.environ.items()
                    if k.lower() not in ("https_proxy", "http_proxy", "all_proxy", "no_proxy", "gh_token",
                                         "github_token")}
        self.env.update(git_id, HOME=str(self.home), PATH=f"{self.fakebin}:{SYSTEM_PATH}",
                        TASK_INSTALL_GITHUB=self.server.url, TASK_INSTALL_REPO=f"file://{root}/origin.git",
                        TASK_INSTALL_KIRO_CLI=self.server.url + "/kiro", TASK_INSTALL_APPLICATIONS=str(self.applications),
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
        # The fake uv: `uv python install 3.12` links python3.12 to the Python running the tests; uninstall unlinks it.
        uv = (f'#!/bin/sh\necho "$* UV_SYSTEM_CERTS=${{UV_SYSTEM_CERTS:-}} HTTPS_PROXY=${{HTTPS_PROXY:-}}"'
              f' >> "{self.uv_calls}"\n'
              'dir=${UV_PYTHON_BIN_DIR:-$HOME/.local/bin}\n'
              'case "$1 $2" in\n'
              f'  "python install") mkdir -p "$dir" && ln -sf "{sys.executable}" "$dir/python$3" ;;\n'
              '  "python uninstall") rm -f "$dir/python$3" ;;\n'
              '  *) exit 2 ;;\nesac\n')
        for triple in ("aarch64-apple-darwin", "x86_64-apple-darwin"):
            name = f"uv-{triple}.tar.gz"
            data = tar_bytes({f"uv-{triple}/uv": uv, f"uv-{triple}/uvx": "#!/bin/sh\n"})
            self.server.files[f"{base}/{name}"] = data
            self.server.files[f"{base}/{name}.sha256"] = f"{sha256(data)}  {name}\n".encode()

    def fake_kiro_cli(self, where):
        return (f'#!/bin/sh\ncase $1 in\n  --version) echo "kiro-cli {KIRO_CLI_VERSION} ({where})" ;;\n'
                f'  whoami) [ -e "{self.kiro_logged_in}" ] && exit 0; echo "Not logged in" >&2; exit 1 ;;\n'
                '  *) exit 2 ;;\nesac\n')

    def publish_kiro_cli(self, sha=None):
        """The manifest.json of prod.download.cli.kiro.dev (its form on 2026-10-02), and a "DMG" (a tar for the fake
        hdiutil) with Kiro CLI.app in it."""
        dmg = tar_bytes({"Kiro CLI.app/Contents/MacOS/kiro-cli": self.fake_kiro_cli("from the DMG"),
                         "Kiro CLI.app/Contents/Info.plist": "<plist/>\n"})
        base = "/kiro/stable"
        self.server.files[f"{base}/latest/manifest.json"] = json.dumps({"version": KIRO_CLI_VERSION, "packages": [
            {"os": "linux", "fileType": "zip", "architecture": "x86_64", "download": f"{KIRO_CLI_VERSION}/kirocli.zip",
             "sha256": sha256(b"linux")},
            {"os": "macos", "fileType": "dmg", "architecture": "universal", "download": f"{KIRO_CLI_VERSION}/Kiro CLI.dmg",
             "sha256": sha or sha256(dmg), "cliPath": "Contents/MacOS/kiro-cli"}]}).encode()
        self.server.files[f"{base}/{KIRO_CLI_VERSION}/Kiro%20CLI.dmg"] = dmg

    def make_origin(self, task=FAKE_TASK):
        src = self.root / "src"
        (src / "bin").mkdir(parents=True)
        (src / "bin/task").write_text(task)
        (src / "bin/task").chmod(0o755)
        for path, _ in KIRO_LINKS + KIRO_COPIES + [("slack-triage", None)]:  # the real ones
            (src / path).parent.mkdir(parents=True, exist_ok=True)
            if (REPO / path).is_dir():
                shutil.copytree(REPO / path, src / path, ignore=shutil.ignore_patterns("__pycache__", "slack-triage-hotkey*"))
            else:
                shutil.copy(REPO / path, src / path)
        for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"], ["git", "commit", "-qm", "init"],
                    ["git", "clone", "-q", "--bare", str(src), str(self.root / "origin.git")]):
            subprocess.run(cmd, cwd=src, env=self.git_env, check=True, capture_output=True)

    def change_origin(self, path, text):
        """A new commit in task-hub's repo, that the next install pulls."""
        src = self.root / "src"
        (src / path).write_text(text)
        for cmd in (["git", "commit", "-qam", f"change {path}"], ["git", "push", "-q", str(self.root / "origin.git"), "main"]):
            subprocess.run(cmd, cwd=src, env=self.git_env, check=True, capture_output=True)

    def tag_origin(self, name):
        """A release of task-hub, as docs/kiro-ide.md says: `git tag -a` on main, then `git push origin <tag>`."""
        src = self.root / "src"
        for cmd in (["git", "tag", "-a", name, "-m", f"release {name}"],
                    ["git", "push", "-q", str(self.root / "origin.git"), name]):
            subprocess.run(cmd, cwd=src, env=self.git_env, check=True, capture_output=True)

    def release(self, name):
        """A new commit on main with that tag on it."""
        self.change_origin("bin/task", FAKE_TASK + f"# {name}\n")
        self.tag_origin(name)

    def lib_git(self, *args):
        r = subprocess.run(["git", "-C", str(self.home / ".local/lib/task-hub"), *args], capture_output=True, text=True)
        return r.stdout.strip()

    def lib_at(self):
        """Where ~/.local/lib/task-hub is: "branch main" or "tag <the tag at HEAD>", and whether HEAD is that of origin."""
        branch = self.lib_git("symbolic-ref", "-q", "--short", "HEAD")
        head = self.lib_git("rev-parse", "HEAD")
        origin = lambda ref: subprocess.run(["git", "-C", str(self.root / "origin.git"), "rev-parse", f"{ref}^{{commit}}"],
                                            capture_output=True, text=True).stdout.strip()
        if branch:
            self.assertEqual(head, origin(branch), "the branch is up to date")
            return f"branch {branch}"
        tag = self.lib_git("describe", "--tags", "--exact-match", "HEAD")
        self.assertEqual(head, origin(tag))
        return f"tag {tag}"

    def short(self, ref="main"):
        return subprocess.run(["git", "-C", str(self.root / "origin.git"), "rev-parse", "--short", ref],
                              capture_output=True, text=True).stdout.strip()

    def line6(self, lines):
        return next(line for line in lines if line.startswith("6. "))

    def doctor6(self, lines):
        i = next(i for i, line in enumerate(lines) if line.startswith(("○ 6. ", "× 6. ")))
        return lines[i:i + 2] if lines[i + 1].startswith("    (") else lines[i:i + 1]

    def install(self, code=0, args=()):
        r = subprocess.run(["sh", str(INSTALL), *args], env=self.env, capture_output=True, text=True,
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
        return [line for line in lines if line.split(".")[0].isdigit()]

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

    def finish_github_login(self):
        """Complete the Terminal command using the fake gh and fake browser approval, no real Terminal."""
        command = self.home / ".local/state/task-hub/gh-login.command"
        self.assertTrue(command.exists())
        self.change_github(lambda db: db.update(approve="alice"))
        terminal_env = {k: self.env[k] for k in ("HOME", "PATH", "TASK_TEST_GH_DB")}
        r = subprocess.run(["sh", str(command)], env=terminal_env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNotNone(self.github()["auth"], "Terminal login must receive its required environment")
        self.assertEqual(self.github()["auth"]["login"], "alice")

    # --- tests ---

    def test_installs_everything_and_a_second_run_changes_nothing(self):
        lines = self.install()
        local = self.home / ".local"
        self.assertTrue(any(line.startswith("2. Python: 入れました") for line in lines), lines)
        self.assertTrue(any(line.startswith("3. gh: 入れました") for line in lines), lines)
        self.assertTrue(any(line.startswith("6. task-hub 本体: 入れました") for line in lines), lines)
        self.assertIn("5. GitHub のログイン: 設定しました(alice、git も gh のログインを使います)", lines)
        self.assertIn("5. kiro-cli のログイン: 済み", lines)
        self.assertTrue(any(line.startswith("7. ボード: 作りました(https://github.com/users/alice/projects/1、alice/tasks: "
                                            "private の alice/tasks、Project alice/1、") for line in lines), lines)
        self.assertTrue(any(line.startswith("8. 設定: 作りました(~/.config/task-hub/config.ini。task list で確かめました)")
                            for line in lines), lines)
        self.assertIn(f"4. kiro-cli: リンクしました(~/.local/bin/kiro-cli → {self.fakebin}/kiro-cli)", lines)
        self.assertTrue(any(line.startswith("9. Kiro との連携: 入れました(") and "Kiro を再起動すると読み込まれます" in line
                            for line in lines), lines)
        self.assertIn("10. 常駐: 飛ばしました(任意です。task watch を launchd で動かすときは --with-launchd を付けて実行します)",
                      lines)
        self.assertEqual(lines[-1], "次にすること: Kiro を再起動し(開いているチャットには、少なくともウィンドウの再読み込みが"
                                    "要ります)、新しいチャットで /task を試してください")
        self.assertFalse((self.home / PLIST).exists())
        self.assertFalse(self.launchctl_calls.exists(), "launchctl is not run without --with-launchd")
        self.assertFalse(self.hdiutil_calls.exists())
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
            "kiro-cli-target": str(self.fakebin / "kiro-cli"),
            "installed": {"uv": str(local / "bin/uv"), "uv-python": "3.12", "gh": str(local / "bin/gh"),
                          "kiro-cli": str(local / "bin/kiro-cli"),
                          "task-hub": str(local / "lib/task-hub"), "task": str(wrapper), "zprofile": ZPROFILE_LINE,
                          "config": str(self.home / ".config/task-hub/config.ini"),
                          "kiro-skill-task": str(self.home / ".kiro/skills/task"),
                          "kiro-skill-chief": str(self.home / ".kiro/skills/chief"),
                          "kiro-steering": str(self.home / ".kiro/steering/task-hub.md"),
                          "kiro-hook": str(self.home / ".kiro/hooks/task-hub-events.json"),
                          "kiro-workflow": str(self.home / ".kiro/workflows/task-hub-events.workflow.json"),
                          "kiro-settings": str(self.home / KIRO_SETTINGS),
                          "slack-triage": str(local / "bin/slack-triage"),
                          "slack-triage-launchd": str(self.home / ST_PLIST)},
            "sha256": {"kiro-hook": hashlib.sha256((REPO / KIRO_COPIES[0][0]).read_bytes()).hexdigest(),
                       "kiro-workflow": hashlib.sha256((REPO / KIRO_COPIES[1][0]).read_bytes()).hexdigest()}})
        self.assertEqual([p for p in (self.home / ".local/state/task-hub").iterdir() if p.name.startswith("install.")],
                         [], "the work folder is removed")

        head = lambda: subprocess.run(["git", "-C", str(local / "lib/task-hub"), "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout
        before, head_before, self.server.log[:] = self.snapshot(), head(), []
        self.change_github(lambda db: db["calls"].clear())
        lines = self.install()
        stages = self.stage_lines(lines)
        self.assertEqual([line.split(":")[0] for line in stages],
                         ["1. 前提の確認", "2. Python", "3. gh", "4. kiro-cli", "5. GitHub のログイン", "5. kiro-cli のログイン",
                          "6. task-hub 本体", "7. ボード", "8. 設定", "9. Kiro との連携", "10. 常駐", "11. Slackトリアージ"])
        self.assertTrue(all(line.split(": ", 1)[1].startswith("済み") for line in stages if not line.startswith("10. ")),
                        stages)
        self.assertIn("すべて済みです。変えたものはありません。", lines)
        self.assertEqual(lines[-1], "次にすること: Kiro の新しいチャットで /task を試してください")
        self.assertEqual(self.downloads(), [])
        self.assertEqual(len(self.uv_calls.read_text().splitlines()), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(head(), head_before)
        self.assertEqual(self.writes(), [], "nothing on GitHub is made or changed again")

    def test_a_new_clone_is_on_the_default_branch_when_there_is_no_kiro_tag(self):
        self.use_python3()
        self.tag_origin("v1")  # not a release tag
        self.change_origin("bin/task", FAKE_TASK + "# after v1\n")
        lines = self.install()
        self.assertEqual(self.lib_at(), "branch main")
        self.assertIn(f"clone(main {self.short()})", self.line6(lines))
        self.assertEqual(self.doctor6(self.doctor(0)),
                         [f"○ 6. task-hub 本体: ~/.local/lib/task-hub(main {self.short()})、~/.local/bin/task、~/.zprofile に PATH"])
        # main moves on: the installer's clone follows it while there is no release
        before = self.short()
        self.change_origin("bin/task", FAKE_TASK + "# more\n")
        lines = self.install()
        self.assertEqual(self.line6(lines), f"6. task-hub 本体: 入れました(main {before} → main {self.short()})")
        self.assertEqual(self.lib_at(), "branch main")
        # the first release: the installer's clone (in the manifest) moves from main to it
        self.release("kiro-v1")
        lines = self.install()
        self.assertEqual(self.line6(lines), f"6. task-hub 本体: 入れました(main {self.short('main~1')} → kiro-v1)")
        self.assertEqual(self.lib_at(), "tag kiro-v1")

    def test_a_new_clone_is_on_the_newest_kiro_tag_and_moves_to_a_newer_one(self):
        self.use_python3()
        for name in ("kiro-v1", "kiro-v2", "kiro-v10", "kiro-v9"):  # kiro-v10 is the newest: numbers, not text
            self.release(name)
        self.release("kiro-v11-rc")  # not kiro-v<number>
        self.change_origin("bin/task", FAKE_TASK + "# main, after the releases\n")
        lines = self.install()
        self.assertEqual(self.lib_at(), "tag kiro-v10")
        self.assertIn("clone(kiro-v10)", self.line6(lines))
        self.assertIn("# kiro-v10", (self.home / ".local/lib/task-hub/bin/task").read_text())
        self.assertEqual(self.doctor6(self.doctor(0)),
                         ["○ 6. task-hub 本体: ~/.local/lib/task-hub(kiro-v10、最新)、~/.local/bin/task、~/.zprofile に PATH"])
        # main moves on, with no new release: it stays
        self.change_origin("bin/task", FAKE_TASK + "# main, later\n")
        lines = self.install()
        self.assertEqual(self.line6(lines), "6. task-hub 本体: 済み(~/.local/lib/task-hub(kiro-v10)、~/.local/bin/task)")
        self.assertEqual(self.lib_at(), "tag kiro-v10")
        # a new release: the diagnosis says so and changes nothing; the next install moves to it
        self.release("kiro-v12")
        before = self.snapshot()
        self.assertEqual(self.doctor6(self.doctor(0)),
                         ["○ 6. task-hub 本体: ~/.local/lib/task-hub(kiro-v10)、~/.local/bin/task、~/.zprofile に PATH",
                          "    (新しい版 kiro-v12 があります。sh kiro/install.sh を実行してください(Kiro のチャットなら"
                          "「セットアップして」))"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.lib_at(), "tag kiro-v10")
        lines = self.install()
        self.assertEqual(self.line6(lines), "6. task-hub 本体: 入れました(kiro-v10 → kiro-v12)")
        self.assertEqual(self.lib_at(), "tag kiro-v12")
        self.assertIn("# kiro-v12", (self.home / ".local/lib/task-hub/bin/task").read_text())

    def test_a_clone_on_a_branch_made_by_hand_is_only_pulled(self):
        """A developer's clone (as on the machine task-hub is made on): it keeps following main."""
        self.use_python3()
        self.release("kiro-v1")
        lib = self.home / ".local/lib/task-hub"
        subprocess.run(["git", "clone", "-q", f"file://{self.root}/origin.git", str(lib)], check=True, capture_output=True)
        self.change_origin("bin/task", FAKE_TASK + "# main, after kiro-v1\n")
        self.release("kiro-v2")
        before = self.short("main~2")
        lines = self.install()
        self.assertEqual(self.line6(lines)[:len("6. task-hub 本体: 入れました(")], "6. task-hub 本体: 入れました(")
        self.assertIn(f"main {before} → main {self.short()}", self.line6(lines))
        self.assertEqual(self.lib_at(), "branch main")
        self.assertNotIn("task-hub", self.manifest()["installed"], "the installer did not make it")
        self.assertEqual(self.doctor6(self.doctor(0)),
                         [f"○ 6. task-hub 本体: ~/.local/lib/task-hub(main {self.short()})、~/.local/bin/task、~/.zprofile に PATH",
                          "    (ブランチ main の上の clone です。インストーラはタグに切り替えず、pull だけします)"])
        self.change_origin("bin/task", FAKE_TASK + "# main, later\n")
        self.install()
        self.assertEqual(self.lib_at(), "branch main")

    def test_ref_chooses_the_version(self):
        self.use_python3()
        self.release("kiro-v1")
        self.release("kiro-v2")
        self.change_origin("bin/task", FAKE_TASK + "# main, after the releases\n")
        lines = self.install(args=["--ref", "main"])
        self.assertIn(f"clone(main {self.short()})", self.line6(lines))
        self.assertEqual(self.lib_at(), "branch main")
        self.assertEqual(self.manifest()["installed"]["task-hub"], str(self.home / ".local/lib/task-hub"))
        lines = self.install(args=["--ref=kiro-v1"])
        self.assertEqual(self.line6(lines), f"6. task-hub 本体: 入れました(main {self.short()} → kiro-v1)")
        self.assertEqual(self.lib_at(), "tag kiro-v1")
        self.install(args=["--ref", "main"])
        self.assertEqual(self.lib_at(), "branch main")
        # --ref is for that run only: without it, the installer's clone goes back to the newest release
        lines = self.install()
        self.assertEqual(self.line6(lines), f"6. task-hub 本体: 入れました(main {self.short()} → kiro-v2)")
        self.assertEqual(self.lib_at(), "tag kiro-v2")
        lines = self.install(1, ["--ref", "kiro-v99"])
        self.assertEqual(lines[-2:], ["6. task-hub 本体: 止まりました。kiro-v99 という版(ブランチかタグ)がありません",
                                      "次にすること: --ref の名前を確かめて、もう一度実行してください"])
        self.assertEqual(self.lib_at(), "tag kiro-v2")
        lines = self.install(1, ["--ref"])
        self.assertEqual(lines[-1], "次にすること: sh kiro/install.sh --ref kiro-v1 のように実行してください")
        # a new clone of a tag
        shutil.rmtree(self.home / ".local/lib/task-hub")
        lines = self.install(args=["--ref", "kiro-v1"])
        self.assertIn("clone(kiro-v1)", self.line6(lines))
        self.assertEqual(self.lib_at(), "tag kiro-v1")
        shutil.rmtree(self.home / ".local/lib/task-hub")
        lines = self.install(1, ["--ref", "kiro-v99"])
        self.assertTrue(lines[-2].startswith(f"6. task-hub 本体: 止まりました。file://{self.root}/origin.git の kiro-v99 を "
                                             "clone できませんでした("), lines)

    def test_doctor_on_a_ref_compares_commits_with_the_newest_kiro_tag(self):
        """The installer's clone on --ref main: a kiro-v* older than main is not a new version, and nothing is fetched."""
        self.use_python3()
        self.release("kiro-v1")
        self.change_origin("bin/task", FAKE_TASK + "# main, after kiro-v1\n")
        self.install(args=["--ref", "main"])
        self.assertEqual(self.lib_at(), "branch main")
        line = f"○ 6. task-hub 本体: ~/.local/lib/task-hub(main {self.short()})、~/.local/bin/task、~/.zprofile に PATH"
        self.assertEqual(self.doctor6(self.doctor(0)),
                         [line, f"    (配布版 kiro-v1 より新しい main({self.short()}) です。次にインストーラを実行すると "
                                "kiro-v1 に戻ります(main を続けるなら --ref main))"])
        # a release after it, not fetched yet: its commit is not here, so it is not known which is newer
        self.release("kiro-v2")
        before = self.snapshot()
        self.assertEqual(self.doctor6(self.doctor(0)),
                         [line, "    (新しい版があるかは確かめられませんでした(kiro-v2 のコミットが手元にありません))"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.lib_git("tag", "-l", "kiro-v2"), "", "the diagnosis fetched nothing")
        self.assertNotEqual(subprocess.run(["git", "-C", str(self.home / ".local/lib/task-hub"), "cat-file", "-e",
                                            f"{self.short('kiro-v2^{commit}')}^{{commit}}"], capture_output=True).returncode, 0)
        # once fetched: the tag's commit is not in main's history here, so it is a new version
        self.lib_git("fetch", "-q", "--tags")
        self.assertEqual(self.doctor6(self.doctor(0)),
                         [line, "    (新しい版 kiro-v2 があります。sh kiro/install.sh を実行してください(Kiro のチャットなら"
                                "「セットアップして」))"])
        # main on the release's commit
        self.install(args=["--ref", "main"])
        self.assertEqual(self.doctor6(self.doctor(0)),
                         [f"○ 6. task-hub 本体: ~/.local/lib/task-hub(main {self.short()})、~/.local/bin/task、~/.zprofile に PATH",
                          f"    (配布版 kiro-v2 と同じコミットの main({self.short()}) です。次にインストーラを実行すると "
                          "kiro-v2 に戻ります(main を続けるなら --ref main))"])
        self.install()
        self.assertEqual(self.lib_at(), "tag kiro-v2")
        self.assertEqual(self.doctor6(self.doctor(0)),
                         ["○ 6. task-hub 本体: ~/.local/lib/task-hub(kiro-v2、最新)、~/.local/bin/task、~/.zprofile に PATH"])

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
        self.assertNotIn("uv-python", m["installed"])  # not the Python
        self.assertNotIn("uv", m["installed"])

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
        self.assertTrue(lines[-2].startswith("6. task-hub 本体: 止まりました。~/.local/bin/task が既にあります"), lines)
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
        self.assertEqual(lines[-2], "5. GitHub のログイン: 止まりました。GitHub にログインしていません。"
                                    "開いたターミナルで、案内に沿ってブラウザで承認してください")
        self.assertEqual(lines[-1], "次にすること: 承認が終わったら、もう一度実行してください")
        command = self.home / ".local/state/task-hub/gh-login.command"
        self.assertEqual(self.opened.read_text(), f"{command}\n")
        self.assertIn("'auth' 'login' '--web' '-s' 'project' '-h' 'github.com' '-p' 'https'", command.read_text())
        self.assertFalse(any(c[:2] == ["auth", "login"] for c in self.gh_calls()))
        self.assertEqual(self.github()["repos"], {}, "later stages do not run")
        # Re-running before approval leaves authentication in Terminal, with no background login process.
        lines = self.install(code=1)
        self.assertEqual(lines[-1], "次にすること: 承認が終わったら、もう一度実行してください")
        self.assertFalse((command.parent / "gh-login.pid").exists())
        self.assertFalse((command.parent / "gh-login.log").exists())
        self.assertFalse(any(c[:2] == ["auth", "login"] for c in self.gh_calls()))
        self.finish_github_login()
        self.assertIn(["auth", "login", "--web", "-s", "project", "-h", "github.com", "-p", "https"], self.gh_calls())
        lines = self.install()
        self.assertIn("5. GitHub のログイン: 設定しました(alice、git も gh のログインを使います)", lines)
        self.assertIn("alice/tasks", self.github()["repos"])
        self.assertFalse(command.exists())

    def test_clones_the_private_repo_only_after_the_github_login(self):
        """task-hub's repo is private: git can read it only with gh's login (gh auth setup-git), as on github.com."""
        self.use_python3()
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"  # not the Mac's osxkeychain helper: no test password in the keychain
        subprocess.run(["git", "-C", str(self.root / "origin.git"), "update-server-info"], check=True)
        self.server.git_root = self.root
        url = self.env["TASK_INSTALL_REPO"] = f"{self.server.url}/git/origin.git"
        git_asked = lambda: [p for p in self.server.log if p.startswith("/git/")]
        # without the login, git cannot clone it (what stopped stage 5 when it came before the login)
        r = subprocess.run(["git", "clone", "-q", url, str(self.root / "no-login")], capture_output=True, text=True,
                           env={**self.env, "GIT_TERMINAL_PROMPT": "0"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not read Username", r.stderr)
        self.server.log[:] = []
        # not logged in: it stops at the login, and does not try to clone
        self.change_github(lambda db: db.update(auth=None))
        lines = self.install(code=1)
        self.assertTrue(lines[-2].startswith("5. GitHub のログイン: 止まりました。GitHub にログインしていません。"), lines)
        self.assertFalse(any(line.startswith("6. ") for line in lines), lines)
        self.assertEqual(git_asked(), [], "no clone before the login")
        self.assertFalse((self.home / ".local/lib/task-hub").exists())
        # logged in: git uses gh's login, and the clone goes through
        self.finish_github_login()
        lines = self.install()
        self.assertIn("5. GitHub のログイン: 設定しました(alice、git も gh のログインを使います)", lines)
        self.assertIn(f"clone(main {self.short()})", self.line6(lines))
        self.assertEqual(self.lib_at(), "branch main")
        self.assertIn(["auth", "git-credential", "get"], self.gh_calls())
        self.assertTrue(git_asked())
        lines = self.install()  # a second run fetches with the same login
        self.assertEqual(self.line6(lines), f"6. task-hub 本体: 済み(~/.local/lib/task-hub(main {self.short()})、~/.local/bin/task)")

    def test_adds_the_project_scope_when_gh_lacks_it(self):
        self.use_python3()
        self.change_github(lambda db: db["auth"].update(scopes="gist, read:project, repo"))
        lines = self.install(code=1)
        self.assertIn("Projects の権限(project)が要ります", lines[-2])
        command = self.home / ".local/state/task-hub/gh-login.command"
        self.assertIn("'auth' 'refresh' '-h' 'github.com' '-s' 'project'", command.read_text())
        self.finish_github_login()
        self.assertIn(["auth", "refresh", "-h", "github.com", "-s", "project"], self.gh_calls())
        self.install()
        self.assertEqual(self.github()["auth"]["scopes"], "gist, read:project, repo, project")

    def test_github_login_opens_an_executable_terminal_command(self):
        self.use_python3()
        self.change_github(lambda db: db.update(auth=None))
        lines = self.install(code=1)
        self.assertEqual(lines[-2], "5. GitHub のログイン: 止まりました。GitHub にログインしていません。"
                                    "開いたターミナルで、案内に沿ってブラウザで承認してください")
        command = self.home / ".local/state/task-hub/gh-login.command"
        self.assertEqual(self.opened.read_text().splitlines()[-1], str(command))
        self.assertTrue(os.access(command, os.X_OK))
        self.assertIn(f"'{self.home}/.local/bin/gh' 'auth' 'login' '--web' '-s' 'project' '-h' 'github.com' '-p' 'https'",
                      command.read_text())
        self.assertEqual(sum(c[:2] == ["auth", "login"] for c in self.gh_calls()), 0, "the installer delegates to Terminal")
        # logged in there: the next run goes on and tidies up
        self.finish_github_login()
        self.install()
        self.assertFalse(command.exists())

    def test_terminal_github_login_keeps_the_system_proxy(self):
        self.use_python3()
        self.set_scutil("<dictionary> {\n  HTTPSEnable : 1\n  HTTPSPort : 8080\n  HTTPSProxy : proxy.example\n}\n")
        required = {"HTTPS_PROXY": "http://proxy.example:8080"}
        self.change_github(lambda db: db.update(auth=None, required_login_env=required))
        self.install(code=1)
        self.finish_github_login()

    def test_terminal_login_keeps_private_network_and_config_environment(self):
        self.use_python3()
        required = {"https_proxy": "http://user:p'ass@proxy.example:8080", "NO_PROXY": "localhost,127.0.0.1",
                    "ALL_PROXY": "socks5://proxy.example:1080", "GH_CONFIG_DIR": str(self.home / "gh-config"),
                    "SSL_CERT_FILE": str(self.home / "corp-ca.pem"), "SSL_CERT_DIR": str(self.home / "corp-certs")}
        self.env.update(required)
        self.change_github(lambda db: db.update(auth=None, required_login_env=required))
        lines = self.install(code=1)
        command = self.home / ".local/state/task-hub/gh-login.command"
        self.assertEqual(command.stat().st_mode & 0o777, 0o700, "a proxy can contain credentials")
        self.assertNotIn(required["https_proxy"], "\n".join(lines))
        self.finish_github_login()
        self.assertFalse(command.exists(), "login must remove the environment-bearing command when it starts")

    def test_terminal_kiro_login_keeps_network_environment_and_removes_its_command(self):
        self.use_python3()
        required = {"https_proxy": "http://user:p'ass@proxy.example:8080",
                    "SSL_CERT_FILE": str(self.home / "corp-ca.pem")}
        self.env.update(required)
        self.kiro_logged_in.unlink()
        self.script("kiro-cli", f'#!{sys.executable}\nimport os, sys\nfrom pathlib import Path\n'
                               f'marker = Path({str(self.kiro_logged_in)!r})\n'
                               'if sys.argv[1] == "--version": print("kiro-cli fake")\n'
                               'elif sys.argv[1] == "whoami": sys.exit(0 if marker.exists() else 1)\n'
                               'elif sys.argv[1] == "login":\n'
                               f'    if any(os.environ.get(k) != v for k, v in {required!r}.items()): sys.exit(1)\n'
                               '    marker.touch()\n'
                               'else: sys.exit(2)\n')
        self.install(code=1)
        command = self.home / ".local/state/task-hub/kiro-login.command"
        self.assertEqual(command.stat().st_mode & 0o777, 0o700)
        r = subprocess.run(["sh", str(command)], env={k: self.env[k] for k in ("HOME", "PATH")},
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.kiro_logged_in.exists(), "kiro's Terminal login needs the same network settings")
        self.assertFalse(command.exists())

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
        self.assertEqual(lines[-2], "5. kiro-cli のログイン: 止まりました。kiro-cli にログインしていません。"
                                    "開いたターミナルで、ログインの方法を選んでブラウザで承認してください")
        command = self.home / ".local/state/task-hub/kiro-login.command"
        self.assertEqual(self.opened.read_text(), f"{command}\n")
        self.assertIn(f"'{self.home}/.local/bin/kiro-cli' 'login'", command.read_text())
        self.assertEqual(self.github()["projects"], [], "later stages do not run")
        self.kiro_logged_in.touch()
        lines = self.install()
        self.assertIn("5. kiro-cli のログイン: 済み", lines)
        self.assertFalse(command.exists())

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


    # --- kiro-cli, Kiro, launchd ---

    def test_links_a_kiro_cli_app_that_is_there(self):
        self.use_python3()
        (self.fakebin / "kiro-cli").unlink()
        for where in (self.applications, self.home / "Applications"):
            with self.subTest(str(where)):
                cli = where / "Kiro CLI.app/Contents/MacOS/kiro-cli"
                cli.parent.mkdir(parents=True)
                cli.write_text(self.fake_kiro_cli("in an app"))
                cli.chmod(0o755)
                lines = self.install()
                self.assertIn(f"4. kiro-cli: リンクしました(~/.local/bin/kiro-cli → {cli})".replace(str(self.home), "~"),
                              lines)
                self.assertEqual(os.readlink(self.home / ".local/bin/kiro-cli"), str(cli))
                self.assertNotIn("kiro-cli-app", self.manifest()["installed"], "the app was there: not ours")
                self.assertFalse(self.hdiutil_calls.exists())
                shutil.rmtree(where / "Kiro CLI.app")  # the link breaks: the next one is found

    def test_installs_kiro_cli_from_its_dmg_when_there_is_none(self):
        self.use_python3()
        (self.fakebin / "kiro-cli").unlink()
        lines = self.install()
        app = self.home / "Applications/Kiro CLI.app"
        self.assertIn("4. kiro-cli: Kiro CLI を取っています(公式の手順ではありません: 公式のスクリプトは管理者権限の要る "
                      "/Applications に入れるため)…", lines)
        self.assertIn("4. kiro-cli: 入れました(~/Applications/Kiro CLI.app、~/.local/bin/kiro-cli。公式の手順ではありません)",
                      lines)
        self.assertIn(f"/kiro/stable/{KIRO_CLI_VERSION}/Kiro%20CLI.dmg", self.downloads())
        attach, detach = self.hdiutil_calls.read_text().splitlines()
        self.assertTrue(attach.startswith("attach -readonly -nobrowse -noautoopen -mountpoint "), attach)
        self.assertEqual(detach.split()[:2], ["detach", "-quiet"])
        # the app, and who signed kiro-cli (not the ad-hoc signature of Slack triage's program, stage 11)
        self.assertEqual(len([c for c in self.codesign_calls.read_text().splitlines() if "--sign -" not in c]), 2)
        self.assertIn('certificate leaf[subject.OU] = "94KV3E626L"', self.codesign_calls.read_text())
        self.assertEqual(os.readlink(self.home / ".local/bin/kiro-cli"), str(app / "Contents/MacOS/kiro-cli"))
        out = subprocess.run([str(self.home / ".local/bin/kiro-cli"), "--version"], capture_output=True, text=True)
        self.assertIn("from the DMG", out.stdout)
        self.assertFalse((self.home / "Applications/.Kiro CLI.app.tmp").exists())
        self.assertEqual(self.manifest()["installed"]["kiro-cli-app"], str(app))
        self.assertEqual(self.manifest()["installed"]["kiro-cli"], str(self.home / ".local/bin/kiro-cli"))
        self.assertIn("5. kiro-cli のログイン: 済み", lines)
        # again: nothing downloaded
        self.server.log[:] = []
        lines = self.install()
        self.assertIn("4. kiro-cli: 済み(~/.local/bin/kiro-cli)", lines)
        self.assertEqual(self.downloads(), [])

    def test_stops_when_the_kiro_cli_dmg_cannot_be_trusted_or_opened(self):
        self.use_python3()
        (self.fakebin / "kiro-cli").unlink()
        for case, why in (("checksum", "Kiro CLI の DMG のチェックサムが合いません"),
                          ("signature", "Kiro CLI の署名を確かめられませんでした"),
                          ("mount", "Kiro CLI の DMG を開けませんでした")):
            with self.subTest(case):
                self.publish_kiro_cli(sha=sha256(b"tampered") if case == "checksum" else None)
                for f in ("codesign-fails", "hdiutil-fails"):
                    (self.root / f).unlink(missing_ok=True)
                if case == "signature":
                    (self.root / "codesign-fails").touch()
                if case == "mount":
                    (self.root / "hdiutil-fails").touch()
                lines = self.install(code=1)
                self.assertTrue(lines[-2].startswith(f"4. kiro-cli: 止まりました。{why}"), lines)
                self.assertFalse((self.home / "Applications/Kiro CLI.app").exists())
                self.assertFalse(os.path.lexists(self.home / ".local/bin/kiro-cli"))
                self.assertFalse((self.home / ".local/lib/task-hub").exists(), "later stages do not run")
                if case == "signature":  # attached, then detached on the way out
                    self.assertEqual(self.hdiutil_calls.read_text().splitlines()[-1].split()[:2], ["detach", "-quiet"])
                if case == "mount":
                    self.assertIn("情シスに、Kiro CLI を /Applications に入れてもらってから", lines[-1])

    def test_links_skills_and_steering_and_copies_hooks_and_workflows(self):
        self.use_python3()
        kiro, lib = self.home / ".kiro", self.home / ".local/lib/task-hub"
        # a link from the manual steps in docs/kiro-ide.md, which Kiro does not read: becomes a copy
        (kiro / "hooks").mkdir(parents=True)
        (kiro / "hooks/task-hub-events.json").symlink_to(lib / "kiro/hooks/task-hub-events.json")
        lines = self.install()
        line = next(line for line in lines if line.startswith("9. "))
        self.assertIn("~/.kiro/skills/task(リンク)", line)
        self.assertIn("~/.kiro/hooks/task-hub-events.json(コピーし直し)", line)
        self.assertIn("~/.kiro/workflows/task-hub-events.workflow.json(コピー)", line)
        for src, dst in KIRO_LINKS:
            self.assertTrue((kiro / dst).is_symlink(), dst)
            self.assertEqual(os.readlink(kiro / dst), str(lib / src))
        for src, dst in KIRO_COPIES:
            self.assertFalse((kiro / dst).is_symlink(), dst)
            self.assertEqual((kiro / dst).read_bytes(), (REPO / src).read_bytes())
        self.assertEqual([p.name for p in (kiro / "hooks").iterdir()], ["task-hub-events.json"], "no temporary file left")

        # task-hub updated: the next run pulls it and copies the hook and the workflow again; the links stay
        before = self.snapshot()
        hook = (REPO / KIRO_COPIES[0][0]).read_text().replace("task-hub events", "task-hub events v2")
        self.change_origin(KIRO_COPIES[0][0], hook)
        workflow = (REPO / KIRO_COPIES[1][0]).read_text().replace('"pollIntervalSec": 60', '"pollIntervalSec": 30')
        self.change_origin(KIRO_COPIES[1][0], workflow)
        lines = self.install()
        line = next(line for line in lines if line.startswith("9. "))
        self.assertEqual(line, "9. Kiro との連携: 入れました(~/.kiro/hooks/task-hub-events.json(コピーし直し)、"
                               "~/.kiro/workflows/task-hub-events.workflow.json(コピーし直し)。Kiro を再起動すると読み込まれます)")
        self.assertEqual((kiro / KIRO_COPIES[0][1]).read_text(), hook)
        self.assertEqual((kiro / KIRO_COPIES[1][1]).read_text(), workflow)
        after = self.snapshot()
        self.assertEqual({k: v for k, v in after.items() if ".kiro/skills" in k or ".kiro/steering" in k},
                         {k: v for k, v in before.items() if ".kiro/skills" in k or ".kiro/steering" in k})

    def test_keeps_a_link_to_another_checkout(self):
        self.use_python3()
        mine = self.root / "my-task-hub/skills/task"
        mine.mkdir(parents=True)
        (self.home / ".kiro/skills").mkdir(parents=True)
        (self.home / ".kiro/skills/task").symlink_to(mine)
        lines = self.install()
        line = next(line for line in lines if line.startswith("9. "))
        self.assertIn("~/.kiro/skills/task は別のものを指しているので、そのままにしました", line)
        self.assertEqual(os.readlink(self.home / ".kiro/skills/task"), str(mine))
        self.assertNotIn("kiro-skill-task", self.manifest()["installed"])
        self.assertTrue((self.home / ".kiro/skills/chief").is_symlink())

    def test_turns_on_workflows_in_kiro_settings_and_keeps_the_rest(self):
        self.use_python3()
        settings = self.home / KIRO_SETTINGS
        settings.parent.mkdir(parents=True)
        mine = ('{\n  "workbench.colorTheme": "Kiro Dark",\n  "editor.fontSize": 13.5,\n  "files.exclude": {"**/.git": true},\n'
                '  "kiroAgent.workflows.enabled": false,\n  "telemetry.telemetryLevel": null,\n  "x.ja": "日本語"\n}\n')
        settings.write_text(mine)
        lines = self.install()
        backups = list(settings.parent.glob("settings.json.bak-*"))
        self.assertEqual([b.read_text() for b in backups], [mine])
        data = json.loads(settings.read_text())
        self.assertEqual(data, {**json.loads(mine), "kiroAgent.workflows.enabled": True})
        self.assertEqual(list(data), list(json.loads(mine)), "the order is kept")
        self.assertIn('\n  "workbench.colorTheme": "Kiro Dark",\n', settings.read_text(), "and the indent")
        self.assertIn('"x.ja": "日本語"', settings.read_text())
        line = next(line for line in lines if line.startswith("9. "))
        self.assertIn(f"~/{KIRO_SETTINGS}(Workflows を有効に。元の内容は ~/{KIRO_SETTINGS}.bak-", line)
        # already on: untouched
        before = settings.read_text()
        self.install()
        self.assertEqual(settings.read_text(), before)
        self.assertEqual(len(list(settings.parent.glob("settings.json.bak-*"))), 1)

    def test_does_not_rewrite_kiro_settings_with_comments(self):
        self.use_python3()
        settings = self.home / KIRO_SETTINGS
        settings.parent.mkdir(parents=True)
        for text in ('{\n  // my font\n  "editor.fontSize": 14,\n}\n',
                     '{\n  "editor.fontSize": 14,\n  // "kiroAgent.workflows.enabled": true\n}\n'):
            with self.subTest(text):
                settings.write_text(text)
                lines = self.install()
                self.assertEqual(settings.read_text(), text)
                self.assertEqual(list(settings.parent.glob("settings.json.bak-*")), [])
                line = next(line for line in lines if line.startswith("9. "))
                self.assertIn(f"~/{KIRO_SETTINGS} はコメントか末尾のカンマがあるので書き換えていません。"
                              "Kiro のコマンドパレットで「Enable Workflows」を実行してください", line)
                self.assertEqual(lines[-1], "次にすること: Kiro のコマンドパレット(⌘⇧P)で「Enable Workflows」を実行し、"
                                            "Kiro を再起動してください")
                self.assertNotIn("kiro-settings", self.manifest()["installed"])
        # on already, in a file with comments: nothing to do
        settings.write_text('{\n  // mine\n  "kiroAgent.workflows.enabled": true,\n}\n')
        lines = self.install()
        self.assertEqual(lines[-1], "次にすること: Kiro の新しいチャットで /task を試してください")

    def test_launchd_only_with_the_option_and_started_only_when_asked(self):
        self.use_python3()
        plist = self.home / PLIST
        lines = self.install(args=["--with-launchd"])
        self.assertTrue(plist.is_file())
        self.assertEqual(subprocess.run(["plutil", "-lint", str(plist)], capture_output=True).returncode, 0)
        p = json.loads(subprocess.run(["plutil", "-convert", "json", "-o", "-", str(plist)], capture_output=True,
                                      text=True, check=True).stdout)
        local = self.home / ".local"
        self.assertEqual(p["Label"], "com.task-hub.watch")
        self.assertEqual(p["ProgramArguments"], [str(local / "bin/task"), "watch"], "no key in the keychain: no key")
        self.assertEqual(p["EnvironmentVariables"], {
            "PATH": f"{local}/bin:{self.fakebin}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.home)})
        self.assertEqual(p["StandardErrorPath"], str(local / "state/task-hub/watch.err.log"))
        self.assertTrue(p["RunAtLoad"] and p["KeepAlive"])
        self.assertIn("10. 常駐: 置きました(~/Library/LaunchAgents/com.task-hub.watch.plist、まだ始めていません。"
                      "KIRO_API_KEY は使いません(", "\n".join(lines))
        self.assertEqual(lines[-1], "次にすること: 常駐を始めてよければ、sh kiro/install.sh --start-launchd を実行してください"
                                    "(ログインしている間 task watch が動き、Ready のカードを始めます)")
        self.assertEqual(set(self.launchctl_calls.read_text().splitlines()), {f"print gui/{os.getuid()}/com.task-hub.watch"},
                         "not started before the user said yes (the diagnosis only looks too)")
        self.assertIn("× 10. 常駐: ~/Library/LaunchAgents/com.task-hub.watch.plist はありますが、動いていません", lines)
        self.assertEqual(self.manifest()["installed"]["launchd"], str(plist))

        # the user said yes
        lines = self.install(args=["--start-launchd"])
        self.assertIn(f"bootstrap gui/{os.getuid()} {plist}", self.launchctl_calls.read_text().splitlines())
        self.assertTrue(any(line.startswith("10. 常駐: 始めました(") for line in lines), lines)
        lines = self.install(args=["--with-launchd"])
        self.assertTrue(any(line.startswith("10. 常駐: 済み(~/Library/LaunchAgents/com.task-hub.watch.plist、動いています")
                            for line in lines), lines)
        self.assertEqual(sum(c.startswith("bootstrap") for c in self.launchctl_calls.read_text().splitlines()), 1)

        # a key in the keychain: read when task watch starts, never written in the plist; reloaded when asked
        self.api_key.touch()
        lines = self.install(args=["--with-launchd"])
        self.assertIn("常駐に変えた設定を読み込ませてよければ", lines[-1])
        p = json.loads(subprocess.run(["plutil", "-convert", "json", "-o", "-", str(plist)], capture_output=True,
                                      text=True, check=True).stdout)
        self.assertEqual(p["ProgramArguments"][:2], ["/bin/sh", "-c"])
        self.assertIn("KIRO_API_KEY=$(/usr/bin/security find-generic-password -s task-hub-kiro-api-key -w) || ",
                      p["ProgramArguments"][2])
        self.assertIn(f"exec '{local}/bin/task' watch", p["ProgramArguments"][2])
        self.assertNotIn("KIRO_API_KEY", p["EnvironmentVariables"])
        self.install(args=["--start-launchd"])
        calls = [c for c in self.launchctl_calls.read_text().splitlines() if not c.startswith("print ")]
        self.assertEqual(calls[-2:], [f"bootout gui/{os.getuid()}/com.task-hub.watch", f"bootstrap gui/{os.getuid()} {plist}"])
        # without the option, again: left as it is
        before = plist.read_text()
        changes = lambda: [c for c in self.launchctl_calls.read_text().splitlines() if not c.startswith("print ")]
        n = len(changes())
        lines = self.install()
        self.assertEqual(plist.read_text(), before)
        self.assertEqual(len(changes()), n)
        self.assertIn("○ 10. 常駐: ~/Library/LaunchAgents/com.task-hub.watch.plist、動いています", lines)

    def test_does_not_replace_a_plist_of_the_users_own(self):
        self.use_python3()
        plist = self.home / PLIST
        plist.parent.mkdir(parents=True)
        plist.write_text("<plist>mine</plist>\n")
        lines = self.install(code=1, args=["--with-launchd"])
        self.assertTrue(lines[-2].startswith("10. 常駐: 止まりました。~/Library/LaunchAgents/com.task-hub.watch.plist が既に"
                                             "あります"), lines)
        self.assertEqual(plist.read_text(), "<plist>mine</plist>\n")
        self.assertFalse(self.launchctl_calls.exists())
        self.install(code=1, args=["--nope"])


    # --- the diagnosis and the uninstaller ---

    def run_script(self, script, code, args=()):
        r = subprocess.run(["sh", str(script), *args], env=self.env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        self.assertEqual(r.stderr, "")
        lines = r.stdout.strip().splitlines()
        self.assertTrue(lines[-1].startswith("次にすること: "), lines)
        self.assertEqual(sum(line.startswith("次にすること") for line in lines), 1, lines)
        return lines

    def doctor(self, code):
        return self.run_script(DOCTOR, code)

    def uninstall(self, code=0, yes=False):
        return self.run_script(UNINSTALL, code, ["--yes"] if yes else [])

    def marks(self, lines):
        """{stage: "○" or "×"} of the diagnosis's list"""
        return {line[2:].split(":")[0]: line[0] for line in lines if line[:2] in ("○ ", "× ")}

    STAGE_NAMES = ["1. 前提の確認", "2. Python", "3. gh", "4. kiro-cli", "5. GitHub のログイン", "5. kiro-cli のログイン",
                   "6. task-hub 本体", "7. ボード", "8. 設定", "9. Kiro との連携", "10. 常駐", "11. Slackトリアージ"]

    def test_doctor_on_a_mac_with_nothing_installed(self):
        (self.fakebin / "kiro-cli").unlink()
        self.change_github(lambda db: db.update(auth=None))
        lines = self.doctor(1)
        self.assertEqual(lines[0], "task-hub の診断です(何も変えません)")
        marks = self.marks(lines)
        self.assertEqual(list(marks), self.STAGE_NAMES)
        self.assertEqual(marks, {**{n: "×" for n in self.STAGE_NAMES}, "1. 前提の確認": "○", "10. 常駐": "○"})
        self.assertIn("○ 10. 常駐: 使っていません(任意。使うなら sh kiro/install.sh --with-launchd)", lines)
        self.assertIn("× 3. gh: gh がありません", lines)
        self.assertIn("× 9. Kiro との連携: ~/.kiro/skills/task、~/.kiro/skills/chief、~/.kiro/steering/task-hub.md、"
                      "~/.kiro/hooks/task-hub-events.json、~/.kiro/workflows/task-hub-events.workflow.json がありません", lines)
        # each × has its next step under it
        for i, line in enumerate(lines):
            if line.startswith("× "):
                self.assertTrue(lines[i + 1].startswith("    → "), lines[i:i + 2])
        self.assertEqual(lines[-2], "足りないものが 10 つあります。")
        self.assertEqual(lines[-1], "次にすること: sh kiro/install.sh を実行してください(Kiro のチャットなら「セットアップして」)")
        self.assertEqual(self.snapshot(), {}, "it changed nothing")
        # no git: the first thing to do is 情シス's
        shutil.rmtree(self.dev)
        lines = self.doctor(1)
        self.assertTrue(lines[1].startswith("× 1. 前提の確認: git がありません"), lines)
        self.assertIn("情シスに Command Line Tools を入れてもらってください", lines[-1])

    def test_doctor_after_a_full_install_lists_everything_there_and_changes_nothing(self):
        lines = self.install()
        # the installer's own run of it: the list, before its one next step
        self.assertIn("診断:", lines)
        at = lines.index("診断:")
        self.assertEqual(list(self.marks(lines[at:])), self.STAGE_NAMES)
        self.assertEqual(set(self.marks(lines[at:]).values()), {"○"}, lines)
        before = self.snapshot()
        self.change_github(lambda db: db["calls"].clear())
        lines = self.doctor(0)
        self.assertEqual(set(self.marks(lines).values()), {"○"}, lines)
        self.assertIn("○ 7. ボード: https://github.com/users/alice/projects/1、alice/tasks", lines)
        self.assertIn("○ 9. Kiro との連携: スキル、steering、フック、ワークフロー、Workflows は有効", lines)
        self.assertEqual(lines[-2:], ["すべて揃っています。", "次にすること: Kiro の新しいチャットで /task を試してください"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.writes(), [])

    def test_doctor_names_what_broke_and_what_to_do(self):
        self.use_python3()
        self.install()
        (self.home / ".kiro/hooks/task-hub-events.json").write_text("{}\n")  # an old copy
        self.kiro_logged_in.unlink()
        def item_closed_off(db):
            for w in db["projects"][0]["workflows"]:
                if w["name"] == "Item closed":
                    w["enabled"] = False
        self.change_github(item_closed_off)
        lines = self.doctor(1)
        marks = self.marks(lines)
        self.assertEqual([n for n, m in marks.items() if m == "×"], ["5. kiro-cli のログイン", "7. ボード", "9. Kiro との連携"])
        i = lines.index("× 7. ボード: https://github.com/users/alice/projects/1 のワークフローが task-hub に合っていません")
        self.assertEqual(lines[i + 1], "    → https://github.com/users/alice/projects/1/workflows を開き、「Item closed」を"
                                       "有効にしてください")
        self.assertIn("× 9. Kiro との連携: ~/.kiro/hooks/task-hub-events.json が task-hub の今の版と違います", lines)
        self.assertEqual(lines[-1], "次にすること: sh kiro/install.sh を実行し、開いたターミナルでログインしてください")
        # JSONC settings.json without Workflows: the command palette
        (self.home / ".kiro/hooks/task-hub-events.json").write_bytes((REPO / KIRO_COPIES[0][0]).read_bytes())
        (self.home / KIRO_SETTINGS).write_text('{\n  // mine\n  "editor.fontSize": 14,\n}\n')
        lines = self.doctor(1)
        i = lines.index("× 9. Kiro との連携: Workflows が有効になっていません")
        self.assertIn("「Enable Workflows」", lines[i + 1])

    def by_hand(self):
        """What docs/setup.md's manual steps leave (the board and config.ini as the installer makes them):
        ~/.local/bin/task a link to the clone's bin/task, kiro-cli only on PATH, no manifest, ~/.local/bin on PATH
        from the shell, git logged in with another helper (a git whose ls-remote reaches the test's GitHub while the
        file git-reaches exists), and a hook copied from an older version that differs only in its description."""
        self.use_python3()
        self.install()
        local = self.home / ".local"
        (local / "bin/task").unlink()
        (local / "bin/task").symlink_to(local / "lib/task-hub/bin/task")
        (local / "bin/kiro-cli").unlink()
        (local / "state/task-hub/install-manifest.json").unlink()
        (self.home / ".zprofile").unlink()
        self.env["PATH"] = f"{local}/bin:{self.env['PATH']}"
        (self.home / ".gitconfig").write_text("[credential]\n\thelper = osxkeychain\n")
        self.git_reaches = self.root / "git-reaches"
        self.git_reaches.touch()
        git = self.dev / "usr/bin/git"
        git.unlink()
        git.write_text(f'#!/bin/sh\ncase " $* " in\n  *" ls-remote "*" {self.server.url}/"*)\n'
                       f'    [ -e "{self.git_reaches}" ] && exit 0\n'
                       '    echo "fatal: Authentication failed" >&2; exit 128 ;;\nesac\n'
                       f'exec "{shutil.which("git")}" "$@"\n')
        git.chmod(0o755)
        hook = self.home / ".kiro" / KIRO_COPIES[0][1]
        data = json.loads(hook.read_text())
        data["hooks"][0]["description"] = "an older description"
        hook.write_text(json.dumps(data, indent=2))
        self.by_hand_hook = json.loads(json.dumps(data))
        return hook, data

    def test_doctor_on_a_manual_install_that_works_says_so_with_notes(self):
        self.by_hand()
        lines = self.doctor(0)
        self.assertEqual(set(self.marks(lines).values()), {"○"}, lines)
        def at(line):
            i = lines.index(line)
            return lines[i:i + 3]
        self.assertEqual(at(f"○ 4. kiro-cli: {self.fakebin}/kiro-cli")[1],
                         "    (手で入れた構成です。~/.local/bin/kiro-cli はなく、PATH にあるものを使います)")
        self.assertEqual(at("○ 5. GitHub のログイン: alice")[1],
                         "    (手で入れた構成です。git は gh 以外のログインで alice/tasks に届きます)")
        self.assertEqual(at(f"○ 6. task-hub 本体: ~/.local/lib/task-hub(main {self.short()})、~/.local/bin/task"), [
            f"○ 6. task-hub 本体: ~/.local/lib/task-hub(main {self.short()})、~/.local/bin/task",
            "    (手で入れた構成です。~/.local/bin/task は clone の bin/task へのリンクで、インストーラの wrapper ではありません)",
            "    (ブランチ main の上の clone です。インストーラはタグに切り替えず、pull だけします)"])
        self.assertIn("○ 7. ボード: https://github.com/users/alice/projects/1、alice/tasks", lines)
        self.assertEqual(at("○ 9. Kiro との連携: スキル、steering、フック、ワークフロー、Workflows は有効")[1],
                         "    (~/.kiro/hooks/task-hub-events.json は task-hub の今の版と説明(description)か名前だけが違います。"
                         "動作は同じです)")
        self.assertEqual(lines[-2:], ["すべて揃っています。", "次にすること: Kiro の新しいチャットで /task を試してください"])

    def test_doctor_on_a_manual_install_still_marks_what_is_broken(self):
        hook, data = self.by_hand()
        with self.subTest("no kiro-cli"):
            (self.fakebin / "kiro-cli").rename(self.root / "kiro-cli")
            marks = self.marks(self.doctor(1))
            self.assertEqual([n for n, m in marks.items() if m == "×"], ["4. kiro-cli", "5. kiro-cli のログイン"])
            (self.root / "kiro-cli").rename(self.fakebin / "kiro-cli")
        with self.subTest("git does not reach GitHub"):
            self.git_reaches.unlink()
            lines = self.doctor(1)
            marks = self.marks(lines)
            self.assertEqual([n for n, m in marks.items() if m == "×"], ["5. GitHub のログイン"])
            self.assertIn("× 5. GitHub のログイン: alice。git が gh のログインを使っておらず、alice/tasks に届きません", lines)
            self.assertEqual(marks["7. ボード"], "○", "the board needs gh only: it is still checked")
            self.git_reaches.touch()
        with self.subTest("a Python older than 3.10"):
            python3 = self.fakebin / "python3"
            python3.unlink()
            python3.write_text(f'#!/bin/sh\ncase "$*" in *version_info*) exit 1 ;; esac\nexec "{sys.executable}" "$@"\n')
            python3.chmod(0o755)
            lines = self.doctor(1)
            self.assertIn(f"× 6. task-hub 本体: ~/.local/bin/task の Python({python3})が 3.10 以上ではありません", lines)
            python3.unlink()
            python3.symlink_to(sys.executable)
        with self.subTest("the hook runs another command"):
            data["hooks"][0]["action"]["command"] = "$HOME/elsewhere/task-events-since"
            hook.write_text(json.dumps(data, indent=2))
            lines = self.doctor(1)
            self.assertEqual([n for n, m in self.marks(lines).items() if m == "×"], ["9. Kiro との連携"])
            self.assertIn("× 9. Kiro との連携: ~/.kiro/hooks/task-hub-events.json が task-hub の今の版と違います", lines)
        hook.write_text(json.dumps(self.by_hand_hook, indent=2))
        self.doctor(0)  # each was put back

    def test_slack_triage_key_is_set_up_for_everyone_and_off_keeps_it_off(self):
        lines = self.install()
        line = next(x for x in lines if x.startswith("11. Slackトリアージ: "))
        self.assertTrue(line.startswith("11. Slackトリアージ: 入れました("
                                        "~/.local/lib/task-hub/slack-triage/bin/slack-triage-hotkey(ビルド)、"
                                        "~/.local/bin/slack-triage、~/Library/LaunchAgents/com.task-hub.slack-triage.plist、"
                                        "Slack のスレッドをコピーして ⌃⌥S で使えます。初めて押したときに"), line)
        # built from its source by slack-triage/hotkey/build.sh, for both CPUs
        self.assertEqual([c.split()[2] for c in self.swiftc_calls.read_text().splitlines()],
                         ["arm64-apple-macos12", "x86_64-apple-macos12"])
        plist = self.home / ST_PLIST
        text = plist.read_text()
        self.assertIn("task-hub: made by kiro/install.sh", text)
        self.assertIn(f"<string>{self.home}/.local/lib/task-hub/slack-triage/bin/slack-triage-hotkey</string>", text)
        self.assertIn(f"<string>{self.home}/.config/task-hub/slack-triage.json</string>", text)
        self.assertIn(f"<string>{self.home}/.local/bin/slack-triage</string>", text)
        self.assertEqual([c for c in self.st_calls.read_text().splitlines() if not c.startswith("print ")],
                         [f"bootstrap gui/{os.getuid()} {plist}"])
        out = subprocess.run([str(self.home / ".local/bin/slack-triage"), "--help"], env=self.env,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("slack-triage off", out.stdout)
        self.assertIn("○ 11. Slackトリアージ: Slack のスレッドをコピーして ⌃⌥S で使えます", self.doctor(0))

        # slack-triage off: the setting, and the agent booted out. The installer leaves it off
        config = self.home / ".config/task-hub/slack-triage.json"
        config.write_text(json.dumps({"enabled": False, "hotkey_key": "t"}))
        self.st_loaded.unlink()
        lines = self.install()
        self.assertIn("11. Slackトリアージ: 済み(止めています(slack-triage off)。使うときは slack-triage on)", lines)
        self.assertEqual(sum(c.startswith("bootstrap") for c in self.st_calls.read_text().splitlines()), 1)
        self.assertIn("○ 11. Slackトリアージ: 止めています(slack-triage off)。使うときは slack-triage on", self.doctor(0))

        # on again, with the key it was changed to: the installer starts it
        config.write_text(json.dumps({"enabled": True, "hotkey_key": "t", "owner_name": "山田"}))
        lines = self.install()
        self.assertIn("11. Slackトリアージ: 入れました(Slack のスレッドをコピーして ⌃⌥T で使えます。"
                      "止めるときは slack-triage off)", lines)
        self.assertTrue(self.st_loaded.exists())

        # the key not held: × with what to do
        self.st_status.write_text("error -9868\n")
        lines = self.doctor(1)
        i = lines.index("× 11. Slackトリアージ: 起動キー ⌃⌥T を登録できていません")
        self.assertEqual(lines[i + 1], "    → slack-triage key t のように別のキーにしてください")

    def test_slack_triage_program_is_built_again_only_when_its_source_changed(self):
        self.install()
        hotkey = self.home / ".local/lib/task-hub/slack-triage/bin/slack-triage-hotkey"
        built, swiftc = hotkey.read_text(), (self.fakebin / "swiftc").read_text()
        (self.fakebin / "swiftc").unlink()  # not needed while the source is the same
        lines = self.install()
        self.assertIn("11. Slackトリアージ: 済み(Slack のスレッドをコピーして ⌃⌥S で使えます)", lines)
        self.assertEqual(len(self.swiftc_calls.read_text().splitlines()), 2)

        # a new version of task-hub changed it: built again, and started again with the new program
        self.change_origin("slack-triage/hotkey/main.swift",
                           (REPO / "slack-triage/hotkey/main.swift").read_text() + "// changed\n")
        lines = self.install(1)
        self.assertEqual(lines[-2:], [
            "11. Slackトリアージ: 止まりました。Slackトリアージのキー受付プログラムを作る swiftc がありません"
            "(Xcode の Command Line Tools が古いか、足りません)",
            "次にすること: 情シスに Xcode の Command Line Tools を入れ直してもらい(ターミナルで xcode-select --install。"
            "管理者権限が要る場合があります)、もう一度実行してください"])
        self.assertEqual(hotkey.read_text(), built, "the program that works is kept")
        self.script("swiftc", swiftc)
        line = next(x for x in self.install() if x.startswith("11. Slackトリアージ: "))
        self.assertTrue(line.startswith("11. Slackトリアージ: 入れました(~/.local/lib/task-hub/slack-triage/bin/"
                                        "slack-triage-hotkey(ビルド)、Slack のスレッドをコピーして ⌃⌥S で使えます。"), line)
        self.assertIn("// changed", hotkey.read_text())
        self.assertEqual([c.split()[0] for c in self.st_calls.read_text().splitlines() if not c.startswith("print ")],
                         ["bootstrap", "bootout", "bootstrap"])

    def test_uninstall_removes_only_what_the_manifest_lists(self):
        mine = {".zprofile": "export EDITOR=vi\n", ".local/bin/mytool": "#!/bin/sh\n", ".kiro/skills/other/SKILL.md": "x\n",
                ".local/state/task-hub/events.jsonl": "{}\n"}
        for rel, text in mine.items():
            (self.home / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.home / rel).write_text(text)
        self.install(args=["--start-launchd"])  # everything, uv and its Python too
        m = self.manifest()["installed"]
        self.assertTrue({"uv", "uv-python", "gh", "launchd", "config", "kiro-settings"} <= set(m), m)
        self.assertIn(ZPROFILE_LINE, (self.home / ".zprofile").read_text())
        github = {k: v for k, v in self.github().items() if k != "calls"}
        self.change_github(lambda db: db["calls"].clear())

        # without --yes: the list, nothing removed
        before = self.snapshot()
        lines = self.uninstall()
        self.assertEqual(self.snapshot(), before)
        self.assertIn("- ~/.local/lib/task-hub(task-hub の clone)", lines)
        self.assertIn("- uv で入れた Python 3.12", lines)
        self.assertIn("- ~/.kiro/skills/task(リンク)", lines)
        self.assertIn("- GitHub のボード(alice/tasks と Project alice/1)。要らなければ、GitHub の画面で消します:", lines)
        self.assertIn("    Project: https://github.com/users/alice/projects/1/settings の一番下「Delete this project」", lines)
        self.assertEqual(lines[-1], "次にすること: 消してよければ、sh kiro/uninstall.sh --yes を実行してください")

        lines = self.uninstall(yes=True)
        self.assertFalse([line for line in lines if line.startswith("消せませんでした")], lines)
        self.assertEqual(lines[-1], "次にすること: Kiro を再起動してください(/task と /chief、フック、ワークフローが外れます)")
        left = self.snapshot()
        for rel, text in mine.items():  # the user's own files, as they were
            self.assertEqual(left.pop(rel), text.encode(), rel)
        self.assertTrue(left.pop(KIRO_SETTINGS), "settings.json is the user's: kept")
        left.pop(".gitconfig")  # gh's login for git: kept with the login
        for rel in list(left):
            if rel.startswith(".local/state/task-hub/"):  # task-hub's data (the watch logs)
                left.pop(rel)
        self.assertEqual(left, {}, "nothing else of the installer's is left")
        self.assertFalse((self.home / ".local/state/task-hub/install-manifest.json").exists())
        self.assertFalse(self.launchd_loaded.exists(), "task watch was stopped")
        self.assertIn(f"bootout gui/{os.getuid()}/com.task-hub.watch", self.launchctl_calls.read_text().splitlines())
        self.assertFalse(self.st_loaded.exists(), "the key of Slack triage was stopped")
        self.assertIn(f"bootout gui/{os.getuid()}/com.task-hub.slack-triage", self.st_calls.read_text().splitlines())
        self.assertIn("python uninstall 3.12", self.uv_calls.read_text())
        self.assertEqual({k: v for k, v in self.github().items() if k != "calls"}, github, "the board on GitHub stays")
        self.assertEqual(self.writes(), [])
        # again: nothing to do
        lines = self.uninstall()
        self.assertIn("がありません。このインストーラで入れたものはありません。", lines[0])

    def test_uninstall_keeps_what_is_no_longer_the_installers(self):
        self.use_python3()
        self.install()
        task = self.home / ".local/bin/task"
        task.write_text("#!/bin/sh\necho mine\n")  # replaced by the user since
        outside = self.root / "not-home-gh"
        outside.write_text("gh\n")
        manifest = self.home / ".local/state/task-hub/install-manifest.json"
        m = json.loads(manifest.read_text())
        m["installed"]["gh"] = str(outside)  # never anything outside HOME
        manifest.write_text(json.dumps(m))
        lines = self.uninstall(yes=True)
        self.assertNotIn("消しました: ~/.local/bin/task", lines)
        self.assertEqual(task.read_text(), "#!/bin/sh\necho mine\n")
        self.assertTrue(outside.exists())
        self.assertFalse((self.home / ".local/lib/task-hub").exists())
        self.assertFalse(os.path.lexists(self.home / ".kiro/skills/task"))

    def test_uninstall_keeps_repointed_kiro_link_and_replaced_hook(self):
        self.use_python3()
        self.install()
        link = self.home / ".kiro/skills/task"
        mine = self.home / "my-skills/task"
        mine.mkdir(parents=True)
        link.unlink()
        link.symlink_to(mine)
        hook = self.home / ".kiro/hooks/task-hub-events.json"
        custom = '{"hooks": [{"name": "my hook", "command": "echo mine"}]}\n'
        hook.write_text(custom)
        self.uninstall(yes=True)
        with self.subTest("repointed link"):
            self.assertTrue(link.is_symlink(), "uninstall must preserve a link the user repointed")
            self.assertEqual(os.readlink(link), str(mine))
        with self.subTest("replaced hook"):
            self.assertTrue(hook.exists(), "uninstall must preserve the user's replacement hook")
            self.assertEqual(hook.read_text(), custom)

    def test_uninstall_keeps_a_repointed_kiro_cli_link(self):
        self.use_python3()
        self.install()
        link = self.home / ".local/bin/kiro-cli"
        mine = self.home / "my-kiro-cli"
        mine.write_text("#!/bin/sh\necho mine\n")
        link.unlink()
        link.symlink_to(mine)
        self.uninstall(yes=True)
        self.assertTrue(link.is_symlink(), "uninstall must preserve a repointed kiro-cli link")
        self.assertEqual(os.readlink(link), str(mine))

    def test_install_does_not_adopt_a_matching_manual_skill_link(self):
        self.use_python3()
        link = self.home / ".kiro/skills/task"
        link.parent.mkdir(parents=True)
        source = self.home / ".local/lib/task-hub/skills/task"
        link.symlink_to(source)
        self.install()
        self.assertNotIn("kiro-skill-task", self.manifest()["installed"])
        self.uninstall(yes=True)
        self.assertTrue(link.is_symlink(), "a manual link remains the user's even when it matches the package")
        self.assertEqual(os.readlink(link), str(source))

    def test_uninstall_keeps_a_legacy_kiro_cli_link_with_no_recorded_target(self):
        self.use_python3()
        self.install()
        manifest = self.home / ".local/state/task-hub/install-manifest.json"
        data = self.manifest()
        data.pop("kiro-cli-target")
        manifest.write_text(json.dumps(data))
        link = self.home / ".local/bin/kiro-cli"
        target = os.readlink(link)
        self.uninstall(yes=True)
        self.assertTrue(link.is_symlink(), "legacy records cannot prove the current link is still owned")
        self.assertEqual(os.readlink(link), target)

    def test_install_keeps_an_existing_custom_hook(self):
        self.use_python3()
        hook = self.home / ".kiro/hooks/task-hub-events.json"
        hook.parent.mkdir(parents=True)
        custom = '{"hooks": [{"name": "my hook", "command": "echo mine"}]}\n'
        hook.write_text(custom)
        r = subprocess.run(["sh", str(INSTALL)], env=self.env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(hook.read_text(), custom, "install must not overwrite an unowned hook")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("次にすること:", r.stdout)

    def test_reinstall_keeps_a_modified_hook(self):
        self.use_python3()
        self.install()
        hook = self.home / ".kiro/hooks/task-hub-events.json"
        custom = '{"hooks": [{"name": "my hook", "command": "echo mine"}]}\n'
        hook.write_text(custom)
        r = subprocess.run(["sh", str(INSTALL)], env=self.env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(hook.read_text(), custom, "reinstall must not overwrite an edited hook")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("次にすること:", r.stdout)

    def test_legacy_owned_copy_updates_after_a_new_package_is_pulled(self):
        self.use_python3()
        self.install()
        manifest = self.home / ".local/state/task-hub/install-manifest.json"
        data = self.manifest()
        data.pop("sha256")  # the previous installer recorded only paths
        manifest.write_text(json.dumps(data))
        source = KIRO_COPIES[0][0]
        new_hook = (REPO / source).read_text().replace("task-hub events", "task-hub events v2")
        self.change_origin(source, new_hook)
        self.install()
        self.assertEqual((self.home / ".kiro" / KIRO_COPIES[0][1]).read_text(), new_hook)
        self.assertEqual(self.manifest()["sha256"]["kiro-hook"], hashlib.sha256(new_hook.encode()).hexdigest())

    def test_uninstall_cleans_owned_links_after_an_install_stops_on_a_custom_hook(self):
        self.use_python3()
        hook = self.home / ".kiro/hooks/task-hub-events.json"
        hook.parent.mkdir(parents=True)
        custom = '{"hooks": [{"name": "my hook", "command": "echo mine"}]}\n'
        hook.write_text(custom)
        self.install(code=1)
        link = self.home / ".kiro/skills/task"
        self.assertTrue(link.is_symlink())
        self.uninstall(yes=True)
        self.assertFalse(os.path.lexists(link), "created links must remain uninstallable after a later stage fails")
        self.assertEqual(hook.read_text(), custom)


class SteeringTest(unittest.TestCase):
    """The steering files have the front matter Kiro reads (https://kiro.dev/docs/steering/)."""

    def front_matter(self, path):
        lines = path.read_text().splitlines()
        self.assertEqual(lines[0], "---", path)
        end = lines.index("---", 1)
        fields = dict(line.split(": ", 1) for line in lines[1:end])
        self.assertIn(fields.get("inclusion"), ("always", "fileMatch", "manual", "auto"), path)
        if fields["inclusion"] == "auto":
            self.assertRegex(fields.get("name", ""), r"^[a-z0-9-]+$", path)
            self.assertTrue(fields.get("description"), path)
        if fields["inclusion"] == "fileMatch":
            self.assertTrue(fields.get("fileMatchPattern"), path)
        return fields

    def test_the_setup_steering_is_read_only_when_the_talk_is_about_setup(self):
        setup = REPO / ".kiro/steering/setup.md"
        fields = self.front_matter(setup)
        # always would put it in every chat in this repo; a worker of a task-hub task reads .kiro/steering too
        self.assertEqual(fields["inclusion"], "auto")
        for word in ("セットアップして", "続けて"):
            self.assertIn(word, fields["description"])
        text = setup.read_text()
        self.assertIn("sh kiro/install.sh", text)
        self.assertIn("worker", text)  # what a worker (Kiro CLI reads every steering file) is to do with it

    def test_the_global_steering(self):
        self.front_matter(REPO / "kiro/steering/task-hub.md")


if __name__ == "__main__":
    unittest.main()
