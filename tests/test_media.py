"""The pictures in assets/media/ (docs/media.md), and the story tests/media.py takes them from.

- Every file tests/media.py writes is there and nothing else, each within its size limit, and none shows the owner's
  board or work, this machine (its paths, its user, its git e-mail address), a date, or an e-mail address: in the text
  each picture shows (assets/media/text.json) and in its bytes (metadata).
- The checks find each of those when it is there.
- The made-up card still runs through bin/task, against the fake GitHub, and prints the same text twice, with nothing
  private in it. Chrome and ffmpeg are not needed: they only turn that text into pictures.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media  # noqa: E402


class MediaFilesTest(unittest.TestCase):

    def test_every_picture_is_there_within_its_limit_and_shows_nothing_private(self):
        texts = json.loads((media.MEDIA / media.TEXTS).read_text(encoding="utf-8"))
        self.assertEqual(media.problems(media.MEDIA, texts), [])

    def test_the_moving_picture_and_both_themes_of_each_screen_and_layer(self):
        names = media.expected_files()
        self.assertTrue({"flow.gif", "flow.webm", "flow.avif"} <= set(names))
        for name in [*media.SCREENS, *(f"layers/{n}" for n in media.LAYERS)]:
            with self.subTest(name):
                self.assertIn(f"{name}-dark.png", names)
                self.assertIn(f"{name}-light.png", names)
        self.assertEqual(len(media.LAYERS), 8)  # docs/brand.md section 4
        self.assertTrue(13 <= sum(f[0] for f in media.FLOW) <= 17)  # 15 seconds or so

    def test_the_checks_find_what_must_not_show(self):
        for text in ("2026-10-29T11:23:31Z", "on 2026/10/29", "10月29日", "id 20261029", "me@example.com",
                     "/Users/someone/notes", "/home/someone", "/var/folders/ab/T/x", "jyoka/tasks#12", "aica"):
            with self.subTest(text):
                self.assertNotEqual(media.leaks(text, machine=set()), [])
        self.assertEqual(media.leaks("x /opt/me/notes", machine={"/opt/me"}), [("this machine", "/opt/me")])
        for text in ("event: #12 Done | Add a search box to the notes list | you/notes-app | pr "
                     "https://github.com/you/notes-app/pull/1", "09:14 時点 · 1 分ごとに更新", "task/12",
                     "log: ~/.local/state/task-hub/logs/12.log (17 lines)", "4分 / 普段9分"):
            with self.subTest(text):
                self.assertEqual(media.leaks(text, machine=set()), [])

    def test_the_byte_checks_find_metadata_today_and_paths(self):
        png = b"\x89PNG\r\n\x1a\n"

        def chunk(kind, data=b""):
            return len(data).to_bytes(4, "big") + kind + data + b"\0\0\0\0"

        plain = png + chunk(b"IHDR", b"\0" * 13) + chunk(b"IDAT", b"tEXt by chance") + chunk(b"IEND")
        self.assertEqual(media.leaks_in_bytes(plain, machine=set()), [])
        tagged = png + chunk(b"IHDR", b"\0" * 13) + chunk(b"tEXt", b"Comment\0hi") + chunk(b"IEND")
        self.assertEqual(media.leaks_in_bytes(tagged, machine=set()), [("metadata", "tEXt")])
        today = __import__("datetime").date(2026, 10, 29)
        self.assertEqual(media.leaks_in_bytes(b"made 2026:10:29 12:00", machine=set(), today=today),
                         [("date", "2026:10:29")])
        self.assertEqual(media.leaks_in_bytes(b"in /Users/x", machine=set()), [("local path", "/Users/")])


class MediaStoryTest(unittest.TestCase):

    def told(self):
        """What the terminal and the boards' `task list` show, from one run of the story."""
        with tempfile.TemporaryDirectory() as tmp:
            boards, said = media.story(media.World(Path(tmp)))
        return said, {name: b["list"] for name, b in boards.items()}

    def test_the_story_prints_the_same_twice_and_nothing_private(self):
        first, second = self.told(), self.told()
        self.assertEqual(first, second)
        said, lists = first
        self.assertEqual(set(lists), set(media.MINUTES))
        shown = [c + "\n" + o for c, o in said.values()] + list(lists.values())
        self.assertEqual([leak for text in shown for leak in media.leaks(text)], [])
        self.assertIn("== reviewer verdict: needs changes", said["log"][1])  # the review sends it back once
        self.assertIn("== reviewer verdict: pass", said["log"][1])
        self.assertIn("Add a search box to the notes list,wait for merge,you/notes-app", lists["queued"])
        self.assertNotIn('"12"', lists["merged"])  # merged: no longer an open card


if __name__ == "__main__":
    unittest.main()
