"""The wayfinding layer — structural guards (#1475).

`scripts/v4_wayfinding.py` renders the footer wayfinder (the loop's five stations, with
this page's station marked) and `scripts/v4_chrome.site_footer` re-pours the mega-menu on
the loop around it. These tests hold the three properties the issue actually bought:

1. **The loop is navigable from anywhere** — every page that carries the canonical footer
   carries exactly one wayfinder, verified over the real `site/` inventory rather than a
   hand-maintained list (the same idiom as the `.loop-forward` sweep in #1468).
2. **One position, one signal** — the station the wayfinder marks is the door the page's
   own doors nav marks. Nav, `.loop-forward` close and footer are keyed off one detected
   value in `v4_apply_chrome.py`, so they can never disagree about where the reader is.
3. **The footer pour is pinned** — since #4182 the mega-menu is exactly the 23 page links
   of the 25-page reach set (the pre-#1475 "removed nothing" subset pin was reversed then).

Plus the two invariants that fail SILENTLY if broken: the station cycle must stay in step
with `v4_chrome.NEXT_STATION` (otherwise the map and the close propose different next
stations on the same page), and the footer ribbon must not reuse the `.loop-ribbon` class
(its `view-transition-name` is unique per document — a second one would kill the
cross-document transition on the 81 pages carrying both, with nothing to see in CI).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

sys.path.insert(0, str(ROOT / "scripts"))
import v4_chrome  # noqa: E402
import v4_wayfinding  # noqa: E402

HREF_RE = re.compile(r'href="([^"]+)"')
CURRENT_DOOR_RE = re.compile(r'<a href="([^"]+)"[^>]*aria-current="page"')
FOOT_RE = re.compile(r'<footer class="site-foot".*?</footer>', re.DOTALL)
WAYFINDER_RE = re.compile(r'<nav class="wayfinder".*?</nav>', re.DOTALL)
HERE_STOP_RE = re.compile(r'<span class="wf-stop is-here[^"]*" data-station="([^"]+)"')

# The footer's page links since #4182 (the 2026-09-26 panel ruling: the reach set is 25,
# the footer 42 → 23 page links in five columns under the new door labels + FOLLOW). This
# REVERSES #1475's "never drop a destination" pin on purpose: the pages the pour cut
# (/data/ledger/, /coaching/team/, /story/timeline/, /story/agents/, /method/platform/, …)
# stay served at their URLs, unlinked — `tests/test_site_nav_reach_ratchet.py` holds the
# reachable count. An exact set, not a subset: adding a footer link is an IA decision
# that must move this pin and the reach ceiling together.
FOOTER_LINKS_4182 = {
    # the numbers
    "/data/physical/",
    "/data/sleep/",
    "/data/training/",
    "/data/nutrition/",
    "/data/labs/",
    # the coaches
    "/coaching/",
    "/coaching/by-coach/",
    "/coaching/scorecard/",
    "/coaching/lab-notes/",
    # what he tries
    "/protocols/",
    "/protocols/experiments/",
    # the story
    "/story/",
    "/story/journal/",
    "/story/panel/",
    "/story/attempts/",
    "/story/about/",
    # how it's built
    "/method/",
    "/story/build/",
    "/gear/",
    "/method/character/",
    # follow
    "/subscribe/",
    "/rss.xml",
    "/privacy/",
}
# The outbound follow marks (#1620) ride in FOLLOW too; they are not pages.
SOCIAL_HREFS = {href for href, _ in v4_chrome.SOCIAL_LINKS}
MENU_RE = re.compile(r'<nav class="site-foot-cols".*?</nav>', re.DOTALL)


def _non_legacy_pages():
    for path in sorted(SITE.rglob("*.html")):
        if "legacy" in path.relative_to(SITE).parts:
            continue
        yield path


# ── The registry itself ─────────────────────────────────────────────────────────


def test_stations_are_exactly_the_doors():
    """The wayfinder's stations are the five doors, in loop order — not a parallel IA."""
    assert [href for _, href, _, _ in v4_wayfinding.STATIONS] == [href for href, _, _, _ in v4_chrome.DOORS]


def test_station_cycle_matches_the_loop_forward_map():
    """The map and the close must propose the SAME next station on every page.

    `v4_chrome.NEXT_STATION` is the editorial close's map; the wayfinder derives `next`
    from the station cycle. If these drift a reader sees the ribbon tag one station
    "next" while the close argues for another, on the same screen.
    """
    for key, href, _, _ in v4_wayfinding.STATIONS:
        _, next_key = v4_wayfinding._neighbours(key)
        next_href = dict((k, h) for k, h, _, _ in v4_wayfinding.STATIONS)[next_key]
        assert (
            v4_chrome.NEXT_STATION[href][0] == next_href
        ), f"{href}: ribbon says {next_href}, loop-forward says {v4_chrome.NEXT_STATION[href][0]}"


def test_doorless_pages_are_invited_to_the_default_next_station():
    """With no door, nothing is 'here' and the cockpit is tagged — matching DEFAULT_NEXT."""
    from_key, next_key = v4_wayfinding._neighbours(None)
    assert from_key is None
    assert dict((k, h) for k, h, _, _ in v4_wayfinding.STATIONS)[next_key] == v4_chrome.DEFAULT_NEXT[0]
    html = v4_wayfinding.wayfinder(None)
    assert "is-here" not in html
    assert "start here" in html


def test_column_stations_are_the_four_causal_stages():
    """The cockpit is the loop's vantage, not a stage — it has no mega-menu column."""
    assert v4_wayfinding.COLUMN_STATIONS == tuple(k for k, _, _, _ in v4_wayfinding.STATIONS)[1:]
    keyed = [station for station, _, _ in v4_chrome.FOOTER_COLUMNS if station]
    assert keyed == list(v4_wayfinding.COLUMN_STATIONS), "the mega-menu's loop columns drifted from loop order"


# ── The rendered footer ─────────────────────────────────────────────────────────


def test_wayfinding_kept_every_footer_link():
    """The mega-menu carries exactly the 23 page links of the #4182 pour (plus the social marks)."""
    menu = MENU_RE.search(v4_chrome.site_footer()).group(0)
    hrefs = HREF_RE.findall(menu)
    pages = [h for h in hrefs if h not in SOCIAL_HREFS]
    assert len(pages) == len(set(pages)) == 23, f"the footer pour must be 23 distinct page links, got {len(pages)}: {pages}"
    assert set(pages) == FOOTER_LINKS_4182, (
        f"footer drifted from the #4182 pour — added {sorted(set(pages) - FOOTER_LINKS_4182)}, "
        f"dropped {sorted(FOOTER_LINKS_4182 - set(pages))}"
    )
    assert SOCIAL_HREFS <= set(hrefs), "the outbound follow marks (#1620) left the footer"
    headings = re.findall(r'<p class="sf-h label">([^<]+)</p>', menu)
    assert headings == ["The numbers", "The coaches", "What he tries", "The story", "How it&#x27;s built", "Follow"], headings


def test_door_labels_are_the_readers_words():
    """#4182: nav, wayfinder and loop-forward close name the doors in ONE vocabulary."""
    labels = [label for _, label, _, _ in v4_chrome.DOORS]
    assert labels == ["today", "the numbers", "the coaches", "what he tries", "the story"]
    assert [name.lower() for _, _, name, _ in v4_wayfinding.STATIONS] == labels
    for href, (_nxt, label, _hook) in v4_chrome.NEXT_STATION.items():
        assert label in labels, f"{href}: loop-forward names a door the nav doesn't ({label!r})"
    assert v4_chrome.DEFAULT_NEXT[1] == "today"
    nav = v4_chrome.doors_nav()
    for old in ("the cockpit", "the data", "the coaching", "the protocols"):
        assert f"</svg>{old}</a>" not in nav


def test_the_wayfinder_adds_the_first_footer_route_to_the_cockpit():
    """The cockpit had no footer link at all before the wayfinder — the loop's vantage
    was reachable only from the top nav. That gap is what 'navigable from anywhere' means
    concretely, so it gets its own guard rather than riding on the coverage subset."""
    assert 'href="/cockpit/"' in v4_chrome.site_footer(current_door="/story/")


def test_the_marked_station_is_not_a_link_and_its_column_is_marked():
    for key, href, _, _ in v4_wayfinding.STATIONS:
        foot = v4_chrome.site_footer(current_door=href)
        wf = WAYFINDER_RE.search(foot).group(0)
        assert HERE_STOP_RE.search(wf).group(1) == key, f"{href}: wrong station marked"
        assert '<a class="wf-stop is-here' not in wf, f"{href}: the station you're on self-links"
        if key in v4_wayfinding.COLUMN_STATIONS:
            assert f'<div class="sf-col is-here" data-station="{key}">' in foot, f"{href}: menu column not marked"
        assert foot.count("is-here") == (2 if key in v4_wayfinding.COLUMN_STATIONS else 1)


def test_the_footer_ribbon_never_reuses_the_loop_ribbon_class():
    """`view-transition-name` must be unique per document (§12b). The page-hero ribbon
    owns `loop-ribbon`; the footer's must stay `wf-ribbon` or the cross-document
    transition dies silently on every page that carries both."""
    for href in [None] + [h for _, h, _, _ in v4_wayfinding.STATIONS]:
        assert "loop-ribbon" not in v4_chrome.site_footer(current_door=href)


# ── The real page inventory ─────────────────────────────────────────────────────


def test_every_footer_page_carries_exactly_one_wayfinder():
    checked = 0
    for path in _non_legacy_pages():
        html = path.read_text(encoding="utf-8")
        if '<footer class="site-foot"' not in html:
            continue
        checked += 1
        rel = path.relative_to(SITE)
        assert html.count('<nav class="wayfinder"') == 1, f"{rel}: expected exactly one wayfinder"
        assert html.count('class="wf-ribbon"') == 1, f"{rel}: duplicate wf-ribbon — the view-transition name would collide"
    assert checked > 0, "no footer-bearing pages found — the sweep didn't run over anything"


def test_the_wayfinder_marks_the_same_station_the_doors_nav_marks():
    """One detected door drives the nav, the loop-forward close and the wayfinder."""
    checked = 0
    for path in _non_legacy_pages():
        html = path.read_text(encoding="utf-8")
        if '<nav class="doors"' not in html:
            continue
        rel = path.relative_to(SITE)
        nav_door = CURRENT_DOOR_RE.search(html)
        foot = FOOT_RE.search(html)
        assert foot, f"{rel}: doors-nav page with no canonical footer"
        marked = HERE_STOP_RE.search(foot.group(0))
        if nav_door is None:
            assert marked is None, f"{rel}: nav marks no door but the wayfinder marks {marked.group(1)}"
            continue
        checked += 1
        expected = v4_wayfinding.STATION_BY_DOOR[nav_door.group(1)]
        assert marked and marked.group(1) == expected, f"{rel}: nav says {expected}, wayfinder says {marked and marked.group(1)}"
    assert checked > 0, "no door-bearing pages found — the sweep didn't run over anything"
