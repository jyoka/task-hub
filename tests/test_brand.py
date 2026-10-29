"""The messaging and the look (docs/brand.md) agree with the READMEs, the banners, and assets/brand/tokens.css.

- The one sentence is the same, word for word, in the README's bold line, docs/brand.md, and both banners.
- Every meaning color in tokens.css has a contrast ratio of 4.5 or more against the page and the panel, in light
  and dark (WCAG 2 relative luminance). `python3 tests/test_brand.py --table` prints the measured ratios.
- tokens.css and the banners load nothing from outside; the READMEs name none of the owner's private boards.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "assets" / "brand"
JA = "Ready に移した GitHub Project のカードを、手元のエージェントがレビュー済みの PR にする。"
EN = "Your local coding agents turn each GitHub Project card you move to Ready into a reviewed PR."
BANNERS = ("banner-dark.svg", "banner-light.svg")
# the colors that carry meaning; each is read as text or a mark on the page and on a panel
MEANING = ("text", "muted", "accent", "cyan", "violet", "ok", "warn", "error")
GROUNDS = ("bg", "panel")
DARK = (':root[data-theme="dark"]', ':root:not([data-theme="light"])')


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

    def test_the_readmes_name_no_private_board_or_work(self):
        """docs/brand.md section 7: the owner's real board, private repositories, and work names stay out."""
        private = re.compile(r"jyoka/(tasks|aica|2\b|3\b|task-sandbox)|aica|AIprogramming|ai-CA_RA", re.I)
        for name in ("README.md", "README.ja.md"):
            with self.subTest(name):
                lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
                self.assertEqual([f"{i}: {line}" for i, line in enumerate(lines, 1) if private.search(line)], [])

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


if __name__ == "__main__":
    if "--table" in sys.argv:
        print(table())
    else:
        unittest.main()
