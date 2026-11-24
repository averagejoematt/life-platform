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

#4588 (the front-page cut-over, owner ruling 2026-10-18) made the v8 footnote appendix and the pages it
listed sinks of the walk. #6223 retired the /next/ preview — the appendix and the kit's deep pages with
it — so the v8 walk has no sinks left and reaches only what site/index.html still links to a page in the
repo. Since the v9 cut-over (#5534) the ratcheted measure is the v9 build's own census, www/reach.json,
where the v9 appendix (/system/everything-else/) is the sink.
"""

from __future__ import annotations

import json
import os

from deploy import www_owned_paths
from ledgers.site_vocabulary_residue import NAV_REACH_CEILING, NAV_REACH_CEILING_V9
from tests import site_text

REACH_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "www", "reach.json")


def v9_reach() -> dict:
    """www/reach.json — emitted by the v9 build (www/scripts/postbuild.mjs) and drift-checked against a fresh
    build by scripts/check_www_build.py, because pytest cannot run `astro build` (#5534)."""
    with open(REACH_JSON, encoding="utf-8") as f:
        return json.load(f)


def test_static_reach_only_ratchets_down():
    """#5534: which front page a reader meets follows the committed switch in www/owned_paths.json. While
    `live_at_root` is false, `/` is site/index.html (the v8 kit page) and the walk below is the measure.
    Once it is true, `/` is the v9 build's and the measure is the build's own census, www/reach.json."""
    if www_owned_paths.live_at_root():
        reach = v9_reach()
        assert reach["depth1_count"] == len(reach["depth1"]) and reach["start"] == "/"
        assert reach["depth1_count"] <= NAV_REACH_CEILING_V9, (
            f"{reach['depth1_count']} reader pages are linked from the v9 front page (ceiling {NAV_REACH_CEILING_V9}). "
            f"A new link must come off the front page or the ceiling be lowered elsewhere first. Linked: {reach['depth1']}"
        )
        return
    reach = site_text.static_reach()
    assert len(reach) <= NAV_REACH_CEILING, (
        f"{len(reach)} reader pages are now reachable from / by static links (ceiling {NAV_REACH_CEILING}). "
        f"A new page must be unlisted (served, not linked) or the ceiling lowered elsewhere first. "
        f"Reachable: {sorted(site_text.page_url(p) for p in reach)}"
    )


def test_v9_reach_census_is_committed_and_under_its_ceiling():
    """The v9 measure is held in both switch states, so the flip merge cannot red on it: the committed
    census is the fixture build's, the appendix is a sink (not in either list), and the v9 ceiling is a
    LOWERING of the v8 one (shrink-only, 18 → 11 → 10, ledgers/site_vocabulary_residue.py)."""
    reach = v9_reach()
    assert NAV_REACH_CEILING_V9 <= NAV_REACH_CEILING, "the v9 ceiling may only lower the ratchet"
    assert reach["depth1_count"] == len(reach["depth1"]) <= NAV_REACH_CEILING_V9, reach["depth1"]
    assert set(reach["depth1"]) <= set(reach["transitive"]) and "/" in reach["transitive"]
    assert "/system/everything-else/" in reach["sinks"], "the appendix is a sink by ruling (2026-10-18)"
    assert not set(reach["sinks"]) & set(reach["depth1"]) and not set(reach["sinks"]) & set(reach["transitive"])
    for door in ("/story/", "/data/", "/system/"):
        assert door in reach["depth1"], f"the masthead's {door} must be one tap from /"
    assert reach["transitive_count"] >= reach["depth1_count"] >= 6, "the census is blind — fewer pages than the masthead alone"


def test_reach_census_is_not_vacuous():
    """The walk from the v8 kit front page still sees a page: its follow door. The kit doors it used to reach were the
    /next/v8/ pages, retired in #6223 — a static link to one of them now resolves to no page in the repo (the edge 301s
    it to its successor), so the walk must not count any, and no reader page may live under site/next/ again."""
    reach = site_text.static_reach()
    assert "site/index.html" in reach and "site/subscribe/index.html" in reach, sorted(reach)
    back = sorted(p for p in site_text.reader_pages() if p.startswith("site/next/"))
    assert not back, f"a page is back under the retired preview prefix: {back}"
