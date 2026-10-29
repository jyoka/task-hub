"""The landing page in site/ (site/README.md), read as files: no browser, nothing from the network.

- Every link and picture leads somewhere: an id on the page, a file under site/ or assets/, or a file and heading in
  this repository on GitHub. The three buttons are there.
- Nothing loads from outside: the page's policy (CSP), its src attributes, its CSS, and its script.
- Under prefers-reduced-motion nothing moves: the 3D only applies under .motion, which site.js sets only when motion
  is allowed, smooth scrolling only without the setting, and the moving picture does not start itself.
- The words follow docs/brand.md: the one sentence, the eight feature cards (headings, two lines, docs), and the
  eight layers (names, lines, colors). English comes first, and every English span has its Japanese one.
- No private board, repository, or work name of the owner (docs/brand.md section 7), no local path or e-mail address.
"""
import html
import os
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brand import EN, JA, slug  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REPO = "https://github.com/jyoka/task-hub"
# docs/brand.md section 7, and what tests/media.py keeps out of the pictures: the owner's board, private repositories,
# work names, local paths, and e-mail addresses. jyoka/task-hub itself is public
PRIVATE = re.compile(r"jyoka/(?!task-hub\b)|aica|AIprogramming|ai-CA_RA|求人|voice-(agent|resume)|LINE のトーク"
                     r"|/Users/|/home/|/var/folders/|[\w.%+-]+@[\w-]+(\.[\w-]+)*\.[A-Za-z]{2,}", re.I)
ACTORS = {"あなた": "actor-you", "task-hub": "actor-task-hub", "エージェント": "actor-agent"}


class Page(HTMLParser):
    """The tags of a page: [(tag, {attribute: value})], and the ids."""

    def __init__(self, text):
        super().__init__()
        self.tags, self.ids = [], set()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if "id" in attrs:
            self.ids.add(attrs["id"])


def read(name):
    return (SITE / name).read_text(encoding="utf-8")


def local(path):
    """A file the page names, under site/. site/assets links to ../assets (a plain file where git makes no links)."""
    path = unquote(path.split("?")[0].split("#")[0])
    if path.startswith("assets/"):
        return ROOT / path
    return SITE / path


def headings(path):
    """The link names of a Markdown file's headings, not counting `# comments` in code blocks."""
    text = re.sub(r"(?ms)^```.*?^```", "", path.read_text(encoding="utf-8"))
    return [slug(h) for h in re.findall(r"(?m)^#+ (.*)$", text)]


def shown(markup):
    """Page text as brand.md writes it: no code tags (brand.md's backticks are dropped too), entities read."""
    return html.unescape(re.sub(r"</?code>", "", markup))


def brand_rows(section):
    """The table rows (as cells) in a numbered section of docs/brand.md, without the header."""
    text = (ROOT / "docs" / "brand.md").read_text(encoding="utf-8")
    body = re.split(r"(?m)^## ", text)
    part = next(p for p in body if p.startswith(f"{section}. "))
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in part.splitlines()
            if re.match(r"\| \d+ \|", line)]
    return rows


class SiteTest(unittest.TestCase):

    def setUp(self):
        self.html = read("index.html")
        self.page = Page(self.html)

    def test_the_one_sentence_is_the_same_as_in_brand_md(self):
        self.assertIn(f"<title>task-hub: {EN}</title>", self.html)
        self.assertIn(f'<meta name="description" content="{EN}">', self.html)
        for sentence in (EN, JA):
            with self.subTest(sentence):
                # the headline and the footer
                self.assertEqual(self.html.count(f">{sentence}</span>"), 2)
        llms = read("llms.txt")
        self.assertTrue(llms.startswith("# task-hub\n"))
        self.assertIn(f"> {EN}\n> {JA}\n", llms)
        self.assertIn(f"task-hub: {EN}", read("site.js"))
        self.assertIn(f"task-hub: {JA}", read("site.js"))

    def test_the_three_buttons(self):
        buttons = {a["data-cta"]: a for tag, a in self.page.tags if tag == "a" and "data-cta" in a}
        self.assertEqual(sorted(buttons), ["demo", "github", "start"])
        self.assertEqual(buttons["start"]["href"], f"{REPO}#get-started")
        self.assertEqual(buttons["start"]["data-ja-href"], f"{REPO}/blob/main/README.ja.md#はじめる")
        self.assertEqual(buttons["github"]["href"], REPO)
        self.assertEqual(buttons["demo"]["href"], "#demo")
        # the moving picture task-hub took of itself (docs/media.md)
        self.assertIn('<source src="assets/media/flow.webm" type="video/webm">', self.html)

    def test_every_link_and_picture_leads_somewhere(self):
        targets = [(tag, attr, value) for tag, attrs in self.page.tags for attr, value in attrs.items()
                   if attr in ("href", "src", "data-ja-href", "poster")]
        self.assertGreater(len(targets), 60)
        for tag, attr, value in targets:
            with self.subTest(f"<{tag} {attr}={value}>"):
                url = urlparse(value)
                if value.startswith("#"):
                    self.assertIn(value[1:], self.page.ids)
                elif url.scheme:
                    self.assertEqual(url.scheme, "https")
                    self.assertTrue(value == REPO or value.startswith((REPO + "#", REPO + "/blob/main/")))
                    path = url.path.removeprefix("/jyoka/task-hub").removeprefix("/blob/main/") or "README.md"
                    self.assertTrue((ROOT / unquote(path)).is_file(), path)
                    anchor = unquote(url.fragment)
                    if anchor and anchor != "readme":
                        self.assertIn(anchor, headings(ROOT / unquote(path)))
                else:
                    self.assertTrue(local(value).is_file(), value)

    def test_the_links_in_site_readme_lead_somewhere(self):
        for target, anchor in re.findall(r"\]\((\.\./[^)#\s]+)(?:#([^)\s]*))?\)", read("README.md")):
            with self.subTest(f"{target}#{anchor}"):
                path = (SITE / target).resolve()
                self.assertTrue(path.exists())
                if anchor:
                    self.assertIn(anchor, headings(path))

    def test_assets_is_a_link_to_the_repository_assets(self):
        link = SITE / "assets"
        if not link.is_symlink():
            self.skipTest("git made no symbolic link here (core.symlinks is off)")
        self.assertEqual(os.readlink(link), "../assets")

    def test_nothing_loads_from_outside(self):
        policy = next(a["content"] for tag, a in self.page.tags
                      if tag == "meta" and a.get("http-equiv") == "Content-Security-Policy")
        self.assertIn("default-src 'none'", policy)
        for kind in ("script", "style", "img", "media"):
            with self.subTest(kind):
                self.assertIn(f"{kind}-src 'self';", policy)
        self.assertNotIn("connect-src", policy)
        for tag, attrs in self.page.tags:
            with self.subTest(f"<{tag}>"):
                self.assertNotIn("style", attrs)  # the policy refuses inline styles
                self.assertFalse(any(k.startswith("on") for k in attrs))  # and inline scripts
                if tag in ("script", "img", "source", "video", "link"):
                    for attr in ("src", "href", "srcset", "poster"):
                        self.assertFalse(re.match(r"(https?:)?//", attrs.get(attr) or ""), f"{attr}={attrs.get(attr)}")
        self.assertEqual(re.findall(r"<script\b[^>]*>(.+?)</script>", self.html, re.S), [])
        self.assertNotIn("<style", self.html)  # the policy refuses inline styles
        for name in ("site.css", "site.js", "favicon.svg", "assets/brand/tokens.css"):
            with self.subTest(name):
                text = local(name).read_text(encoding="utf-8").replace('xmlns="http://www.w3.org/2000/svg"', "")
                self.assertIsNone(re.search(r"https?:|@import|url\(", text))
        self.assertIsNone(re.search(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|importScripts)\b|import\(",
                                    read("site.js")))

    def test_nothing_moves_under_reduced_motion(self):
        js = read("site.js")
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)')", js)
        self.assertIn("const moving = () => sized && !reduce.matches && tall.matches;", js)
        self.assertIn("setMotion(moving())", js)
        self.assertIn("root.classList.toggle('motion', on)", js)
        # the 3D and the long track apply only under .motion
        css = re.sub(r"/\*.*?\*/", "", read("site.css"), flags=re.S)
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if re.search(r"\b(rotate[XYZ]?|translateZ|perspective)\(|perspective:|\d+vh", body):
                for selector in selectors.split(","):
                    with self.subTest(selector.strip()):
                        self.assertTrue(selector.strip().startswith(".motion"), body)
        self.assertRegex(css, r"@media \(prefers-reduced-motion: no-preference\) \{\s*html \{ scroll-behavior: smooth; \}")
        self.assertEqual(css.count("scroll-behavior"), 1)
        video = next(a for tag, a in self.page.tags if tag == "video")
        self.assertNotIn("autoplay", video)
        self.assertIn("controls", video)
        self.assertIn("if (reduce.matches) {\n        video.autoplay = false;\n        video.pause();", js)

    def test_a_phone_gets_the_page_at_its_width(self):
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', self.html)
        css = read("site.css")
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn("white-space: pre-wrap", css)  # the commands wrap
        self.assertEqual(self.html.count("<table"), self.html.count('<div class="table-wrap">'))  # tables scroll inside

    def test_the_eight_feature_cards_follow_brand_md(self):
        cards = brand_rows(3)
        self.assertEqual(len(cards), 8)
        headings_on_page = re.findall(r'<h3><span data-lang="en">([^<]+)</span><span data-lang="ja">([^<]+)</span></h3>',
                                      self.html)
        self.assertEqual([(c[3], c[1]) for c in cards], headings_on_page)
        # each card opens the docs brand.md names for it
        links = re.findall(r'<a class="card-shot[^"]*" href="([^"]+)"', self.html)
        expected = [re.search(r"\]\(([^)]+)\)", c[5]).group(1) for c in cards]
        self.assertEqual(links, [f"{REPO}/blob/main/docs/{e}" for e in expected])
        # and its two lines are brand.md's, in both languages
        bodies = re.findall(r'<li class="card">(.*?)</li>', self.html, re.S)
        self.assertEqual(len(bodies), 8)
        for body, card in zip(bodies, cards):
            lines = re.findall(r'<p><span data-lang="en">(.*?)</span><span data-lang="ja">(.*?)</span></p>', body)
            with self.subTest(card[3]):
                self.assertEqual([shown(en) for en, _ in lines], card[4].replace("`", "").split("<br>"))
                self.assertEqual([shown(ja) for _, ja in lines], card[2].replace("`", "").split("<br>"))

    def test_the_eight_layers_follow_brand_md(self):
        rows = brand_rows(4)
        layers = re.findall(r'<li class="layer ([\w-]+)[^"]*" data-layer="(\d)">(.*?)</li>', self.html, re.S)
        self.assertEqual(len(rows), 8)
        self.assertEqual([n for _, n, _ in layers], [str(i) for i in range(1, 9)])
        for (actor, number, body), row in zip(layers, rows):
            with self.subTest(row[1]):
                self.assertIn(f'<span class="layer-num">0{number} / 08</span>', body)
                text = re.sub(r"</?code>", "", body)
                self.assertIn(f'<span data-lang="ja">{row[1]}</span>', body)  # the name
                self.assertIn(f'<span data-lang="ja">{row[2].replace("`", "")}</span>', text)  # the line
                self.assertIn(f'<span data-lang="en">{row[3].replace("`", "")}</span>', text)
                self.assertEqual(actor, ACTORS[next(k for k in ACTORS if row[5].startswith(k))])
                self.assertEqual(body.count('<span class="layer-line">'), 2)
                self.assertTrue(re.search(r'src="assets/media/layers/' + number + r'-[\w-]+-light\.png"', body))
                self.assertTrue(re.search(r'src="assets/media/layers/' + number + r'-[\w-]+-dark\.png"', body))
        # only the review layer carries the needs changes -> pass mark
        self.assertEqual(self.html.count('class="verdict-mark"'), 1)
        self.assertIn('data-layer="5"', self.html.split('class="verdict-mark"')[0].rsplit("<li ", 1)[1])

    def test_english_comes_first_and_both_languages_are_there(self):
        self.assertTrue(self.html.startswith('<!doctype html>\n<html lang="en">'))
        self.assertIn("stored(LANG_KEY) === 'ja' ? 'ja' : 'en'", read("site.js"))
        # every English span is followed at once by its Japanese one, and there is no other Japanese span
        pairs = re.findall(r'<span data-lang="en">(?:(?!<span).)*?</span>(<span data-lang="ja">)?', self.html, re.S)
        self.assertEqual(len(pairs), self.html.count('data-lang="en"'))
        self.assertNotIn("", pairs)
        self.assertEqual(self.html.count('data-lang="ja"'), len(pairs))
        for tag, attrs in self.page.tags:
            for attr in ("alt", "aria-label", "title"):
                if attr in attrs:
                    with self.subTest(f"<{tag} {attr}={attrs[attr]}>"):
                        self.assertIn(f"data-ja-{attr}", attrs)

    def test_no_private_name_of_the_owner(self):
        self.assertTrue(PRIVATE.search("jyoka/tasks#12") and PRIVATE.search("me@example.com"))
        self.assertIsNone(PRIVATE.search("https://github.com/jyoka/task-hub/blob/main/README.md"))
        for name in ("index.html", "llms.txt", "README.md", "site.css", "site.js", "favicon.svg"):
            with self.subTest(name):
                lines = read(name).splitlines()
                self.assertEqual([f"{i}: {line}" for i, line in enumerate(lines, 1) if PRIVATE.search(line)], [])


if __name__ == "__main__":
    unittest.main()
