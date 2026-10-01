"""Black-box tests of kiro/install.sh: run it with `sh`, with HOME a temporary folder.

- GitHub Releases is a local HTTP server (TASK_INSTALL_GITHUB) with fake gh and uv archives and their checksums,
  so nothing is downloaded for real. releases/latest redirects to a tag, as on github.com.
- task-hub is cloned from a local bare repo (TASK_INSTALL_REPO), whose bin/task only prints its arguments.
- PATH has a fake bin folder first, then only the system folders (no Homebrew, pyenv, ...). The fakes:
  xcode-select (points to a folder whose usr/bin/git is the real git), scutil (no proxy), and per test python3 / gh.
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
import unittest
import zipfile
from pathlib import Path

INSTALL = Path(__file__).resolve().parent.parent / "kiro" / "install.sh"
GH_TAG, UV_TAG = "v2.0.0", "0.9.0"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
ZPROFILE_LINE = 'export PATH="$HOME/.local/bin:$PATH"'
FAKE_TASK = '#!/usr/bin/env python3\nimport sys\nprint("task", sys.executable, *sys.argv[1:])\n'
NO_PROXY_SCUTIL = "<dictionary> {\n  ExceptionsList : <array> {\n    0 : *.local\n  }\n}\n"


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
                    if k.lower() not in ("https_proxy", "http_proxy", "all_proxy", "no_proxy")}
        self.env.update(git_id, HOME=str(self.home), PATH=f"{self.fakebin}:{SYSTEM_PATH}",
                        TASK_INSTALL_GITHUB=self.server.url, TASK_INSTALL_REPO=f"file://{root}/origin.git")

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
            data = zip_bytes({f"{name}/bin/gh": f"#!/bin/sh\necho 'gh version {ver} (fake)'\n",
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

    def make_origin(self):
        src = self.root / "src"
        (src / "bin").mkdir(parents=True)
        (src / "bin/task").write_text(FAKE_TASK)
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
        return [line for line in lines if line[:2] in ("1.", "2.", "3.", "5.")]

    # --- tests ---

    def test_installs_everything_and_a_second_run_changes_nothing(self):
        lines = self.install()
        local = self.home / ".local"
        self.assertTrue(any(line.startswith("2. Python: 入れました") for line in lines), lines)
        self.assertTrue(any(line.startswith("3. gh: 入れました") for line in lines), lines)
        self.assertTrue(any(line.startswith("5. task-hub 本体: 入れました") for line in lines), lines)
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
                          "task-hub": str(local / "lib/task-hub"), "task": str(wrapper), "zprofile": ZPROFILE_LINE}})
        self.assertEqual([p for p in (self.home / ".local/state/task-hub").iterdir() if p.name.startswith("install.")],
                         [], "the work folder is removed")

        head = lambda: subprocess.run(["git", "-C", str(local / "lib/task-hub"), "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout
        before, head_before, self.server.log[:] = self.snapshot(), head(), []
        lines = self.install()
        stages = self.stage_lines(lines)
        self.assertEqual([line.split(":")[0] for line in stages],
                         ["1. 前提の確認", "2. Python", "3. gh", "5. task-hub 本体"])
        self.assertTrue(all(line.split(": ", 1)[1].startswith("済み") for line in stages), stages)
        self.assertIn("すべて済みです。変えたものはありません。", lines)
        self.assertEqual(self.downloads(), [])
        self.assertEqual(len(self.uv_calls.read_text().splitlines()), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(head(), head_before)

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
        self.assertEqual(sorted(m["installed"]), ["gh", "task", "task-hub", "zprofile"])  # not the Python: not ours

    def test_uses_a_gh_already_on_path(self):
        self.use_python3()
        self.script("gh", "#!/bin/sh\necho 'gh version 9.9.9'\n")
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


if __name__ == "__main__":
    unittest.main()
