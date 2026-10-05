"""macOS標準のダイアログ（AppleScript）。
表示する文章は argv で渡し、スクリプト本文には埋め込まない（文章中の記号でスクリプトが壊れたり、命令として実行されたりしない）。"""
import os
import subprocess
import tempfile

from .core import format_summary, is_valid_repo

TITLE = "Slackトリアージ"
OTHER = "その他（入力する）"


class Cancelled(Exception):
    pass


def osa(script, *args):
    """AppleScriptを実行して結果を返す。キャンセル（-128）なら None"""
    p = subprocess.run(["osascript", "-e", script] + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        if "-128" in p.stderr:
            return None
        raise RuntimeError("ダイアログを出せませんでした: " + p.stderr.strip())
    return p.stdout.rstrip("\n")


def _preview(s, n):
    s = s or ""
    return s[:n] + "…" if len(s) > n else s


_DIALOG = """on run argv
  activate
  set r to display dialog (item 1 of argv) with title (item 2 of argv) buttons %s default button "%s"
  return button returned of r
end run"""


class MacUI:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run

    def notify(self, message):
        try:
            osa('on run argv\n  display notification (item 1 of argv) with title (item 2 of argv)\nend run', message, TITLE)
        except Exception:
            pass  # 通知は出なくても続ける

    def alert(self, message):
        osa(_DIALOG % ('{"OK"}', "OK"), message, TITLE)

    def review_task(self, task, index, total, summary):
        body = "\n".join([
            "タスクにしますか？  %d / %d%s" % (index + 1, total, "　※練習モード（登録しません）" if self.dry_run else ""),
            "",
            "【スレッドの整理】",
            _preview(format_summary(summary), 600),
            "",
            "【タスク案】",
            "■ %s%s" % (task["title"], "（調査タスク）" if task.get("research") else ""),
            "リポジトリ: %s" % (task.get("repo") or "未決定（登録時に選びます）"),
            "",
            _preview(task["goal"], 600),
            "",
            "登録すると、スレッドの整理もカードの本文に残ります。",
        ])
        r = osa(_DIALOG % ('{"不要", "内容を直す", "登録"}', "登録"), body, TITLE)
        return {"登録": "register", "内容を直す": "edit"}.get(r, "skip")

    def edit_task(self, task):
        """タイトルはダイアログ、ゴールはTextEditで直す。キャンセルなら None"""
        title = osa("""on run argv
  activate
  set r to display dialog "タイトル" with title (item 2 of argv) default answer (item 1 of argv) buttons {"キャンセル", "次へ"} default button "次へ" cancel button "キャンセル"
  return text returned of r
end run""", task["title"], TITLE)
        if title is None:
            return None
        with tempfile.TemporaryDirectory(prefix="slack-triage-") as d:
            path = os.path.join(d, "goal.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(task["goal"])
            subprocess.run(["open", "-e", path], check=False)
            ok = osa("""on run argv
  activate
  display dialog "TextEdit でゴールを直して保存（⌘S）したら「完了」を押してください。" with title (item 1 of argv) buttons {"キャンセル", "完了"} default button "完了" cancel button "キャンセル"
  return "ok"
end run""", TITLE)
            if ok is None:
                return None
            with open(path, encoding="utf-8") as f:
                goal = f.read().strip()
        return dict(task, title=title.strip() or task["title"], goal=goal or task["goal"])

    def choose_repo(self, candidates, task):
        repo = None
        if candidates:
            repo = osa("""on run argv
  activate
  set r to choose from list (items 3 thru -1 of argv) with prompt (item 1 of argv) with title (item 2 of argv)
  if r is false then return ""
  return item 1 of r
end run""", "「%s」の登録先リポジトリ" % task["title"], TITLE, *(list(candidates) + [OTHER]))
            if not repo:
                return None
        if not repo or repo == OTHER:
            repo = ask_text("登録先リポジトリ（owner/name）", "")
        repo = (repo or "").strip() or None
        if repo and not is_valid_repo(repo):
            self.alert("「%s」は owner/name の形式ではないので、この候補は登録しません。" % repo)
            return None
        return repo

    def registered(self, task, url):
        if self.dry_run:
            self.alert("練習モードなので登録はしていません。\n本番では、ここで task-hub の Backlog にカードができます。\n\n%s" % task["title"])
            return
        r = osa(_DIALOG % ('{"閉じる", "Issueを開く"}', "閉じる"),
                "登録しました（Backlog）\n\n%s\n%s\n\nカードを Ready にする（または task start）とエージェントが着手します。"
                % (task["title"], url or ""), TITLE)
        if r == "Issueを開く" and url:
            subprocess.run(["open", url], check=False)


# ---- 設定用のダイアログ ----

def ask_text(prompt, default):
    return osa("""on run argv
  activate
  set r to display dialog (item 1 of argv) with title (item 3 of argv) default answer (item 2 of argv) buttons {"キャンセル", "OK"} default button "OK" cancel button "キャンセル"
  return text returned of r
end run""", prompt, default, TITLE)


def choose_many(prompt, items, defaults):
    """複数選択。キャンセルなら None、何も選ばなければ []"""
    if not items:
        return []
    out = osa("""on run argv
  set n to (item 3 of argv) as integer
  set allItems to items 4 thru (3 + n) of argv
  if (count of argv) > (3 + n) then
    set defs to items (4 + n) thru -1 of argv
  else
    set defs to {}
  end if
  activate
  set r to choose from list allItems with prompt (item 1 of argv) with title (item 2 of argv) default items defs with multiple selections allowed and empty selection allowed
  if r is false then return "__CANCEL__"
  set AppleScript's text item delimiters to linefeed
  return r as text
end run""", prompt, TITLE, len(items), *(list(items) + list(defaults)))
    if out is None or out == "__CANCEL__":
        return None
    return [x for x in out.split("\n") if x]


def confirm(message, yes="はい", no="あとで"):
    return osa(_DIALOG % ('{"%s", "%s"}' % (no, yes), yes), message, TITLE) == yes
