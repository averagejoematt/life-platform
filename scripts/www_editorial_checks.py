#!/usr/bin/env python3
"""scripts/www_editorial_checks.py — the editorial release's three build checks (owner authorisation, review 14, 2026-11-24).

Run by ``scripts/check_www_build.py::scan`` on every build (the fixture build in CI, the LIVE build the deploy scans), each
with a self-test that plants the failure it exists to catch (``self_test``, run before the scan grades anything):

  * ``feature_fingerprint`` — an editorial feature's page carries its approved text EXACTLY. The text is rebuilt from the
    built page with the Chronicle edition verifier's own pieces (``content.chapter_editions``: ``_norm`` for each block's
    words, ``prose_blocks(render_html(text))`` as the approved block list, ``_blocks_problems`` to compare, ``text_sha256``
    for the bytes) and must hash to the SHA-256 pinned in ``www/src/features/features.json``, which must also be the hash
    of the committed text file. The only presentation removed is the page's own: a link around a site address whose words
    ARE that address, and each block's element standing for its markdown marker (# / ## / ### / - / 1.). The
    first-publication day is chrome, outside the text, and must be the one features.json records.
  * ``first_person_pin`` — the homepage headline and opening are the owner's own first-person words, authorised exactly:
    static text, hashed as built. Any change, a variable, a computed number or markup inside them fails.
  * ``progress_agreement`` — "What happens next" and the homepage read ONE computation (www/src/lib/editorial.js
    progress): the data line, the "where the experiment stands" body figure and both "What happens next" blocks must
    carry the same pounds figure.

Pure: reads files only. No network, no clock.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import sys
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))
from content import chapter_editions as CE  # noqa: E402 — the Chronicle edition verifier's pieces, reused (not forked)

FEATURES_DIR = os.path.join(REPO, "www", "src", "features")
FEATURES_JSON = os.path.join(FEATURES_DIR, "features.json")

#: The owner's authorised first-person words on the homepage (review 14, 2026-11-24), as SHA-256 of their UTF-8 bytes.
#: Headline: "I lost 115 pounds once. I regained it all, and more."
#: Opening: "I’m Matt. British, in Seattle. On 6 September 2026 I weighed 327.3 pounds and started again, by my own count
#: ‘the 15th or 16th reset in a few months’. This time a team of AI coaches is part of it. I can’t yet say whether the
#: coaches are helping." (curly apostrophes and single curly quotes, as authorised)
FIRST_PERSON_SHA256 = {
    "headline": "d70fe3520c5b59b075d0f9402c67198cf68a179ef25f99c921666ed7a94c6e49",
    "opening": "af2d603b59981d6bec8ec7ecc5329f6e323b33487880f8941492a4b4db10215f",
}

_ANCHOR = re.compile(r"<a\b([^>]*)>([\s\S]*?)</a>", re.IGNORECASE)
_HREF = re.compile(r'\bhref="([^"]*)"')
_ADDRESS = re.compile(r"^/(?:story|data|system)/[A-Za-z0-9_\-/]*/$")


def is_site_build(dist: str) -> bool:
    """A real v9 build (astro writes its bundle to _astro/ on every build); a hand-made test dist of a page or two is
    not one, and the three checks below hold real builds only."""
    return os.path.isdir(os.path.join(dist, "_astro"))


def load_features(path: str = FEATURES_JSON) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(json.load(fh).get("features") or [])


def feature_text(feature: dict, features_dir: str = FEATURES_DIR) -> str:
    with open(os.path.join(features_dir, feature["text_file"]), "rb") as fh:
        return fh.read().decode("utf-8")


def _region(page: str, fid: str) -> str | None:
    m = re.search(rf'<div data-published-body data-feature-text="{re.escape(fid)}">([\s\S]*)</div></article>', page or "")
    return m.group(1) if m else None


def _unlink(region: str, phrases: dict | None = None) -> tuple[str, list[str]]:
    """The region with each permitted link unwrapped (its words kept), and a problem for any other link. Permitted: an
    address linking to itself, or a phrase features.json declares under `links` linking to its declared page."""
    problems = []
    phrases = phrases or {}

    def one(m: re.Match) -> str:
        words = html_lib.unescape(m.group(2))
        href = _HREF.search(m.group(1))
        target = html_lib.unescape(href.group(1)) if href else ""
        to_self = _ADDRESS.match(words) and target.endswith(words)
        declared = words in phrases and target.endswith(phrases[words])
        if "<" in m.group(2) or not href or not (to_self or declared):
            problems.append(f"a link inside the text is neither an address linking to itself nor a declared phrase: {words[:60]!r}")
        return m.group(2)

    return _ANCHOR.sub(one, region), problems


class _Blocks(HTMLParser):
    """The text's blocks back from the page: h1 → "# ", h2 → "## ", summary → "### ", p → as is, li → "- " / "N. "."""

    KINDS = ("h1", "h2", "summary", "p", "li")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[tuple[str, str, int]] = []  # (marker, raw inner html, list id)
        self.cur: list | None = None
        self.lists: list[list] = []  # [kind, counter, id]
        self.n_lists = 0
        self.nested = False

    def handle_starttag(self, tag, attrs):
        if self.cur is not None:
            self.nested = True
            self.cur[1] += self.get_starttag_text() or ""
            return
        if tag in ("ul", "ol"):
            self.n_lists += 1
            self.lists.append([tag, 0, self.n_lists])
        elif tag in self.KINDS:
            marker = {"h1": "# ", "h2": "## ", "summary": "### ", "p": ""}.get(tag)
            if tag == "li":
                lst = self.lists[-1] if self.lists else None
                if lst is None:
                    marker, lid = "?? ", 0
                else:
                    lst[1] += 1
                    marker, lid = ("- " if lst[0] == "ul" else f"{lst[1]}. "), lst[2]
            else:
                lid = 0
            self.cur = [marker, "", lid, tag]

    def handle_endtag(self, tag):
        if self.cur is not None and tag == self.cur[3]:
            self.blocks.append((self.cur[0], self.cur[1], self.cur[2]))
            self.cur = None
        elif self.cur is not None:
            self.cur[1] += f"</{tag}>"
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()

    def handle_data(self, data):
        if self.cur is not None:
            self.cur[1] += data

    def handle_entityref(self, name):
        if self.cur is not None:
            self.cur[1] += f"&{name};"

    def handle_charref(self, name):
        if self.cur is not None:
            self.cur[1] += f"&#{name};"


def rebuild(region: str, phrases: dict | None = None) -> tuple[str | None, list[str], list[str]]:
    """(the rebuilt text, its blocks one per line as the verifier models them, problems) from a page's feature region."""
    plain, problems = _unlink(region, phrases)
    p = _Blocks()
    p.feed(plain)
    if p.nested:
        problems.append("the text's blocks hold markup other than the permitted links")
    lines = [f"{m}{CE._norm(inner)}" for m, inner, _ in p.blocks]
    out = ""
    for i, (m, _inner, lid) in enumerate(p.blocks):
        if i:
            out += "\n" if lid and lid == p.blocks[i - 1][2] else "\n\n"
        out += lines[i]
    return (out if p.blocks else None), lines, problems


def feature_fingerprint(dist: str, features: list[dict] | None = None, features_dir: str = FEATURES_DIR) -> list[str]:
    if not is_site_build(dist):
        return []
    out = []
    for f in load_features() if features is None else features:
        fid, sha = f.get("id"), f.get("sha256")
        try:
            approved = feature_text(f, features_dir)
        except OSError as exc:
            out.append(f"feature {fid}: its text file cannot be read ({exc})")
            continue
        if CE.text_sha256(approved) != sha:
            out.append(f"feature {fid}: the committed text hashes to {CE.text_sha256(approved)}, not the pinned {sha}")
        rel = f.get("path", "").strip("/") + "/index.html"
        try:
            page = open(os.path.join(dist, rel), encoding="utf-8").read()
        except OSError:
            out.append(f"feature {fid}: {rel} was not built")
            continue
        region = _region(page, fid)
        if region is None:
            out.append(f"{rel}: no feature text region")
            continue
        text, lines, problems = rebuild(region, f.get("links") or {})
        out += [f"{rel}: {x}" for x in problems]
        want = CE.prose_blocks(CE.render_html(approved))
        out += [f"{rel}: {x}" for x in CE._blocks_problems(lines, want, None)]
        if text is None or CE.text_sha256(text) != sha:
            out.append(f"{rel}: the text rebuilt from the page hashes to {CE.text_sha256(text or '')}, not the approved {sha}")
        # the first-publication day is chrome, outside the text, and is the recorded one
        day = f.get("first_published")
        m = re.search(r"<p[^>]*data-first-published[^>]*>([\s\S]*?)</p>", page)
        if not m or CE._norm(m.group(1)) != f"First published {_day_words(day)}":
            out.append(f"{rel}: the page does not say it was first published on {day} (features.json)")
        elif m.start() > page.find("data-feature-text"):
            out.append(f"{rel}: the first-publication line sits inside or after the text")
    return out


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _day_words(iso: str | None) -> str:
    if not iso or not re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        return "?"
    y, mo, d = (int(x) for x in iso.split("-"))
    return f"{d} {_MONTHS[mo - 1]} {y}"


def first_person_pin(dist: str, pins: dict | None = None) -> list[str]:
    if not is_site_build(dist):
        return []
    pins = FIRST_PERSON_SHA256 if pins is None else pins
    rel = "index.html"
    try:
        page = open(os.path.join(dist, rel), encoding="utf-8").read()
    except OSError:
        return [f"{rel} was not built"]
    out = []
    for key, pattern in (
        ("headline", r"<h1 data-first-person-headline>([\s\S]*?)</h1>"),
        ("opening", r'<p class="ed-opening" data-first-person>([\s\S]*?)</p>'),
    ):
        found = re.findall(pattern, page)
        if len(found) != 1:
            out.append(f"{rel}: the owner's first-person {key} appears {len(found)} times, not once")
            continue
        inner = found[0]
        if "<" in inner:
            out.append(f"{rel}: the owner's first-person {key} holds markup")
        words = html_lib.unescape(inner)
        if hashlib.sha256(words.encode("utf-8")).hexdigest() != pins[key]:
            out.append(f"{rel}: the owner's first-person {key} is not the authorised text, character for character: {words[:80]!r}")
    return out


def _attr(page: str, marker: str) -> list[str]:
    return re.findall(rf'{marker}[^>]*?\bdata-progress-below="([^"]*)"|data-progress-below="([^"]*)"[^>]*?{marker}', page)


def progress_agreement(dist: str) -> list[str]:
    """The pounds figure on the homepage's data line, its body figure, its "What happens next" block and the path's "What
    happens next" page — one computation, one number."""
    if not is_site_build(dist):
        return []
    out = []
    seen: dict[str, str] = {}

    def read(rel):
        try:
            return open(os.path.join(dist, rel), encoding="utf-8").read()
        except OSError:
            return None

    home = read("index.html")
    whn = read(os.path.join("story", "start", "what-happens-next", "index.html"))
    if home is None or whn is None:
        return ["progress: the homepage or the What-happens-next page was not built"]
    for rel, page, marker in (
        ("index.html", home, "data-progress-line"),
        ("index.html", home, "data-what-happens-next"),
        ("story/start/what-happens-next/", whn, "data-what-happens-next"),
    ):
        vals = [a or b for a, b in _attr(page, marker)]
        if vals:
            seen[f"{rel} {marker}"] = vals[0]
    body = re.search(r'class="standing-row st-body"[\s\S]*?<b class="standing-v num[^"]*">([^<]*)</b>', home)
    if body and body.group(1).strip() not in ("—", ""):
        seen["index.html standing body"] = body.group(1).replace("lb", "").strip()
    if len(set(seen.values())) > 1:
        out.append(f"progress: the pounds figure differs across the homepage and What happens next: {seen}")
    if seen and len(seen) < 4:
        out.append(f"progress: a figure is served but not every reader of it carries the shared mark: {sorted(seen)}")
    for key, v in seen.items():
        page = whn if key.startswith("story/") else home
        if key.endswith("data-what-happens-next") and f"{v} pounds" not in CE._norm(page):
            out.append(f"progress: {key} marks {v} but its question does not say '{v} pounds'")
    return out


def self_test() -> list[str]:
    """Each check against a page planted to fail it. Returns the checks that MISSED their planted failure."""
    import tempfile

    missed = []
    text = "# A title\n\nA dateline · dated 1 January 2026\n\nThe summary of it.\n\nBy someone.\n\n## A section\n\nA paragraph naming /story/week-08/ here and her coach page too.\n\n- one\n- two\n\n## The evidence\n\nOpen these.\n\n### Sources\n\n1. first\n2. second"
    f = {
        "id": "t",
        "path": "/story/features/t/",
        "text_file": "t.txt",
        "sha256": CE.text_sha256(text),
        "first_published": "2026-01-02",
        "links": {"her coach page": "/system/coaches/sleep_coach/"},
    }

    def page(body: str, first: str = "2 January 2026") -> str:
        return f'<p class="ed-meta" data-first-published>First published {first}</p><article class="fx" data-feature="t"><div data-published-body data-feature-text="t">{body}</div></article>'

    good = (
        '<header class="fx-head"><h1>A title</h1><p class="fx-dateline">A dateline · dated 1 January 2026</p><p class="fx-dek">The summary of it.</p>'
        '<p class="fx-byline">By someone.</p></header><div class="fx-story"><h2>A section</h2><p>A paragraph naming <a href="/story/week-08/">/story/week-08/</a> here and <a href="/system/coaches/sleep_coach/">her coach page</a> too.</p>'
        '<ul><li>one</li><li>two</li></ul></div><h2 class="fx-evidence">The evidence</h2><p class="fx-ev-intro">Open these.</p>'
        '<details class="last"><summary>Sources</summary><div class="fx-body"><ol><li>first</li><li>second</li></ol></div></details>'
    )
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "f"))
        with open(os.path.join(d, "f", "t.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)

        def run(body, first="2 January 2026"):
            os.makedirs(os.path.join(d, "dist", "story", "features", "t"), exist_ok=True)
            os.makedirs(os.path.join(d, "dist", "_astro"), exist_ok=True)
            with open(os.path.join(d, "dist", "story", "features", "t", "index.html"), "w", encoding="utf-8") as fh:
                fh.write(page(body, first))
            return feature_fingerprint(os.path.join(d, "dist"), [f], os.path.join(d, "f"))

        if run(good):
            missed.append(f"feature_fingerprint refused the exact text: {run(good)}")
        for name, bad in (
            ("one changed character", good.replace("The summary of it.", "The summary of it!")),
            ("a dropped block", good.replace("<li>two</li>", "")),
            ("a heading level changed", good.replace("<h2>A section</h2>", "<p>A section</p>")),
            ("a link whose words are not its address", good.replace('">/story/week-08/</a>', '">chapter five</a>')),
            ("an added word inside the text", good.replace("<li>one</li>", "<li>one <b>new</b></li>")),
            ("a declared phrase linking elsewhere", good.replace('href="/system/coaches/sleep_coach/"', 'href="/system/coaches/webb/"')),
            (
                "an undeclared phrase link",
                good.replace("<p>A paragraph naming", '<p><a href="/story/">A paragraph</a> naming'),
            ),
        ):
            if not run(bad):
                missed.append(f"feature_fingerprint missed {name}")
        if not run(good, first="3 January 2026"):
            missed.append("feature_fingerprint missed a wrong first-publication day")
        # the first-person pin
        os.makedirs(os.path.join(d, "home", "_astro"), exist_ok=True)
        pins = {"headline": hashlib.sha256(b"Words.").hexdigest(), "opening": hashlib.sha256("I’m here.".encode()).hexdigest()}

        def home(h, o):
            with open(os.path.join(d, "home", "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f'<h1 data-first-person-headline>{h}</h1><p class="ed-opening" data-first-person>{o}</p>')
            return first_person_pin(os.path.join(d, "home"), pins)

        if home("Words.", "I’m here."):
            missed.append("first_person_pin refused the authorised words")
        for name, h, o in (
            ("a straight apostrophe", "Words.", "I'm here."),
            ("a changed number", "Words!", "I’m here."),
            ("markup inside", "Words.", "I’m <b>here</b>."),
        ):
            if not home(h, o):
                missed.append(f"first_person_pin missed {name}")
        # progress agreement
        os.makedirs(os.path.join(d, "p", "story", "start", "what-happens-next"), exist_ok=True)
        os.makedirs(os.path.join(d, "p", "_astro"), exist_ok=True)

        def prog(a, b, c, body):
            with open(os.path.join(d, "p", "index.html"), "w", encoding="utf-8") as fh:
                fh.write(
                    f'<p class="ed-dataline" data-progress-line data-progress-below="{a}">x</p><li class="standing-row st-body"><b class="standing-v num ">{body} lb</b></li>'
                    f'<div class="ed-narrow" data-what-happens-next data-progress-below="{b}"><p>He is {b} pounds lighter</p></div>'
                )
            with open(os.path.join(d, "p", "story", "start", "what-happens-next", "index.html"), "w", encoding="utf-8") as fh:
                fh.write(f'<div class="ed-narrow" data-what-happens-next data-progress-below="{c}"><p>He is {c} pounds lighter</p></div>')
            return progress_agreement(os.path.join(d, "p"))

        if prog("42.1", "42.1", "42.1", "42.1"):
            missed.append(f"progress_agreement refused one shared figure: {prog('42.1', '42.1', '42.1', '42.1')}")
        if not prog("42.1", "42.1", "42.8", "42.1"):
            missed.append("progress_agreement missed the path page disagreeing")
        if not prog("42.1", "42.1", "42.1", "42.8"):
            missed.append("progress_agreement missed the body figure disagreeing")
        # a hand-made dist that is not a build is not graded; a build missing the feature page is
        if feature_fingerprint(os.path.join(d, "home"), [f], os.path.join(d, "f")) == []:
            missed.append("feature_fingerprint passed a build with no feature page")
    return missed


if __name__ == "__main__":
    print(self_test() or "self-test: every planted failure caught")
