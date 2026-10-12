"""Windows のダイアログ(tkinter。Python に付いてくるので、ほかに何も入れない)。macui.py と同じ関数を持つ。
表示する文章はウィジェットに文字として渡すだけで、どこにも命令として埋め込まない。
通知は bin/task と同じく、Windows PowerShell 5.1 からトースト(文章は環境変数で渡す)。"""
import os
import subprocess

from .core import format_summary, is_valid_repo

TITLE = "Slackトリアージ"
OTHER = "その他（入力する）"
FONT = ("Yu Gothic UI", 10)  # Windows 10/11 の日本語の標準のフォント(無ければ tk が近いものを使う)
# Windows PowerShell 5.1 は、PATH が狭くても(起動キーから起動したとき)ここにある
POWERSHELL = os.path.join(os.environ.get("SystemRoot") or "C:\\Windows", "System32", "WindowsPowerShell", "v1.0",
                          "powershell.exe")

TOAST = """$m = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$x = $m::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
[void]$t.Item(0).AppendChild($x.CreateTextNode($env:SLACK_TRIAGE_TITLE))
[void]$t.Item(1).AppendChild($x.CreateTextNode($env:SLACK_TRIAGE_BODY))
$m::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show(
    [Windows.UI.Notifications.ToastNotification]::new($x))"""


class Cancelled(Exception):
    pass


def _preview(s, n):
    s = s or ""
    return s[:n] + "…" if len(s) > n else s


def _window():
    """前に出る、1 枚だけのウィンドウ。Ctrl+Alt+S から起動したとき、ほかのアプリの後ろに隠れないように"""
    import tkinter as tk
    root = tk.Tk()
    root.title(TITLE)
    root.option_add("*Font", FONT)
    root.attributes("-topmost", True)
    root.resizable(True, True)
    root.answer = None
    root.protocol("WM_DELETE_WINDOW", root.destroy)  # × で閉じたら、答えは None(キャンセル)
    return root


def _run(root):
    """表示して、ボタンが押されるか閉じられるまで待つ。答えを返す(テストはここを差し替える)"""
    root.lift()
    root.focus_force()
    root.mainloop()
    return root.answer


def _buttons(root, labels, default):
    """右下に並ぶボタン。押すと、そのラベルを答えにして閉じる。Enter は default"""
    import tkinter as tk
    bar = tk.Frame(root)
    bar.pack(side="bottom", fill="x", padx=12, pady=10)
    root.buttons = {}
    for label in reversed(labels):
        def press(label=label):
            root.answer = label if root.answer is None else root.answer
            root.destroy()
        b = tk.Button(bar, text=label, width=max(8, len(label) * 2), command=press,
                      default="active" if label == default else "normal")
        b.pack(side="right", padx=4)
        root.buttons[label] = b
    root.bind("<Return>", lambda e: root.buttons[default].invoke())
    root.bind("<Escape>", lambda e: root.destroy())


def _text(root, body, height=12):
    """読むだけの、スクロールできる文章"""
    import tkinter as tk
    frame = tk.Frame(root)
    frame.pack(side="top", fill="both", expand=True, padx=12, pady=(12, 0))
    bar = tk.Scrollbar(frame)
    bar.pack(side="right", fill="y")
    t = tk.Text(frame, wrap="char", width=72, height=height, yscrollcommand=bar.set, relief="flat",
                background=root.cget("background"))
    t.insert("1.0", body)
    t.configure(state="disabled")
    t.pack(side="left", fill="both", expand=True)
    bar.configure(command=t.yview)
    return t


def dialog(message, buttons, default):
    """文章とボタン。押したボタンのラベル、閉じたら None"""
    root = _window()
    _buttons(root, buttons, default)
    _text(root, message, height=min(24, max(4, message.count("\n") + 2)))
    return _run(root)


class WinUI:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run

    def notify(self, message):
        try:  # 通知は出なくても続ける
            subprocess.Popen([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", TOAST],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=dict(os.environ, SLACK_TRIAGE_TITLE=TITLE, SLACK_TRIAGE_BODY=message),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            pass

    def alert(self, message):
        dialog(message, ["OK"], "OK")

    def review_task(self, task, index, total, summary):
        body = "\n".join([
            "タスクにしますか？  %d / %d%s" % (index + 1, total, "　※練習モード（登録しません）" if self.dry_run else ""),
            "",
            "【スレッドの整理】",
            _preview(format_summary(summary), 1200),
            "",
            "【タスク案】",
            "■ %s%s" % (task["title"], "（調査タスク）" if task.get("research") else ""),
            "リポジトリ: %s" % (task.get("repo") or "未決定（登録時に選びます）"),
            "",
            _preview(task["goal"], 1200),
            "",
            "登録すると、スレッドの整理もカードの本文に残ります。",
        ])
        r = dialog(body, ["不要", "内容を直す", "登録"], "登録")
        return {"登録": "register", "内容を直す": "edit"}.get(r, "skip")

    def edit_task(self, task):
        """タイトルとゴールを 1 つの画面で直す(Mac は TextEdit を使うが、Windows はこの画面の中で)。キャンセルなら None"""
        import tkinter as tk
        root = _window()
        _buttons(root, ["キャンセル", "登録へ"], "登録へ")
        tk.Label(root, text="タイトル", anchor="w").pack(side="top", fill="x", padx=12, pady=(12, 0))
        title = tk.Entry(root, width=72)
        title.insert(0, task["title"])
        title.pack(side="top", fill="x", padx=12)
        tk.Label(root, text="ゴール(エージェントへの指示)", anchor="w").pack(side="top", fill="x", padx=12, pady=(10, 0))
        goal = tk.Text(root, wrap="char", width=72, height=16)
        goal.insert("1.0", task["goal"])
        goal.pack(side="top", fill="both", expand=True, padx=12)
        root.unbind("<Return>")  # ゴールの中の改行は、改行のまま
        values = {}

        def keep(*_):  # 閉じる前に読む(閉じたあとのウィジェットは読めない)
            values["title"], values["goal"] = title.get(), goal.get("1.0", "end-1c")
        root.buttons["登録へ"].configure(command=lambda: (keep(), setattr(root, "answer", "登録へ"), root.destroy()))
        root.edit = (title, goal)
        if _run(root) != "登録へ":
            return None
        return dict(task, title=values.get("title", "").strip() or task["title"],
                    goal=values.get("goal", "").strip() or task["goal"])

    def choose_repo(self, candidates, task):
        repo = None
        if candidates:
            picked = _choose("「%s」の登録先リポジトリ" % task["title"], list(candidates) + [OTHER], [], many=False)
            if not picked:
                return None
            repo = picked[0]
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
        r = dialog("登録しました（Backlog）\n\n%s\n%s\n\nカードを Ready にする（または task start）とエージェントが着手します。"
                   % (task["title"], url or ""), ["閉じる", "Issueを開く"], "閉じる")
        if r == "Issueを開く" and url:
            os.startfile(url)  # 既定のブラウザで開く


# ---- 設定用のダイアログ ----

def ask_text(prompt, default):
    """1 行の入力。キャンセルなら None"""
    import tkinter as tk
    root = _window()
    _buttons(root, ["キャンセル", "OK"], "OK")
    _text(root, prompt, height=min(12, max(3, prompt.count("\n") + 2)))
    entry = tk.Entry(root, width=72)
    entry.insert(0, default or "")
    entry.pack(side="top", fill="x", padx=12, pady=(6, 0))
    entry.focus_set()
    values = {}
    root.buttons["OK"].configure(command=lambda: (values.update(v=entry.get()), setattr(root, "answer", "OK"),
                                                  root.destroy()))
    root.entry = entry
    return values.get("v", "") if _run(root) == "OK" else None


def _choose(prompt, items, defaults, many):
    """一覧から選ぶ。キャンセルなら None"""
    import tkinter as tk
    root = _window()
    _buttons(root, ["キャンセル", "OK"], "OK")
    _text(root, prompt, height=min(8, max(3, prompt.count("\n") + 2)))
    box = tk.Listbox(root, selectmode="extended" if many else "browse", width=72, height=min(16, max(4, len(items))),
                     exportselection=False)
    for i, item in enumerate(items):
        box.insert("end", item)
        if item in defaults:
            box.selection_set(i)
    if not many and items and not defaults:
        box.selection_set(0)
    box.pack(side="top", fill="both", expand=True, padx=12, pady=(6, 0))
    picked = []
    root.buttons["OK"].configure(command=lambda: (picked.extend(items[i] for i in box.curselection()),
                                                  setattr(root, "answer", "OK"), root.destroy()))
    root.box = box
    return picked if _run(root) == "OK" else None


def choose_many(prompt, items, defaults):
    """複数選択。キャンセルなら None、何も選ばなければ []"""
    if not items:
        return []
    # Mac の「⌘ を押しながら」は Windows では Ctrl
    return _choose(prompt.replace("⌘ を押しながら", "Ctrl を押しながら"), list(items), list(defaults), many=True)


def confirm(message, yes="はい", no="あとで"):
    return dialog(message, [no, yes], yes) == yes
