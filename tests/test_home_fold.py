"""#407 — home teaches the loop in one screen; the constellation gets a scale.

Source-level pins (the geometric fold check ran via the local Playwright
harness pre-merge: teaser bottom at y=710 on a 1440x900 viewport, y=509 on
390x844 — both in-fold; verified again with live screenshots post-deploy).
"""

import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = open(os.path.join(_REPO, "site/index.html")).read()


def test_loop_teaser_sits_inside_the_hero_copy():
    """The teaser must be part of the hero (above the fold), not the below-fold
    arc — and it must come BEFORE the arc anchor in document order."""
    assert 'class="hero-loop label"' in HOME
    assert HOME.find("hero-loop") < HOME.find('id="arc"')
    # Directly under the claim, not appended after the CTA at the column's foot.
    assert HOME.find("hero-loop") < HOME.find("hero-elena")


def test_teaser_names_all_four_doors_in_loop_order():
    teaser = HOME[HOME.find("hero-loop") : HOME.find("</p>", HOME.find("hero-loop"))]
    order = [m for m in re.findall(r'href="/(data|coaching|protocols|story)/"', teaser)]
    assert order == ["data", "coaching", "protocols", "story"]
    assert "↻" in teaser  # it's a loop, not a line


def test_full_loop_diagram_not_regressed():
    """The below-fold diagram (with the role descriptions) stays — the teaser
    supplements it; mobile sequencing is untouched."""
    assert HOME.count('class="loop-node"') == 4
    assert "The levers — what gets changed to move the data." in HOME


def test_constellation_caption_carries_the_scale():
    cap = HOME[HOME.find("constellation-desc") : HOME.find("</figcaption>")]
    assert "out of 100" in cap
    assert "not a broken one" in cap  # low reads early/low, never alarming
    assert "const-legend" in cap  # the at-a-glance low→high dot legend
