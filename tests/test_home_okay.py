"""#789 — the friends/family "Is he okay this week?" surface.

Source-level pins (same style as test_home_fold.py): the plain-language weekly
status beat exists high on the home page, ships a no-JS fallback that points to
the live cockpit, and story.js renders it DETERMINISTICALLY from data already on
the page — with an honest absent state and an "as of" stamp (ADR-104/105). No new
fetch, no AI generation, no lambda write is introduced.
"""

import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = open(os.path.join(_REPO, "site/index.html")).read()
STORY_JS = open(os.path.join(_REPO, "site/assets/js/story.js")).read()
STORY_CSS = open(os.path.join(_REPO, "site/assets/css/story.css")).read()


def test_okay_beat_present_and_high_on_the_page():
    """The section exists inside the arc and comes BEFORE the loop/dispatches
    beats — family gets their answer near the top, not buried."""
    assert 'class="beat beat-okay"' in HOME
    assert "Is he okay this week?" in HOME
    # High: before the constellation beat (#1469 — it replaced the retired
    # beat-loop card row) and before the dispatches/chronicle beat.
    assert HOME.find("beat-okay") < HOME.find("beat-constellation")
    assert HOME.find("beat-okay") < HOME.find("beat-dispatches")


def test_okay_beat_has_a_no_js_fallback_pointer():
    """No-JS readers still get a sensible line pointing at the live cockpit; JS
    replaces it with the real read."""
    section = HOME[HOME.find("beat-okay") : HOME.find("</section>", HOME.find("beat-okay"))]
    assert "okay-fallback" in section
    assert 'href="/cockpit/"' in section
    assert "data-okay" in section  # the JS mount point


def test_render_reads_existing_endpoints_no_new_fetch_or_ai():
    """renderOkay is fed the already-fetched character + journey + presence values
    (presence was already fetched for the hero quiet-stretch line; it keeps the
    chips honest during a logging stall — truth audit 2026-07-10); it must not
    open its own network call or invoke any AI path."""
    assert "function renderOkay(" in STORY_JS
    assert 'renderOkay(charV, journeyV, presence.status === "fulfilled" ? presence.value : null, pre)' in STORY_JS
    # The render function body must contain no fetch/getJSON of its own.
    start = STORY_JS.find("function renderOkay(")
    body = STORY_JS[start : STORY_JS.find("\n}\n", start)]
    assert "fetch(" not in body
    assert "getJSON(" not in body


def test_absent_data_reads_honestly_absent():
    """ADR-104: a pillar the engine flags as no-signal must render as honestly
    absent, never a faked 'steady'. The absent copy + the coverage gate exist."""
    assert "not measured this week" in STORY_JS
    assert "coverage_hold" in STORY_JS
    assert "data_coverage" in STORY_JS


def test_read_carries_an_as_of_stamp():
    """Every read is stamped with the character sheet's own as_of_date."""
    assert "as_of_date" in STORY_JS
    assert "okay-asof" in STORY_JS
    assert "as of ${esc(asOf)}" in STORY_JS


def test_styles_use_design_tokens_no_hardcoded_color():
    """The beat is styled with the tokens.css system, not bespoke hex."""
    block = STORY_CSS[STORY_CSS.find(".okay-card") : STORY_CSS.find(".beat-since {")]
    assert "var(--ember)" in block
    assert "var(--font-serif)" in block
    # No raw hex colors slipped into the new block.
    assert "#" not in block
