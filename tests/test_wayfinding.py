"""The wayfinding layer — structural guards, re-pinned at the v7 cut-over (#1475 → ADR-157, #4182).

Until the cut-over this file pinned the v4 footer: the #1475 wayfinder ribbon (the loop's
five stations), the mega-menu re-poured on the loop, and the 22-link `FOOTER_LINKS_4182`
pour of the 24-page reach set. ADR-157 retired all three with `scripts/v4_wayfinding.py`
(deleted in the cut-over PR): the site is nine reachable pages, the bar is fixed on every
page, and no page is a dead end by construction. What this file now holds is the v7 shape
of the same three properties:

1. **Navigable from anywhere** — every chrome-bearing page under `site/` (legacy excluded)
   carries exactly one `nav.v7-bar` and one `footer.v7-foot`, and none of the retired
   chrome (`.doors`, `.site-foot`, `.wayfinder`, `.loop-forward`), verified over the real
   inventory rather than a hand-maintained list.
2. **One position, one signal** — the bar marks `aria-current="page"` on the page's own key
   for each of the nine, and nothing on an archive page (served, unlisted).
3. **The footer pour is pinned** — exactly the four footer-tier pages + RSS + Privacy
   (`FOOTER_LINKS_4182`), an exact set: adding a footer link is an IA decision that must
   move this pin and `NAV_REACH_CEILING` together.

Plus the retirement itself, asserted so it cannot creep back: the wayfinding module is
gone, `NEXT_STATION` / `DEFAULT_NEXT` are gone from `v4_chrome`, and `loop_forward()` is
the empty string (the generators' call sites stay; the chrome pass strips any aside a
committed page still carries).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

sys.path.insert(0, str(ROOT / "scripts"))
import v4_chrome  # noqa: E402

HREF_RE = re.compile(r'href="([^"]+)"')
BAR_RE = re.compile(r'<nav class="v7-bar".*?</nav>', re.DOTALL)
FOOT_RE = re.compile(r'<footer class="v7-foot".*?</footer>', re.DOTALL)
CURRENT_RE = re.compile(r'<a href="([^"]+)" aria-current="page">')

# The footer's links since the cut-over (ADR-157): the four footer-tier pages, the feed
# (a deviation recorded on ADR-157 — v7's concept footer had no RSS link; the feed is real
# and non-empty, so the link stays) and Privacy. An exact set, not a subset.
FOOTER_LINKS_4182 = {
    "/protocols/",
    "/story/about/",
    "/method/",
    "/subscribe/",
    "/rss.xml",
    "/privacy/",
}
BAR_LINKS = ["/", "/cockpit/", "/story/", "/data/", "/coaching/"]
BAR_LABELS = ["Home", "Today", "This week", "His numbers", "The coaches"]
RETIRED_CHROME = ('<nav class="doors"', '<footer class="site-foot"', '<nav class="wayfinder"', '<aside class="loop-forward"')


def _non_legacy_pages():
    for path in sorted(SITE.rglob("*.html")):
        if "legacy" in path.relative_to(SITE).parts:
            continue
        yield path


def _viewer_path(path: Path) -> str:
    rel = path.relative_to(SITE).as_posix()
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


# ── The registry itself ─────────────────────────────────────────────────────────


def test_the_nine_are_the_bar_plus_the_footer_tier():
    """`V7_PAGES` derives from the two registries — the bar's five, then the footer's four."""
    assert v4_chrome.V7_PAGES == ("", "cockpit/", "story/", "data/", "coaching/", "protocols/", "story/about/", "method/", "subscribe/")
    assert [lbl for _, lbl in v4_chrome.V7_BAR] == BAR_LABELS


def test_the_footer_pour_is_exactly_the_tier_plus_rss_and_privacy():
    foot = v4_chrome.site_footer()
    pages = HREF_RE.findall(foot)
    assert len(pages) == len(set(pages)) == 6, f"the footer pour must be 6 distinct links, got {len(pages)}: {pages}"
    assert set(pages) == FOOTER_LINKS_4182, (
        f"footer drifted from the ADR-157 pour — added {sorted(set(pages) - FOOTER_LINKS_4182)}, "
        f"dropped {sorted(FOOTER_LINKS_4182 - set(pages))}"
    )
    # the two functional tags every page has always carried ride in the footer (#1621, #4182 M2)
    assert v4_chrome.ATTRIBUTION_TAG in foot and v4_chrome.GLOSS_RUNTIME_TAG in foot


def test_the_bar_is_the_five_in_concept_order_and_marks_one_key():
    bar = v4_chrome.doors_nav()
    assert HREF_RE.findall(bar) == BAR_LINKS
    assert re.findall(r">([^<]+)</a>", bar) == BAR_LABELS
    assert "aria-current" not in bar
    for key in v4_chrome.V7_PAGES:
        marked = CURRENT_RE.findall(v4_chrome.doors_nav(key))
        assert marked == ([f"/{key}"] if key in dict(v4_chrome.V7_BAR) else []), key
    # both door spellings normalise: the page key and the viewer path (an archive page's old nav)
    assert CURRENT_RE.findall(v4_chrome.doors_nav("/data/")) == ["/data/"]
    assert CURRENT_RE.findall(v4_chrome.doors_nav("/data/sleep/")) == []
    # a preview shell keeps its bar inside the preview
    assert HREF_RE.findall(v4_chrome.doors_nav("cockpit/", base="/next/"))[0] == "/next/"


def test_the_wayfinder_and_the_loop_forward_are_retired():
    assert not (ROOT / "scripts" / "v4_wayfinding.py").exists(), "the wayfinding module came back (ADR-157 retired it)"
    for name in ("NEXT_STATION", "DEFAULT_NEXT", "FOOTER_COLUMNS", "RETURN_TRIGGER"):
        assert not hasattr(v4_chrome, name), f"v4_chrome.{name} came back — the loop close was retired at the cut-over"
    assert v4_chrome.loop_forward("/data/") == "" and v4_chrome.loop_forward(None, self_path="/subscribe/") == ""
    assert v4_chrome.EDITION == "v7"


# ── The real page inventory ─────────────────────────────────────────────────────


def test_every_chrome_bearing_page_carries_one_bar_one_footer_and_none_of_the_retired_chrome():
    checked = 0
    for path in _non_legacy_pages():
        html = path.read_text(encoding="utf-8")
        if '<nav class="v7-bar"' not in html and '<footer class="v7-foot"' not in html:
            continue
        checked += 1
        rel = path.relative_to(SITE)
        assert html.count('<nav class="v7-bar"') == 1, f"{rel}: expected exactly one v7 bar"
        assert html.count('<footer class="v7-foot"') == 1, f"{rel}: expected exactly one v7 footer"
        for marker in RETIRED_CHROME:
            assert marker not in html, f"{rel}: retired chrome survived the cut-over: {marker}"
    assert checked >= 90, f"only {checked} chrome-bearing pages found — the sweep ran over too little"


def test_the_bar_marks_the_pages_own_key_and_links_under_its_own_base():
    checked = 0
    for path in _non_legacy_pages():
        html = path.read_text(encoding="utf-8")
        bar_m = BAR_RE.search(html)
        if not bar_m:
            continue
        rel = path.relative_to(SITE)
        viewer = _viewer_path(path)
        base = "/next/" if viewer.startswith("/next/") else "/"
        hrefs = HREF_RE.findall(bar_m.group(0))
        assert hrefs == [base + p for p, _ in v4_chrome.V7_BAR], f"{rel}: the bar links drifted from V7_BAR under {base}"
        marked = CURRENT_RE.findall(bar_m.group(0))
        key = viewer[len(base) :] if viewer.startswith(base) else None
        expect = [viewer] if key in dict(v4_chrome.V7_BAR) else []
        assert marked == expect, f"{rel}: bar marks {marked}, expected {expect}"
        if expect:
            checked += 1
    assert checked == 10, f"expected the five bar pages live + preview to mark themselves, got {checked}"
