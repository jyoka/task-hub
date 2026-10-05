"""slack-triage: Slackのスレッドを読んで、task-hub に登録するタスクを提案する（docs/slack-triage.md）。
  slack-triage            クリップボードのスレッドを整理して、タスクにするかを聞く（⌃⌥S で呼ばれる。初めてなら先に名前を聞く）
  slack-triage practice   練習用のスレッドで試す（登録はしない）
  slack-triage setup      名前と登録先リポジトリを設定し直す
  slack-triage key t      起動キーを ⌃⌥T にする（a〜z。修飾キーも変えるなら: key t ctrl,opt,cmd）
  slack-triage off        起動キーを止める（kiro/install.sh をもう一度実行しても止めたまま）
  slack-triage on         起動キーを再開する
  slack-triage check      動くための条件がそろっているか確かめる
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

from . import core, macui

HOME = os.path.expanduser("~")
LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # slack-triage/（.kiro/agents がある）
STATE = os.path.join(HOME, ".local", "state", "task-hub")
CONFIG = os.path.join(HOME, ".config", "task-hub", "slack-triage.json")
LOG = os.path.join(STATE, "slack-triage.log")
HOTKEY_STATUS = os.path.join(STATE, "slack-triage-hotkey.status")
LOCK = os.path.join(tempfile.gettempdir(), "slack-triage-%d.lock" % os.getuid())
AGENT_FILE = os.path.join(LIB, ".kiro", "agents", "slack-triage.json")
LAUNCHD_LABEL = os.environ.get("SLACK_TRIAGE_LABEL") or "com.task-hub.slack-triage"
PLIST = os.path.join(HOME, "Library", "LaunchAgents", LAUNCHD_LABEL + ".plist")
TASK_HUB_CONFIG = os.path.join(HOME, ".config", "task-hub", "config.ini")
DEFAULT_KEY, DEFAULT_MODS = "s", "ctrl,opt"
INSTALL = "sh kiro/install.sh を実行してください(Kiro のチャットなら「セットアップして」)"

# ⌃⌥S から起動すると PATH がほぼ空なので、よくある置き場所を足す
EXTRA_PATH = [
    os.path.join(HOME, ".local", "bin"),
    os.path.join(HOME, "Applications", "Kiro CLI.app", "Contents", "MacOS"),
    "/Applications/Kiro CLI.app/Contents/MacOS",
    "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
]


def _setup_env():
    parts = EXTRA_PATH + [p for p in os.environ.get("PATH", "").split(":") if p and p not in EXTRA_PATH]
    os.environ["PATH"] = ":".join(parts)
    os.environ.setdefault("LANG", "ja_JP.UTF-8")
    os.environ["LC_ALL"] = os.environ.get("LC_ALL") or "ja_JP.UTF-8"


def which(name):
    for d in os.environ.get("PATH", "").split(":"):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def kiro_bin():
    """kiro-cli の実体。~/.local/bin/kiro-cli（kiro/install.sh のリンク）のまま呼ぶと、kiro-cli は自分の部品
    （kiro-cli-chat）をリンクのある場所で探して「No such file or directory」で止まるので、リンク先を使う"""
    k = os.environ.get("KIRO_BIN") or which("kiro-cli")
    return os.path.realpath(k) if k else None


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), msg))
    except OSError:
        pass


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            c = json.load(f)
            return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG)


def key_label(key, mods):
    """ctrl,opt + s → ⌃⌥S"""
    ms = [m.strip() for m in (mods or "").split(",")]
    out = "".join(sym for names, sym in ((("ctrl", "control"), "⌃"), (("opt", "option", "alt"), "⌥"),
                                         (("shift",), "⇧"), (("cmd", "command"), "⌘")) if any(n in ms for n in names))
    return out + (key or "").upper()


def hotkey_label(cfg=None):
    cfg = load_config() if cfg is None else cfg
    return key_label(cfg.get("hotkey_key") or DEFAULT_KEY, cfg.get("hotkey_mods") or DEFAULT_MODS)


# ---- 外部コマンド（シェルを介さず引数の配列で渡す） ----

def ask_kiro(prompt):
    kiro = kiro_bin()
    if not kiro:
        raise RuntimeError("kiro-cli が見つかりません。" + INSTALL)
    try:
        p = subprocess.run([kiro, "chat", "--no-interactive", "--agent", "slack-triage", "--trust-tools=", prompt],
                           cwd=LIB, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=int(os.environ.get("SLACK_TRIAGE_KIRO_TIMEOUT", "240")), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Kiroの応答が時間内に返りませんでした。もう一度試してください")
    err = core.strip_ansi(p.stderr).lower()
    # slack-triage が読めないと、Kiroは全ツール付きの既定エージェントで動く。その結果は使わない
    if "no agent with name" in err or " is invalid" in err:
        raise RuntimeError("整理用の設定（slack-triage エージェント）を読み込めませんでした。" + INSTALL)
    if p.returncode != 0:
        log("kiro exit %d: %s" % (p.returncode, core.strip_ansi(p.stderr)[-1500:]))
        raise RuntimeError("Kiroが失敗しました。ログインが切れているかもしれません。\n"
                           "ターミナルで kiro-cli login を実行してから、もう一度試してください")
    return core.extract_json(p.stdout)


def run_task(task):
    tb = os.environ.get("TASK_BIN") or which("task")
    if not tb:
        raise RuntimeError("task コマンドが見つかりません。" + INSTALL)
    with tempfile.TemporaryDirectory(prefix="slack-task-") as d:
        goal_file = os.path.join(d, "goal.md")
        with open(goal_file, "w", encoding="utf-8") as f:
            f.write(task["goal"])
        args = [tb, "new", "--title", task["title"], "--repo", task["repo"], "--goal-file", goal_file]
        if task.get("research"):
            args.append("--research")
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        e = RuntimeError("task new が失敗しました")
        e.stderr = (p.stderr or p.stdout).strip()
        raise e
    log("registered: %s (%s)" % (task["title"], task["repo"]))
    return p.stdout


def read_clipboard():
    p = subprocess.run(["pbpaste"], capture_output=True, env=dict(os.environ, LANG="ja_JP.UTF-8", LC_ALL="ja_JP.UTF-8"))
    return p.stdout.decode("utf-8", errors="replace")


# ---- 二重起動の防止 ----

def acquire_lock():
    try:
        with open(LOCK) as f:
            pid = int(f.read().strip() or 0)
        if pid and pid != os.getpid():
            try:
                os.kill(pid, 0)
                return False  # 前のが動いている
            except OSError:
                pass
    except (OSError, ValueError):
        pass
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


# ---- 設定（初めて ⌃⌥S を押したとき、または slack-triage setup） ----

def gh_login():
    """gh でログインしている GitHub のアカウント名（登録できるのは、このアカウント配下のリポジトリだけ）"""
    gh = which("gh")
    if not gh:
        return None
    p = subprocess.run([gh, "api", "user", "-q", ".login"], capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    login = p.stdout.strip()
    return login if p.returncode == 0 and login and "/" not in login else None


def board_repo():
    """task-hub のボードの issues リポジトリ（config.ini の [board] issues。ほかのタスクの Issue と同じ場所）"""
    try:
        with open(TASK_HUB_CONFIG, encoding="utf-8") as f:
            section = None
            for line in f:
                t = line.split(";", 1)[0].split("#", 1)[0].strip()
                if t.startswith("[") and t.endswith("]"):
                    section = t[1:-1].strip()
                elif section == "board" and "=" in t and t.split("=", 1)[0].strip() == "issues":
                    v = t.split("=", 1)[1].strip()
                    return v if core.is_valid_repo(v) else None
    except OSError:
        pass
    return None


def recent_repos(owner):
    """自分のアカウント配下のリポジトリ（最近 push した順）。会社(organization)のものは出さない"""
    gh = which("gh")
    if not gh or not owner:
        return []
    p = subprocess.run([gh, "api", "user/repos?sort=pushed&per_page=50&affiliation=owner",
                        "-q", ".[] | select(.archived | not) | .full_name"],
                       capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        return []
    return [x for x in p.stdout.split("\n") if core.owned_by(x, owner)]


def fill_repo_settings(cfg):
    """allowed_owner（gh のアカウント）と research_repo（ボードの issues リポジトリ）を入れる。変えたら True"""
    changed = False
    if not cfg.get("allowed_owner"):
        login = gh_login()
        if login:
            cfg["allowed_owner"] = login
            changed = True
    board = board_repo()
    if board and cfg.get("research_repo") != board:
        cfg["research_repo"] = board
        changed = True
    owner = cfg.get("allowed_owner")
    if owner:
        kept = [r for r in cfg.get("candidates") or [] if core.owned_by(r, owner)]
        if kept != (cfg.get("candidates") or []):
            cfg["candidates"] = kept
            changed = True
    return changed


def default_name():
    try:
        return subprocess.run(["id", "-F"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def setup(first_time=False):
    """名前と登録先候補を決める。キャンセルなら False。
    テストや一括の設定では SLACK_TRIAGE_OWNER_NAME / SLACK_TRIAGE_REPOS で答えを渡せる"""
    cfg = load_config()
    name = os.environ.get("SLACK_TRIAGE_OWNER_NAME")
    if name is None:
        intro = "Slackトリアージを初めて使うので、2つだけ設定します。\n\n" if first_time else ""
        name = macui.ask_text(
            intro + "Slackでの あなたの表示名を入れてください。\n"
            "（スレッドの中で、あなた宛ての依頼を見分けるのに使います。例: 山田 太郎）\n\n"
            "あだ名や別の書き方もあれば、読点（、）で区切って続けて書けます。例: 山田 太郎、やまだ、山田さん",
            "、".join([cfg["owner_name"]] + cfg.get("aliases", [])) if cfg.get("owner_name") else default_name())
        if name is None:
            return False
    names = [x.strip() for x in name.replace(",", "、").split("、") if x.strip()]
    if not names:
        return False

    fill_repo_settings(cfg)
    owner = cfg.get("allowed_owner")
    research = cfg.get("research_repo")
    repos_env = os.environ.get("SLACK_TRIAGE_REPOS")
    if repos_env is not None:
        chosen = [x.strip() for x in repos_env.split(",") if core.owned_by(x.strip(), owner)]
    else:
        found = recent_repos(owner)
        current = [r for r in cfg.get("candidates", []) if core.owned_by(r, owner)]
        items = current + [r for r in found if r not in current and r != research]
        chosen = current
        if items:
            picked = macui.choose_many(
                "コードを直すタスクの作業先になりそうなリポジトリを選んでください（⌘ を押しながらクリックで複数選べます）。\n"
                "出てくるのは %s のリポジトリだけです。\n"
                "調査や回答のまとめのタスクは、選ばなくても %s に登録します。"
                % (owner or "あなた", research or "ボードのリポジトリ"),
                items, current or [])
            if picked is not None:
                chosen = picked
    cfg.update({"owner_name": names[0], "aliases": names[1:], "candidates": chosen})
    cfg.setdefault("default_repo", None)
    save_config(cfg)
    log("setup: names=%d candidates=%d" % (len(names), len(chosen)))
    return True


def cmd_setup():
    if setup():
        cfg = load_config()
        print("設定しました: 名前=%s、候補リポジトリ=%d件(%s)" % (
            "、".join([cfg["owner_name"]] + cfg.get("aliases", [])), len(cfg["candidates"]), CONFIG.replace(HOME, "~")))
        return 0
    print("設定をキャンセルしました(何も変えていません)")
    return 1


# ---- 整理と登録 ----

def practice_thread(name):
    return """山田 太郎  [10:02]
@{n} 社内ツールの README に、Windows でのセットアップ手順がなくて困っています。追記してもらえますか？急ぎではないです
{n}  [10:05]
確認します！
山田 太郎  [10:06]
あと、来週の定例は会議室Bに変わりました（共有だけです）""".format(n=name)


def cmd_run(text_source, dry_run=False):
    ui = macui.MacUI(dry_run=dry_run)
    if not acquire_lock():
        ui.notify("前のスレッドを整理中です。終わってからもう一度押してください。")
        return 0
    try:
        if not load_config().get("owner_name") and not setup(first_time=True):
            ui.notify("設定をキャンセルしました。もう一度押すと、また聞きます。")
            return 0
        cfg = load_config()
        if fill_repo_settings(cfg):
            save_config(cfg)
        cfg["hotkey_label"] = hotkey_label(cfg)
        text = text_source(cfg) if callable(text_source) else text_source
        runner = (lambda t: "") if dry_run else run_task
        result = core.triage(text, ui, ask_kiro, runner, cfg)
        # スレッドの本文はログに残さない
        log("%s%s %s" % (result["status"], " (practice)" if dry_run else "",
                         json.dumps({"task_count": result.get("task_count"), "results": result["results"]}, ensure_ascii=False)))
        return 0
    except Exception as e:
        log("error: %r" % (e,))
        try:
            ui.alert("エラーで止まりました: %s\n\n詳細: %s" % (e, LOG.replace(HOME, "~")))
        except Exception:
            pass
        return 1
    finally:
        release_lock()


# ---- 起動キー（常駐は kiro/install.sh が ~/Library/LaunchAgents に置く） ----

def launchctl(*args):
    return subprocess.run(["launchctl"] + list(args), capture_output=True, text=True)


def domain():
    return "gui/%d" % os.getuid()


def loaded():
    return launchctl("print", "%s/%s" % (domain(), LAUNCHD_LABEL)).returncode == 0


def hotkey_status():
    try:
        with open(HOTKEY_STATUS, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def wait_status(before_mtime=None):
    for _ in range(20):
        try:
            if before_mtime is None or os.path.getmtime(HOTKEY_STATUS) != before_mtime:
                s = hotkey_status()
                if s:
                    return s
        except OSError:
            pass
        time.sleep(0.25)
    return hotkey_status()


def cmd_off():
    cfg = load_config()
    cfg["enabled"] = False
    save_config(cfg)
    if loaded():
        launchctl("bootout", "%s/%s" % (domain(), LAUNCHD_LABEL))
    print("%s を止めました。再開するときは slack-triage on" % hotkey_label(cfg))
    return 0


def cmd_on():
    if not os.path.isfile(PLIST):
        print("常駐の設定(%s)がありません。%s" % (PLIST.replace(HOME, "~"), INSTALL))
        return 1
    cfg = load_config()
    cfg["enabled"] = True
    save_config(cfg)
    if not loaded():
        try:
            os.remove(HOTKEY_STATUS)
        except OSError:
            pass
        r = launchctl("bootstrap", domain(), PLIST)
        if r.returncode != 0:
            print("起動キーを始められませんでした(%s)。時間をおいて、もう一度 slack-triage on" % r.stderr.strip())
            return 1
    s = wait_status()
    if s.startswith("ok"):
        print("%s で起動できます" % hotkey_label(cfg))
        return 0
    print("起動キーを始められませんでした(%s)。slack-triage check で確かめてください" % (s or "応答がありません"))
    return 1


def cmd_key(args):
    if not args or len(args[0]) != 1 or not args[0].isalpha() or not args[0].isascii():
        print("使い方: slack-triage key t(a〜z)。修飾キーも変えるなら: slack-triage key t ctrl,opt,cmd")
        return 2
    key = args[0].lower()
    mods = args[1].lower() if len(args) > 1 else None
    if mods is not None:
        ms = [m.strip() for m in mods.split(",") if m.strip()]
        allowed = {"ctrl", "control", "opt", "option", "alt", "cmd", "command", "shift"}
        if not ms or any(m not in allowed for m in ms):
            print("修飾キーは ctrl / opt / cmd / shift を , で区切って書いてください(例: ctrl,opt)")
            return 2
        mods = ",".join(ms)
    cfg = load_config()
    cfg["hotkey_key"] = key
    if mods:
        cfg["hotkey_mods"] = mods
    save_config(cfg)
    label = hotkey_label(cfg)
    if cfg.get("enabled") is False or not loaded():
        print("起動キーを %s にしました(次に常駐を始めたときから使えます)" % label)
        return 0
    try:
        before = os.path.getmtime(HOTKEY_STATUS)
    except OSError:
        before = None
    launchctl("kickstart", "-k", "%s/%s" % (domain(), LAUNCHD_LABEL))  # 新しいキーで起動し直す
    s = wait_status(before)
    if s.startswith("ok"):
        print("起動キーを %s にしました" % label)
        return 0
    print("起動キーを %s にしましたが、登録できませんでした(%s)。別のキーを試してください" % (label, s or "応答がありません"))
    return 1


# ---- 確認 ----

def checks():
    """(項目, OKか, 説明, 次にすること) の一覧"""
    out = []
    kiro = kiro_bin()
    if not kiro:
        out.append(("Kiro CLI", False, "見つかりません", INSTALL))
    else:
        r = subprocess.run([kiro, "whoami"], capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        out.append(("Kiro CLI のログイン", r.returncode == 0, "ログイン済み" if r.returncode == 0 else "未ログイン",
                    "ターミナルで kiro-cli login を実行してください"))
    tb = os.environ.get("TASK_BIN") or which("task")
    try:
        with open(TASK_HUB_CONFIG, encoding="utf-8") as f:
            board_ok = any(line.strip().startswith("issues") for line in f)
    except OSError:
        board_ok = False
    out.append(("task-hub", bool(tb) and board_ok,
                "task コマンドとボードの設定あり" if tb and board_ok else ("task コマンドがありません" if not tb else "ボードの設定がありません"),
                INSTALL))
    out.append(("整理用の設定", os.path.isfile(AGENT_FILE), AGENT_FILE.replace(HOME, "~"), INSTALL))
    cfg = load_config()
    out.append(("あなたの設定", True,
                "名前=%s、候補リポジトリ=%d件" % (cfg["owner_name"], len(cfg.get("candidates") or []))
                if cfg.get("owner_name") else "まだです(初めて %s を押したときに聞きます)" % hotkey_label(cfg), ""))
    status = hotkey_status()
    if cfg.get("enabled") is False:
        out.append(("起動キー", True, "止めています(再開は slack-triage on)", ""))
    elif loaded() and status.startswith("ok"):
        out.append(("起動キー", True, "%s で起動できます" % hotkey_label(cfg), ""))
    elif status.startswith("conflict"):
        out.append(("起動キー", False, "ほかのアプリが %s を使っています" % hotkey_label(cfg),
                    "slack-triage key t のように別のキーにしてください"))
    else:
        out.append(("起動キー", False, "常駐していません", INSTALL))
    return out


def cmd_check():
    bad = 0
    for name, ok, detail, todo in checks():
        print("%s %s: %s" % ("○" if ok else "×", name, detail))
        if not ok:
            bad += 1
            print("    → %s" % todo)
    if bad:
        print("× の行の → のとおりにしてください。")
    else:
        print("使えます。Slackでスレッドをコピーして %s を押してください。" % hotkey_label())
    return 1 if bad else 0


def main(argv=None):
    _setup_env()
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "run"
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if cmd == "check":
        return cmd_check()
    if cmd == "setup":
        return cmd_setup()
    if cmd == "off":
        return cmd_off()
    if cmd == "on":
        return cmd_on()
    if cmd == "key":
        return cmd_key(argv[1:])
    if cmd == "practice":
        return cmd_run(lambda cfg: practice_thread(cfg.get("owner_name") or "自分"), dry_run=True)
    if cmd == "run":
        return cmd_run(lambda cfg: read_clipboard(), dry_run="--dry-run" in argv)
    print("知らないコマンドです: %s\n%s" % (cmd, __doc__))
    return 2
