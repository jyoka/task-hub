"""The messaging and the look (docs/brand.md) agree with the READMEs, the banners, and assets/brand/tokens.css.

- The one sentence is the same, word for word, in the README's bold line, docs/brand.md, and both banners.
- Every meaning color in tokens.css has a contrast ratio of 4.5 or more against the page and the panel, in light
  and dark (WCAG 2 relative luminance). `python3 tests/test_brand.py --table` prints the measured ratios.
- tokens.css and the banners load nothing from outside; the READMEs and docs name none of the owner's private
  boards, repositories, or work.
- The READMEs follow CONTRIBUTING.md's "README の構成": the headings in its order, the banner above the title, the
  moving picture under the sentence, the Features table of 4 pictures that link to docs, alt texts, and the length.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "assets" / "brand"
JA = "AI に任せて、離れていい。確かめてから届くから。"
EN = "Hand work to AI agents and walk away. Nothing reaches you unchecked."
BANNERS = ("banner-dark.svg", "banner-light.svg")
READMES = {"README.md": ("English | [日本語](README.ja.md)", "## Features"),
           "README.ja.md": ("[English](README.md) | 日本語", "## 特長")}
# CONTRIBUTING.md: the lines a README may have, not counting the pictures' HTML
MOST_LINES = 200
# the colors that carry meaning; each is read as text or a mark on the page and on a panel
MEANING = ("text", "muted", "accent", "cyan", "violet", "ok", "warn", "error")
GROUNDS = ("bg", "panel")
DARK = (':root[data-theme="dark"]', ':root:not([data-theme="light"])')
# the owner's private names (docs/brand.md section 7): real boards (jyoka/2, jyoka/3), private repositories, links to
# their Issues (tasks#81), examples under the owner's account (jyoka/app), and the names of the owner's work
PRIVATE = re.compile(r"jyoka/(?!task-hub\b|workenv_setting\b)[\w.-]+|(?<![\w/])tasks#\d"
                     r"|(?<![a-z])aica|AIprogramming|ai-CA_RA|求人|LINE のトーク", re.I)


def block(css, selector):
    """The custom properties set in `selector { ... }`, as {name: value}."""
    at = css.index(selector + " {")
    body = css[at:css.index("}", at)]
    return dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", body))


def slug(heading):
    """GitHub's link name for a heading: lower case, punctuation dropped, spaces as hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.replace("`", "").strip().lower()).replace(" ", "-")


def themes():
    css = (BRAND / "tokens.css").read_text(encoding="utf-8")
    light = block(css, ":root")
    return {"light": light, "dark": {**light, **block(css, DARK[0])}}


def luminance(color):
    rgb = [int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pairs(theme):
    """(foreground, background) pairs that must reach 4.5: each meaning color on the page, on a panel, and on its
    own tint (a label inside a mark), and the text on the accent color (a button)."""
    out = [(fg, bg) for fg in MEANING for bg in GROUNDS]
    out += [(fg, f"{fg}-bg") for fg in MEANING if f"{fg}-bg" in theme]
    return out + [("on-accent", "accent")]


def table():
    rows = ["| 字 / 印 | 地 | ライト | ダーク |", "|---|---|---|---|"]
    t = themes()
    for fg, bg in pairs(t["light"]):
        rows.append(f"| `--{fg}` | `--{bg}` | "
                    + " | ".join(f"{contrast(t[k][fg], t[k][bg]):.2f}" for k in ("light", "dark")) + " |")
    return "\n".join(rows)


def readme(name):
    return (ROOT / name).read_text(encoding="utf-8")


def section(text, heading):
    return text.split(heading + "\n", 1)[1].split("\n## ", 1)[0]


def pictures(text):
    """Each <picture> as (its sources' srcset, the <img> alt, the <img> src)."""
    out = []
    for body in re.findall(r"(?s)<picture>(.*?)</picture>", text):
        img = re.search(r'<img [^>]*alt="([^"]*)"[^>]*src="([^"]*)"', body)
        out.append((re.findall(r'srcset="([^"]*)"', body), img[1], img[2]))
    return out


class BrandTest(unittest.TestCase):

    def test_the_one_sentence_is_the_same_everywhere(self):
        self.assertIn(f"**{EN}**", (ROOT / "README.md").read_text(encoding="utf-8").splitlines())
        self.assertIn(f"**{JA}**", (ROOT / "README.ja.md").read_text(encoding="utf-8").splitlines())
        brand = (ROOT / "docs" / "brand.md").read_text(encoding="utf-8")
        self.assertIn(f"**{JA}**", brand)
        self.assertIn(f"**{EN}**", brand)
        for name in BANNERS:
            with self.subTest(name):
                svg = (BRAND / name).read_text(encoding="utf-8")
                self.assertIn(f'<desc id="desc">{JA} {EN}</desc>', svg)
                self.assertIn(">task-hub</text>", svg)

    def test_meaning_colors_reach_4_5_against_their_grounds(self):
        for name, theme in themes().items():
            for fg, bg in pairs(theme):
                with self.subTest(f"{name} --{fg} on --{bg}"):
                    self.assertGreaterEqual(contrast(theme[fg], theme[bg]), 4.5)

    def test_dark_follows_the_os_and_data_theme_with_the_same_values(self):
        css = (BRAND / "tokens.css").read_text(encoding="utf-8")
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        first, second = (block(css, s) for s in DARK)
        self.assertEqual(first, second)
        light = block(css, ":root")
        colors = {k for k, v in light.items() if v.startswith("#")}
        self.assertEqual(colors - set(first), set())  # every light color has a dark value

    def test_the_banners_use_the_token_colors(self):
        t = themes()
        for name, theme in (("banner-dark.svg", t["dark"]), ("banner-light.svg", t["light"])):
            with self.subTest(name):
                used = set(re.findall(r'(?:fill|stroke)="(#[0-9a-f]{6})"', (BRAND / name).read_text(encoding="utf-8")))
                self.assertEqual(used - set(theme.values()), set())
                self.assertIn(f'fill="{theme["bg"]}"', (BRAND / name).read_text(encoding="utf-8"))

    def test_nothing_loads_from_outside(self):
        for name in ("tokens.css", *BANNERS):
            with self.subTest(name):
                text = (BRAND / name).read_text(encoding="utf-8").replace('xmlns="http://www.w3.org/2000/svg"', "")
                self.assertIsNone(re.search(r"https?:|@import|url\(|<script|<image|<foreignObject", text, re.I))

    def test_the_public_docs_name_no_private_board_or_work(self):
        """docs/brand.md section 7: the owner's real boards, private repositories, real Issues, and work names stay out
        of the READMEs and docs. Examples use `you/app`, `you/tasks#12`, and the like."""
        docs = sorted((ROOT / "docs").rglob("*.md"))
        self.assertGreater(len(docs), 20)
        top = ("README.md", "README.ja.md", "CONTRIBUTING.md", "SECURITY.md", "AGENTS.md")
        for path in [ROOT / name for name in top] + docs:
            with self.subTest(str(path.relative_to(ROOT))):
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual([f"{i}: {line}" for i, line in enumerate(lines, 1) if PRIVATE.search(line)], [])

    def test_the_private_names_check_finds_them(self):
        for line in ("repos = jyoka/aica", "(jyoka/tasks#81)", "tasks#47 で", "Project `jyoka/2` と", "`jyoka/3`",
                     "jyoka/task-sandbox", "ci = jyoka/app, jyoka/web", "~/AIprogramming PJ/", "求人検索と…",
                     "https://github.com/jyoka/tasks/issues/117", "LINE のトークで"):
            with self.subTest(line):
                self.assertIsNotNone(PRIVATE.search(line))
        for line in ("Issue you/tasks#12", "jyoka/task-hub", "github.com/jyoka/workenv_setting", "`#12`",
                     "owner/name#n", "you/app#114", "Jamaica"):
            with self.subTest(line):
                self.assertIsNone(PRIVATE.search(line))

    def test_the_links_in_brand_md_lead_somewhere(self):
        """Each feature card links to its docs: the file exists, and so does the heading the link names."""
        doc = ROOT / "docs" / "brand.md"
        links = re.findall(r"\]\(([^)#\s]+)(?:#([^)\s]*))?\)", doc.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len([anchor for _, anchor in links if anchor]), 8)
        for target, anchor in links:
            with self.subTest(f"{target}#{anchor}"):
                path = doc.parent / target
                self.assertTrue(path.exists())
                if anchor:
                    self.assertIn(anchor, [slug(h) for h in re.findall(r"(?m)^#+ (.*)$", path.read_text(encoding="utf-8"))])


    def test_the_readmes_keep_the_headings_of_contributing_md(self):
        rule = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split("### README の構成", 1)[1]
        rows = re.findall(r"(?m)^\| \d+ \| `(#+ [^`]+)`(?: / `(#+ [^`]+)`)? \|", rule)
        self.assertEqual(rows[0][0], "# task-hub")
        for name, column in (("README.ja.md", 0), ("README.md", 1)):
            with self.subTest(name):
                want = [row[column] or row[0] for row in rows]
                text = re.sub(r"(?ms)^```.*?^```", "", readme(name))  # a `# comment` in a code block is no heading
                self.assertEqual(re.findall(r"(?m)^#{1,2} .*$", text), want)

    def test_the_readmes_open_with_the_banner_the_sentence_and_the_moving_picture(self):
        for name, sentence in (("README.md", EN), ("README.ja.md", JA)):
            with self.subTest(name):
                text = readme(name)
                lines = [line for line in text.splitlines() if line.strip()]
                self.assertEqual(lines[0], "<picture>")  # the banner comes first, above the title
                banner, flow = pictures(text)[:2]
                self.assertEqual(banner[0], ["assets/brand/banner-dark.svg"])
                self.assertEqual(banner[2], "assets/brand/banner-light.svg")
                self.assertIn('<source media="(prefers-color-scheme: dark)" srcset="assets/brand/banner-dark.svg">', text)
                at = lines.index("# task-hub")
                self.assertEqual(lines[at + 1:at + 4], [READMES[name][0], f"**{sentence}**", "<picture>"])
                # the moving picture stops for prefers-reduced-motion, and AVIF falls back to GIF
                self.assertEqual(flow[0], ["assets/media/list-dark.png", "assets/media/list-light.png",
                                           "assets/media/flow.avif"])
                self.assertEqual(flow[2], "assets/media/flow.gif")
                self.assertIn('media="(prefers-reduced-motion: reduce)"', text)
                # the rest of the top stays: the landing page (site/README.md), the CI badge, the two decisions,
                # and the way in for Kiro IDE
                top = text.split("\n## ", 1)[0]
                for kept in ("](https://jyoka.github.io/task-hub/", "actions/workflows/windows.yml/badge.svg",
                             "docs/kiro-quickstart.md", "docs/windows-quickstart.md"):
                    self.assertIn(kept, top)
                self.assertEqual(len(re.findall(r"(?m)^- \*\*", top)), 2)

    def test_the_features_table_shows_4_pictures_that_link_to_docs(self):
        tables = {}
        for name, (_, heading) in READMES.items():
            with self.subTest(name):
                features = section(readme(name), heading)
                table = re.search(r"(?s)<table>(.*?)</table>", features)[1]
                cells = re.findall(r"(?s)<td [^>]*>(.*?)</td>", table)
                self.assertEqual(len(cells), 4)
                self.assertEqual(len(re.findall(r"<tr>", table)), 2)  # 2 columns
                shown = []
                for cell in cells:
                    href = re.search(r'<a href="([^"#]+)#([^"]+)"><picture>', cell)
                    self.assertIsNotNone(href, cell)
                    path = ROOT / href[1]
                    headings = re.findall(r"(?m)^#+ (.*)$", path.read_text(encoding="utf-8"))
                    self.assertIn(href[2], [slug(h) for h in headings])
                    (srcset,), _, src = pictures(cell)[0]
                    self.assertEqual(srcset, src.replace("-light.png", "-dark.png"))
                    self.assertRegex(cell, r"</a><br>\s*<b>[^<]+</b><br>\s*\S")  # a bold name, then one line
                    shown.append(src)
                tables[name] = shown
                self.assertIn("(docs/media.md)", features.split("</table>", 1)[1].split("\n- ", 1)[0])
                self.assertLessEqual(len(re.findall(r"(?m)^- ", features)), 7)
        if len(tables) == 2:  # both READMEs show the same pictures in the same order
            self.assertEqual(tables["README.md"], tables["README.ja.md"])

    def test_every_picture_in_the_readmes_has_a_file_and_an_alt_that_says_what_it_shows(self):
        for name in READMES:
            with self.subTest(name):
                found = pictures(readme(name))
                self.assertGreaterEqual(len(found), 6)
                for srcsets, alt, src in found:
                    for path in (*srcsets, src):
                        self.assertTrue((ROOT / path).is_file(), path)
                    self.assertGreaterEqual(len(alt), 60, alt)  # a sentence, not a file name
                    self.assertNotIn(Path(src).stem, alt)

    def test_the_readmes_stay_short(self):
        for name in READMES:
            with self.subTest(name):
                prose = re.sub(r"(?s)<(picture|table)>.*?</\1>", "", readme(name))
                self.assertLessEqual(len(prose.splitlines()), MOST_LINES)


if __name__ == "__main__":
    if "--table" in sys.argv:
        print(table())
    else:
        unittest.main()
