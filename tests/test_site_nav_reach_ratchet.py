"""tests/test_site_nav_reach_ratchet.py — the page-reach ratchet (#4182, ruling vi).

91 reader pages exist; 39 are reachable from "/" by static <a href> links (2026-09-26). A
newcomer meets the reachable set, not the served set, and the site was overwhelming because
that set grew one page at a time with no counter. This is the counter: the statically
reachable count may only go down from tests/site_vocabulary_residue.py::NAV_REACH_CEILING,
and lowering that number is how the owner's cap (24 proposed) is set. Unlisted pages keep
their URLs — served-but-unlinked is the sanctioned state (/method/state/ already lives there).

Static reach only (see tests/site_text.py's stated limit): links evidence.js injects at
runtime are not counted, so this ratchet is a floor on the nav, not a census of every path.
"""

from __future__ import annotations

from tests import site_text
from tests.site_vocabulary_residue import NAV_REACH_CEILING


def test_static_reach_only_ratchets_down():
    reach = site_text.static_reach()
    assert len(reach) <= NAV_REACH_CEILING, (
        f"{len(reach)} reader pages are now reachable from / by static links (ceiling {NAV_REACH_CEILING}). "
        f"A new page must be unlisted (served, not linked) or the ceiling lowered elsewhere first. "
        f"Reachable: {sorted(site_text.page_url(p) for p in reach)}"
    )


def test_reach_census_is_not_vacuous():
    reach = site_text.static_reach()
    assert "site/index.html" in reach
    assert len(reach) >= 6, "home + the five doors must at least be reachable — the crawler is blind"
    for door in (
        "site/cockpit/index.html",
        "site/data/index.html",
        "site/coaching/index.html",
        "site/protocols/index.html",
        "site/story/index.html",
    ):
        assert door in reach, door
