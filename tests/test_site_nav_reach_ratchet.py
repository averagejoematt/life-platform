"""tests/test_site_nav_reach_ratchet.py — the page-reach ratchet (#4182, ruling vi).

91 reader pages exist; 39 were reachable from "/" by static <a href> links at landing, 25
since the panel's reach-set ruling the same day (#4182). A
newcomer meets the reachable set, not the served set, and the site was overwhelming because
that set grew one page at a time with no counter. This is the counter: the statically
reachable count may only go down from ledgers/site_vocabulary_residue.py::NAV_REACH_CEILING,
and lowering that number is how the owner's cap is set. Unlisted pages keep
their URLs — served-but-unlinked is the sanctioned state (/method/state/ already lives there).

Static reach only (see tests/site_text.py's stated limit): links evidence.js injects at
runtime are not counted, so this ratchet is a floor on the nav, not a census of every path.

#4588 (the front-page cut-over, owner ruling 2026-10-18): the kit footer links the footnote
appendix, which lists every off-path page. The appendix is a footnote, not navigation, so the
walk treats the appendix and the pages it lists as sinks (`site_text.appendix_sinks`): not
counted, not walked. What is still counted through them is honest reach — `/subscribe/` keeps
its v5 chrome, so its menu walks the v5 doors (`/cockpit/`, `/data/`, `/coaching/`,
`/protocols/`, `/method/`, `/story/build/`) and those count: 17 on the rebuilt rehearsal, 18 on
the 2026-10-23 refresh (main pointed the v8 coaches page at the kit call list), the
new ceiling. Re-pouring `/subscribe/` on the kit would take that to ~10, but it is a new screen
and the epic's rule 4 builds nothing beneath a screen the owner has not seen.
"""

from __future__ import annotations

from ledgers.site_vocabulary_residue import NAV_REACH_CEILING
from tests import site_text


def test_static_reach_only_ratchets_down():
    reach = site_text.static_reach(sinks=site_text.appendix_sinks())
    assert len(reach) <= NAV_REACH_CEILING, (
        f"{len(reach)} reader pages are now reachable from / by static links (ceiling {NAV_REACH_CEILING}). "
        f"A new page must be unlisted (served, not linked) or the ceiling lowered elsewhere first. "
        f"Reachable: {sorted(site_text.page_url(p) for p in reach)}"
    )


def test_reach_census_is_not_vacuous():
    # #4588: the kit front page's own static links are the preview paths (data-ck-base="/next/v8/"),
    # so the doors a reader reaches from / are the four kit doors there plus the follow page.
    reach = site_text.static_reach(sinks=site_text.appendix_sinks())
    assert "site/index.html" in reach
    assert len(reach) >= 6, "home + the kit doors must at least be reachable — the crawler is blind"
    for door in (
        "site/next/v8/start/index.html",
        "site/next/v8/story/index.html",
        "site/next/v8/coaches/index.html",
        "site/next/v8/built/index.html",
        "site/subscribe/index.html",
    ):
        assert door in reach, door
    assert "site/next/v8/appendix/index.html" not in reach, "the appendix is a footnote, not navigation (ruling 2026-10-18)"


def test_the_appendix_sinks_are_real_and_change_the_count():
    """The control: the sinks are served pages, and taking them out of the walk is what the
    ruling does — a walk without them reaches far more (the appendix lists every off-path page)."""
    sinks = site_text.appendix_sinks()
    assert site_text.APPENDIX_NODE in sinks and len(sinks) > 50
    assert len(site_text.static_reach()) > len(site_text.static_reach(sinks=sinks)) + 50
