"""tests/test_narrator_byline_6178.py — every byline names Elena Voss as the AI editorial narrator, the same way (#6178,
owner ruling 2026-11-22 §7).

Surfaces: the chapter page, the home page's latest-chapter card, the story index (all from ``www/src/lib/narrator.js``),
the RSS channel (``scripts/v4_build_rss.py`` and the committed ``site/rss.xml`` / ``site/feed.xml``) and the subscribe
page. Each carries ``NARRATOR_WHO`` verbatim. The owner's own approved first-person sentences are untouched, byte for
byte: the naming sits beside them, never inside. "The platform's narrator" survives only inside those sentences.

# premerge-gate: sweeps www/src for a rendered byline that still says "the platform's narrator" (a repo-shape ratchet)
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_WWW = _REPO / "www" / "src"


def _read(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8")


def _js_const(name: str) -> str:
    m = re.search(rf'export const {name} = "([^"]+)";', _read("www/src/lib/narrator.js"))
    assert m, f"narrator.js lost {name}"
    return m.group(1)


WHO = _js_const("NARRATOR_WHO")

# The owner's approved first-person lines that mention the narrator. Byte-identical, by rule: no sentence of his changes.
OWNER_LINES = {
    "www/src/pages/index.astro": "Written by the platform's narrator from the week's data; published after I approved it. The figures in it are explorable in the data room.",
    "www/src/pages/system/index.astro": "The weekly chapters are written by the platform's narrator and published after I approve them; the essay is in my voice.",
}


def test_the_disclosure_names_her_says_ai_and_says_language_model():
    assert WHO.startswith("Elena Voss, an AI editorial persona") and "language model" in WHO and "platform's data" in WHO


def test_the_v9_bylines_read_the_one_definition():
    page = _read("www/src/pages/story/[id].astro")
    assert "{CHAPTER_BYLINE}" in page and 'from "../../lib/narrator.js"' in page
    home = _read("www/src/pages/index.astro")
    assert "{NARRATOR_BYLINE}" in home and 'from "../lib/narrator.js"' in home
    index = _read("www/src/pages/story/index.astro")
    assert "{INDEX_BYLINE}" in index and 'from "../../lib/narrator.js"' in index
    src = _read("www/src/lib/narrator.js")
    for name in ("NARRATOR_BYLINE", "CHAPTER_BYLINE", "INDEX_BYLINE"):
        assert re.search(rf"export const {name} = `[^`]*\$\{{NARRATOR_(?:WHO|BYLINE)\}}", src), name
    assert "approved it" in src and "approves it" in src, "each byline says the owner approves the chapter before it publishes"


def test_the_feed_and_the_subscribe_page_carry_the_same_disclosure():
    import importlib.util

    spec = importlib.util.spec_from_file_location("v4_build_rss_6178", _REPO / "scripts" / "v4_build_rss.py")
    rss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rss)
    assert f"Written by {WHO}" in rss.DESC and "approves each chapter before it publishes" in rss.DESC
    for rel in ("site/rss.xml", "site/feed.xml"):
        assert f"Written by {WHO}" in _read(rel), rel
    sub = _read("site/subscribe/index.html")
    assert WHO in sub and "AI journalist" not in sub


def test_the_owners_first_person_lines_are_byte_identical_and_the_only_unnamed_narrator():
    for rel, line in OWNER_LINES.items():
        assert _read(rel).count(line) == 1, f"{rel}: the owner's approved sentence changed or moved"
    leftovers = []
    for p in sorted(_WWW.rglob("*")):
        if p.suffix not in (".astro", ".js", ".ts") or not p.is_file():
            continue
        rel = str(p.relative_to(_REPO))
        text = p.read_text(encoding="utf-8")
        text = text.replace(OWNER_LINES.get(rel, "\0"), "")
        for ln, line in enumerate(text.splitlines(), 1):
            if "platform's narrator" in line and not line.lstrip().startswith(("//", "*", "/*")):
                leftovers.append(f"{rel}:{ln}")
    assert leftovers == [], f"an unnamed narrator byline is still rendered: {leftovers}"


def test_no_changed_byline_surface_links_legacy():
    for rel in ("www/src/lib/narrator.js", "www/src/pages/story/index.astro", "site/subscribe/index.html"):
        assert 'href="/legacy' not in _read(rel), rel
