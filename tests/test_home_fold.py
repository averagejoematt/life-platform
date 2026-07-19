"""#407 → #1469 — home teaches the loop in one screen.

#1469 (variant A, "the loop, drawn live" — Matthew's pick from rendered
screenshots, 2026-07-19): the fold's loop teacher is now the code-drawn loop
DIAL — the measuring rule bent into a ring, four door-icon stations, verbs on
the arcs, the live day counter at the hub — plus four scroll verses that light
their station in sequence. The #407 hero-loop teaser line and the below-fold
.beat-loop card row are retired (the loop is taught once, properly). The
constellation keeps its section BELOW the fold — it is a pillar-correlation
instrument, not a loop teacher.

Source-level pins (the geometric render check runs via the local Playwright
harness pre-merge at 1280 + 390; tests/visual_qa.py's manifest checks are the
live arbiter).
"""

import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = open(os.path.join(_REPO, "site/index.html")).read()


def test_loop_dial_owns_the_fold():
    """The dial (with the live day counter at its hub) sits above the arc —
    the fold teaches the loop before any other beat."""
    assert 'class="loop-dial"' in HOME
    assert HOME.find("loop-dial") < HOME.find('id="arc"')
    # The hub carries the LIVE day counter (the page's one glow — earned).
    dial = HOME[HOME.find('class="dial"') : HOME.find("</figure>", HOME.find('class="dial"'))]
    assert 'data-bind="dayNum"' in dial


def test_dial_names_all_four_stations_in_loop_order():
    """Stations appear in causal-loop order with the sprite door icons and the
    four verbs on the arcs — direction is drawn, not implied."""
    svg = HOME[HOME.find('class="loop-dial"') : HOME.find("</svg>", HOME.find('class="loop-dial"'))]
    order = re.findall(r'class="st st-(data|coaching|protocols|story)"', svg)
    assert order == ["data", "coaching", "protocols", "story"]
    for verb in ("reads", "proposes", "shifts", "narrates"):
        assert f">{verb}<" in svg
    # Door icons come from the shared sprite (§8.1) — never bespoke one-offs.
    assert svg.count('href="/assets/icons/icons.svg#i-door-') == 4


def test_verses_walk_the_loop_and_close_it():
    """The four verses follow loop order, each links its door, and the close
    verse returns to station 01 (the loop closes) with the cockpit CTA."""
    stations = re.findall(r'<article class="verse[^"]*" data-station="([a-z]+)"', HOME)
    assert stations == ["data", "coaching", "protocols", "story", "data"]
    verses = HOME[HOME.find('class="verses"') : HOME.find('class="scroll-rule"')]
    for door in ("/data/", "/coaching/", "/protocols/", "/story/"):
        assert f'href="{door}"' in verses
    close = verses[verses.find("verse-close") :]
    assert 'href="/cockpit/"' in close  # the loop-forward CTA
    # #949: the start weight binds to the live baseline — never a hand-coded literal.
    assert 'data-bind="hero-start"' in close


def test_loop_taught_once_teaser_and_card_row_retired():
    """#1469: the loop is taught by the dial alone — the #407 hero-loop teaser
    line and the .beat-loop card row are gone, not duplicated."""
    assert 'class="hero-loop label"' not in HOME
    assert 'class="loop-node"' not in HOME


def test_constellation_kept_below_the_fold():
    """The constellation survives as its own beat AFTER the dial — same markup,
    so story.js drawConstellation and the qa_manifest visual checks hold."""
    assert HOME.find('class="loop-dial"') < HOME.find('class="constellation"')
    assert 'class="beat beat-constellation"' in HOME


def test_constellation_caption_carries_the_scale():
    cap = HOME[HOME.find("constellation-desc") : HOME.find("</figcaption>")]
    assert "out of 100" in cap
    assert "not broken" in cap  # #590: "a young experiment starts low, not broken" — low reads early, never alarming
    assert "const-legend" in cap  # the at-a-glance low→high dot legend
