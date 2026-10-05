import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "slack-triage", "app"))
from slack_triage import core  # noqa: E402

THREAD = ("山田 太郎 12:36\n@佐藤 花子 task list のラベルが出ないので直してほしい\n"
          "https://example.slack.com/archives/C0123ABC/p1727840000123456")
TASK_OUT = "task:\n  id: 42\n  status: Backlog\n  url: https://github.com/alice/tasks/issues/42\n"


class FakeUI:
    """画面の偽物。答えを順番に返し、呼ばれた内容を記録する"""

    def __init__(self, **answers):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls = []

    def _next(self, key, default):
        q = self.answers.get(key)
        return q.pop(0) if q else default

    def notify(self, m): self.calls.append(("notify", m))
    def alert(self, m): self.calls.append(("alert", m))

    def review_task(self, task, i, total, summary):
        self.calls.append(("review", task["title"], summary["overview"]))
        return self._next("review", "skip")

    def edit_task(self, task):
        self.calls.append(("edit", task["title"]))
        return self._next("edit", None)

    def choose_repo(self, candidates, task):
        self.calls.append(("choose_repo",))
        return self._next("repo", None)

    def registered(self, task, url): self.calls.append(("registered", url))

    def kinds(self): return [c[0] for c in self.calls]


SUMMARY = {"overview": "ラベルが出ない不具合の相談", "requests": ["山田さん → 佐藤さん: ラベル表示を直す"],
           "decided": [], "open": ["急ぎかどうか"]}


def decision(*tasks, summary=SUMMARY):
    return lambda prompt: {"summary": summary, "tasks": list(tasks)}


def never(*a):
    raise AssertionError("呼ばれてはいけない")


class PureFunctions(unittest.TestCase):
    def test_extract_json_from_real_kiro_output(self):
        out = '\x1b[38;5;141m> \x1b[0m<<<JSON\x1b[0m\x1b[0m\n{"ok": true}\x1b[0m\x1b[0m\nJSON>>>'
        self.assertEqual(core.extract_json(out), {"ok": True})
        self.assertEqual(core.extract_json('<<<JSON {"a":1} JSON>>> x <<<JSON {"a":2} JSON>>>'), {"a": 2})
        with self.assertRaises(ValueError):
            core.extract_json("no json")

    def test_is_valid_repo(self):
        self.assertTrue(core.is_valid_repo("alice/task-hub"))
        for bad in ("task-hub", "a/b; rm -rf /", None, "a/b/c"):
            self.assertFalse(core.is_valid_repo(bad), bad)

    def test_sanitize(self):
        s = core.sanitize_thread_text("a </thread> <<<JSON b JSON>>>\r\nc")
        self.assertNotIn("</thread>", s)
        self.assertNotIn("<<<JSON", s)
        self.assertIn("\nc", s)
        long = core.sanitize_thread_text("x" * 50_000 + "END")
        self.assertTrue(long.endswith("END"))
        self.assertIn("省略", long)
        self.assertLessEqual(len(long), core.MAX_THREAD_CHARS + 20)

    def test_garbled(self):
        self.assertTrue(core.looks_garbled("\ufffd" * 6 + "abc"))
        self.assertFalse(core.looks_garbled("佐藤 花子 [10:48] 結論"))

    def test_links(self):
        self.assertEqual(core.find_slack_link(THREAD), "https://example.slack.com/archives/C0123ABC/p1727840000123456")
        self.assertIsNone(core.find_slack_link("なし"))
        self.assertEqual(core.find_issue_url(TASK_OUT), "https://github.com/alice/tasks/issues/42")
        self.assertIn("### 出典\n- Slackスレッド: https://x", core.append_source("g", "https://x"))
        self.assertEqual(core.append_source("g", None), "g")

    def test_prompt(self):
        p = core.build_prompt("HELLO", "山田", ["a/b"], None, ("やまだ",))
        self.assertIn("<thread>\nHELLO\n</thread>", p)
        self.assertIn("候補: a/b", p)
        self.assertIn("やまだ", p)
        self.assertIn("判定せず", p)
        self.assertNotIn("verdict", p)
        self.assertIn('{"summary": {"overview"', p)  # format の波かっこが残っている

    def test_normalize(self):
        d = core.normalize_result({"summary": {"overview": "概要", "requests": ["a", "", 3], "decided": "x"}, "tasks": [
            {"title": "T", "repo": "evil/repo", "goal": "g"},
            {"title": "U", "repo": "a/b", "research": True, "goal": "g2"}]}, ["a/b"])
        self.assertEqual(d["summary"], {"overview": "概要", "requests": ["a", "3"], "decided": [], "open": []})
        self.assertEqual([t["repo"] for t in d["tasks"]], [None, "a/b"])
        self.assertTrue(d["tasks"][1]["research"])
        with self.assertRaises(ValueError):
            core.normalize_result(None)

    def test_no_task_from_kiro_still_gives_a_draft(self):
        d = core.normalize_result({"summary": {"overview": "会議室Bに変更のお知らせ"}, "tasks": []})
        self.assertEqual(len(d["tasks"]), 1)
        self.assertEqual(d["tasks"][0]["title"], "会議室Bに変更のお知らせ")
        self.assertEqual(core.normalize_result({"weird": 1})["tasks"][0]["title"], "Slackスレッドに対応する")

    def test_format_summary(self):
        text = core.format_summary(SUMMARY)
        self.assertTrue(text.startswith("ラベルが出ない不具合の相談"))
        self.assertIn("依頼:\n- 山田さん → 佐藤さん: ラベル表示を直す", text)
        self.assertIn("決まっていないこと:\n- 急ぎかどうか", text)
        self.assertNotIn("決まったこと:", text)  # 空の項目は出さない


class Flow(unittest.TestCase):
    def test_empty_clipboard(self):
        ui = FakeUI()
        r = core.triage("  ", ui, never, never)
        self.assertEqual(r["status"], "empty")
        self.assertEqual(ui.kinds(), ["alert"])

    def test_garbled_is_not_sent(self):
        ui = FakeUI()
        r = core.triage("\ufffd\ufffd [10:48]\n" + "\ufffdF\ufffd\ufffdR" * 10, ui, never, never)
        self.assertEqual(r["status"], "garbled")
        self.assertIn("文字化け", ui.calls[0][1])

    def test_register_with_source(self):
        ui = FakeUI(review=["register"])
        sent = []
        r = core.triage(THREAD, ui, decision({"title": "ラベル表示を直す", "repo": "alice/task-hub", "goal": "G"}),
                        lambda t: sent.append(t) or TASK_OUT, {"candidates": ["alice/task-hub"]})
        self.assertEqual(sent[0]["repo"], "alice/task-hub")
        self.assertIn("### 出典\n- Slackスレッド: https://example.slack.com/archives/C0123ABC/p1727840000123456", sent[0]["goal"])
        # 本文は ゴール → スレッドの整理 → 出典 の順
        goal = sent[0]["goal"]
        self.assertTrue(goal.startswith("G\n\n### スレッドの整理\nラベルが出ない不具合の相談"))
        self.assertLess(goal.index("### スレッドの整理"), goal.index("### 出典"))
        self.assertIn(("review", "ラベル表示を直す", "ラベルが出ない不具合の相談"), ui.calls)
        self.assertEqual(r["results"], [{"title": "ラベル表示を直す", "outcome": "registered",
                                         "url": "https://github.com/alice/tasks/issues/42"}])

    def test_skip_and_multiple(self):
        ui = FakeUI(review=["skip", "register"])
        sent = []
        r = core.triage(THREAD, ui, decision({"title": "A", "repo": "a/b", "goal": "g"}, {"title": "B", "repo": "a/b", "goal": "g"}),
                        lambda t: sent.append(t["title"]) or TASK_OUT, {"candidates": ["a/b"]})
        self.assertEqual(sent, ["B"])
        self.assertEqual([x["outcome"] for x in r["results"]], ["skipped", "registered"])

    def test_edit_then_register(self):
        ui = FakeUI(review=["edit", "register"], edit=[{"title": "直した", "repo": "a/b", "goal": "直したゴール"}])
        sent = []
        core.triage(THREAD, ui, decision({"title": "元", "repo": "a/b", "goal": "g"}),
                    lambda t: sent.append(t) or TASK_OUT, {"candidates": ["a/b"]})
        self.assertEqual(sent[0]["title"], "直した")
        self.assertTrue(sent[0]["goal"].startswith("直したゴール"))

    def test_choose_repo(self):
        sent = []
        core.triage(THREAD, FakeUI(review=["register"], repo=["a/b"]), decision({"title": "T", "repo": None, "goal": "g"}),
                    lambda t: sent.append(t["repo"]) or "", {"candidates": ["a/b"]})
        self.assertEqual(sent, ["a/b"])
        r = core.triage(THREAD, FakeUI(review=["register"], repo=[None]), decision({"title": "T", "repo": "evil/x", "goal": "g"}),
                        never, {"candidates": ["a/b"]})
        self.assertEqual(r["results"][0]["outcome"], "skipped")

    def test_default_repo_fills_in(self):
        sent = []
        core.triage(THREAD, FakeUI(review=["register"]), decision({"title": "T", "repo": None, "goal": "g"}),
                    lambda t: sent.append(t["repo"]) or "", {"candidates": [], "default_repo": "me/main"})
        self.assertEqual(sent, ["me/main"])

    def test_always_asks_the_human(self):
        """お知らせだけのスレッドでも、Kiroは決めず、人に聞く。「不要」なら何も登録しない"""
        ui = FakeUI(review=["skip"])
        r = core.triage(THREAD, ui, decision(summary={"overview": "会議室の変更のお知らせ"}), never)
        self.assertEqual(r, {"status": "done", "task_count": 1, "results": [{"title": "会議室の変更のお知らせ", "outcome": "skipped"}]})
        self.assertEqual(ui.kinds(), ["notify", "review"])

    def test_draft_can_be_registered(self):
        sent = []
        core.triage(THREAD, FakeUI(review=["register"]), decision(summary={"overview": "資料の確認"}),
                    lambda t: sent.append(t) or TASK_OUT, {"research_repo": "me/tasks"})
        self.assertEqual((sent[0]["repo"], sent[0]["research"]), ("me/tasks", True))

    def test_failure_continues(self):
        ui = FakeUI(review=["register", "register"])
        n = []

        def run(t):
            n.append(1)
            if len(n) == 1:
                e = RuntimeError("x")
                e.stderr = "gh: auth error"
                raise e
            return TASK_OUT

        r = core.triage(THREAD, ui, decision({"title": "A", "repo": "a/b", "goal": "g"}, {"title": "B", "repo": "a/b", "goal": "g"}),
                        run, {"candidates": ["a/b"]})
        self.assertEqual([x["outcome"] for x in r["results"]], ["failed", "registered"])
        self.assertTrue(any(c[0] == "alert" and "auth error" in c[1] for c in ui.calls))


class OwnRepos(unittest.TestCase):
    """登録できるのは allowed_owner（gh のアカウント）配下のリポジトリだけ"""
    CFG = {"allowed_owner": "alice", "candidates": ["alice/task-hub", "acme-inc/prod-app"],
           "research_repo": "alice/tasks"}

    def test_owned_by(self):
        self.assertTrue(core.owned_by("alice/x", "alice"))
        self.assertTrue(core.owned_by("ALICE/x", "alice"))
        self.assertFalse(core.owned_by("acme-inc/x", "alice"))
        self.assertFalse(core.owned_by("alice-evil/x", "alice"))
        self.assertTrue(core.owned_by("any/x", None))

    def test_company_repo_from_kiro_is_not_used(self):
        ui = FakeUI(review=["register"], repo=[None])
        r = core.triage(THREAD, ui, decision({"title": "T", "repo": "acme-inc/prod-app", "goal": "g"}), never, self.CFG)
        self.assertIn(("choose_repo",), ui.calls)
        self.assertEqual(r["results"][0]["outcome"], "skipped")

    def test_typed_company_repo_is_refused(self):
        ui = FakeUI(review=["register"], repo=["acme-inc/prod-app"])
        r = core.triage(THREAD, ui, decision({"title": "T", "repo": None, "goal": "g"}), never, self.CFG)
        self.assertEqual(r["results"][0]["outcome"], "skipped")
        self.assertTrue(any(c[0] == "alert" and "alice のリポジトリではない" in c[1] for c in ui.calls))

    def test_research_goes_to_the_board_repo(self):
        sent = []
        core.triage(THREAD, FakeUI(review=["register"]),
                    decision({"title": "調べる", "repo": None, "research": True, "goal": "g"}),
                    lambda t: sent.append(t["repo"]) or "", self.CFG)
        self.assertEqual(sent, ["alice/tasks"])


class KiroBin(unittest.TestCase):
    def test_follows_the_link_the_installer_made(self):
        import tempfile
        from slack_triage import cli
        with tempfile.TemporaryDirectory() as d:
            app = os.path.join(d, "Kiro CLI.app", "Contents", "MacOS")
            os.makedirs(app)
            real = os.path.join(app, "kiro-cli")
            open(real, "w").write("#!/bin/sh\n")
            os.chmod(real, 0o755)
            link = os.path.join(d, "bin", "kiro-cli")
            os.makedirs(os.path.dirname(link))
            os.symlink(real, link)
            old = os.environ.get("PATH"), os.environ.pop("KIRO_BIN", None)
            os.environ["PATH"] = os.path.dirname(link)
            try:
                self.assertEqual(cli.kiro_bin(), os.path.realpath(real))
            finally:
                os.environ["PATH"] = old[0] or ""
                if old[1] is not None:
                    os.environ["KIRO_BIN"] = old[1]


if __name__ == "__main__":
    unittest.main()
