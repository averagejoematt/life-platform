"""Shared site chrome — the doors nav, the loop-forward close, and the footer — from
ONE source (#1009, extended #1468).

The doors nav and the `.site-foot` footer are the platform's chrome: they appear on
every v4 page. Historically each `v4_build_*` generator hand-wrote its own copy, so the
markup drifted (icon-less navs on 5 pages, a richer coaching-column footer on the
coaching section, per-section base labels, a stray `/gear/` link). This module is the
single source of truth for all three, so a chrome edit is a one-file change and
`v4_apply_chrome.py` can re-flatten every page to it.

Four axes of per-page chrome variation are DELIBERATE and are parameters here — nothing
else varies:
  * `current_door` — the door the page lives under, marked `aria-current="page"`
    (one of "/cockpit/" "/data/" "/coaching/" "/protocols/" "/story/", or None).
  * `with_follow` — the "follow" pill, present on the 15 reader-facing pages.
  * `with_asof` (footer) — the live `data-bind="asof"` "updated YYYY-MM-DD" stamp in the
    footer base line; home only (story.js binds it from /api stats metadata, #1104).
  * `loop_forward`'s own `current_door` reuses the SAME detected door as the nav — see
    its docstring for why that's the right signal (not the `loop_ribbon` short-key one).
    Since #1475 `site_footer` takes the same `current_door` for the footer wayfinder, so
    nav, close and footer all state one position from one detected signal.

The byte layout matches the canonical nav/footer that ships on the ~51 dominant pages
exactly (HTML-entity apostrophes via `html.escape`, `&amp;`, single-line, no stray
whitespace) so regenerating a canonical page is a zero-diff no-op.
"""

from __future__ import annotations

import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v4_wayfinding  # noqa: E402 — the #1475 wayfinding layer (station registry + ribbon)

# The five doors, in loop order: cockpit · data · coaching · protocols · story.
# (href, label, sprite-key, title) — title becomes the hover tooltip, HTML-escaped.
# Labels are the reader's words, not the platform's (#4182, the owner's pick 2026-09-26:
# TODAY · THE NUMBERS · THE COACHES · WHAT HE TRIES · THE STORY). The URLs and sprite keys
# keep the builder names — no URL moves. Tooltips are third person: the site is about
# Matthew, the reader is not the subject. Measured at 360 + 390px: every two-word label
# wraps to two lines under its icon exactly as "the protocols" did, and the fixed bottom
# app-bar stays 66.8px (≤ its 68px body clearance) — no phone-only short label needed.
DOORS = [
    ("/cockpit/", "today", "cockpit", "Today, in one screen — how his week is going, how he slept, what today holds"),
    ("/data/", "the numbers", "data", "His numbers — weight, sleep, training, eating and blood tests, as his devices record them"),
    ("/coaching/", "the coaches", "coaching", "What his AI coaches say about his data — and how often they have been right"),
    ("/protocols/", "what he tries", "protocols", "What he takes and what he tries — each with what it should move"),
    ("/story/", "the story", "story", "The weekly write-up, his own words, and who he is"),
]

_VALID_DOORS = {href for href, _, _, _ in DOORS}

FOLLOW_PILL = '<a href="/subscribe/" class="nav-follow" aria-label="Follow the experiment">follow</a>'

THEME_TOGGLE = (
    '<button class="theme-toggle" type="button" aria-label="Toggle light and dark">'
    '<span class="theme-dot" aria-hidden="true"></span></button>'
)


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


# ── Head chrome (#1639) ────────────────────────────────────────────────────────
#
# The icon / manifest / theme-color block that belongs in every content page's
# <head>. Before #1639 this was copy-pasted as an f-string literal across ~10
# generators and had drifted: only 21 of 79 content pages shipped the manifest and
# apple-touch-icon, only 24 the theme-color pair, and NO page offered the vector
# favicon even though `site/assets/marks/favicon-{dark,light}.svg` already ship.
# `v4_apply_chrome.apply_head_chrome` re-flattens every content page's head to this
# single block the same way the nav/footer/loop-forward are flattened, so head chrome
# gets the same anti-drift gate the rest of the chrome already has.
#
# Order is load-bearing for the favicon: the `.ico` is declared FIRST as the universal
# fallback, then the SVG — a browser that understands `image/svg+xml` uses the later,
# more-capable declaration and renders the vector mark; one that doesn't silently
# ignores the type it can't decode and falls back to the `.ico`. The single SVG points
# at the DARK mark by design (rel=icon has no reliable per-scheme media selector across
# browsers); the light `.ico`/PNG cover light surfaces. The theme-color pair tints the
# mobile browser chrome to the page in each scheme.
HEAD_CHROME_TAGS = (
    '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#F4EFE4">',
    '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0E0C08">',
    '<link rel="icon" href="/favicon.ico">',
    '<link rel="icon" type="image/svg+xml" href="/assets/marks/favicon-dark.svg">',
    '<link rel="manifest" href="/manifest.webmanifest">',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
)


def head_chrome(indent: str = "  ") -> str:
    """The canonical <head> icon/manifest/theme-color block (#1639), one tag per line.

    `indent` is the per-line leading whitespace (pages use two spaces). Returns the tags
    joined by newlines with NO trailing newline — the caller controls the surrounding
    whitespace, exactly as `doors_nav()`/`site_footer()` return a bare element.
    """
    return "\n".join(indent + tag for tag in HEAD_CHROME_TAGS)


# ── Syndication chrome (#3615 box 5) ──────────────────────────────────────────
#
# WHAT WAS SHIPPING. Eleven pages under /story/ carried
#   <link rel="alternate" type="application/rss+xml" … href="/podcast/feed.xml">
# and the feed at that URL was 200 / 593 bytes: a complete <channel> with an
# <itunes:author>, an artwork link, and ZERO <item> elements (re-measured live
# 2026-09-21). Every podcast client treats `rel=alternate` as a real subscription
# offer, so the platform was advertising a show with no episodes — an unfurl that
# promises content nothing produces. That is the #3495 class (a claim a reader would
# believe that the platform's own data does not support), not a cosmetic nit.
#
# THE GATE, AND WHERE ITS TRUTH COMES FROM. A build script cannot see the live feed
# (it is generated into `generated/podcast/` in S3 and never committed), and a
# build-time HTTP fetch would make generated HTML depend on the network — the
# regenerate-to-a-zero-diff property the whole v4 build rests on would be gone. So the
# gate reads the ONE committed statement the platform already makes about that feed:
# the `Absence(contract="declared_dark")` on the `podcast/feed_items` cell of
# `lambdas/operational/hook_registry.py`. One declaration, two consumers:
#
#   * the nightly census PROBES the live feed and reports that cell honestly-absent
#     against the declaration (#3615 box 1, shipped in PR #4015);
#   * this module WITHDRAWS the advertisement for exactly the feeds it names.
#
# "Honestly absent" then becomes a whole statement instead of half of one: the feed is
# empty, the platform says so in a dated and owned declaration, and no page offers it.
# When the TTS episodes get built (the other half of box 5's owner choice — the grade
# is identical either way), deleting that Absence and re-running the story builder
# brings the link back, and `tests/test_podcast_feed_link_3615.py` REDS until both
# halves move in the same direction.
FEED_LINKS = (
    ("/rss.xml", "averagejoematt"),
    ("/podcast/feed.xml", "The Measured Life — read aloud (podcast)"),
    ("/panelcast/feed.xml", "The Measured Life — The Panel (podcast)"),
)


def dark_feeds() -> frozenset:
    """Feed paths the hook registry DECLARES dark — advertising one is a false offer.

    Derived from `hook_registry` rather than re-listed here: a second hand-maintained
    copy of "which feeds are empty" is the drift this gate exists to end. A feed with no
    registry row (today `/rss.xml`) is not gated — it is a surface the census has never
    ruled on, and silence is not a declaration in either direction.

    Raises rather than guessing when the registry cannot be read: a build that fell back
    to "advertise everything" would quietly republish the false offer, and an unreadable
    committed module is a real breakage, not a degraded environment.
    """
    lambdas_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
    if lambdas_dir not in sys.path:
        sys.path.insert(0, lambdas_dir)
    try:
        from operational import hook_registry
    except Exception as exc:  # noqa: BLE001 — any import failure here is the same verdict
        raise RuntimeError(f"v4_chrome cannot read lambdas/operational/hook_registry.py, so it cannot tell which feeds are dark: {exc}")
    dark = set()
    for _hook, artifact in hook_registry.cells():
        absence = getattr(artifact, "absence", None)
        if absence is not None and absence.contract == "declared_dark" and str(artifact.locator).startswith("/"):
            dark.add(artifact.locator)
    return frozenset(dark)


def syndication_links(indent: str = "  ") -> str:
    """The page's `<link rel=alternate>` feed block, minus every declared-dark feed.

    One tag per line, joined with newlines and no trailing newline — the same contract
    as `head_chrome()`.
    """
    dark = dark_feeds()
    return "\n".join(
        f'{indent}<link rel="alternate" type="application/rss+xml" title="{title}" href="{href}">'
        for href, title in FEED_LINKS
        if href not in dark
    )


def _door_icon(key: str) -> str:
    # Inline <use> of the shared sprite — server-rendered (no JS), inherits .ico-door colour.
    return (
        '<svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f'<use href="/assets/icons/icons.svg#i-door-{key}"></use></svg>'
    )


def doors_nav(current_door: str | None = None, with_follow: bool = False) -> str:
    """The canonical doors nav.

    `current_door` is the door path ("/cockpit/" "/data/" "/coaching/" "/protocols/"
    "/story/") to mark `aria-current="page"`, or None for pages under no door.
    `with_follow` includes the follow pill immediately before the theme toggle.
    """
    if current_door is not None and current_door not in _VALID_DOORS:
        raise ValueError(f"current_door must be one of {sorted(_VALID_DOORS)} or None, got {current_door!r}")
    links = []
    for href, label, key, title in DOORS:
        current = ' aria-current="page"' if href == current_door else ""
        links.append(f'<a href="{href}" title="{_esc(title)}"{current}>{_door_icon(key)}{label}</a>')
    follow = FOLLOW_PILL if with_follow else ""
    return f'<nav class="doors" aria-label="Doors">{"".join(links)}{follow}{THEME_TOGGLE}</nav>'


ASOF_STAMP = '<span class="label asof" data-bind="asof"></span>'

# #1620 — outbound social follow links for the footer's "Follow &amp; context" column.
# Before this the live site had ZERO outbound social links, so a post that went viral had
# nowhere to send follow intent. These are the site's canonical follow destinations. They
# are external, so each carries target="_blank" + rel="me noopener" — rel=me asserts the
# identity backlink (Mastodon/IndieAuth-style verification), noopener closes the reverse-
# tabnabbing handle. Handles are owner-confirmed (2026-07-23): the issue's TikTok typo
# `avereagejoematt` was corrected to `averagejoematt`. Bluesky uses the default
# `<handle>.bsky.social` namespace; X is the underscore handle; YouTube/TikTok use the
# @handle form. This is the ONE source for the footer marks — dispatches.js (the in-app
# chronicle reader) and wednesday_chronicle_lambda.py (the crawlable post permalink) carry
# their own copies of the same handle set by necessity (JS + email-Lambda runtimes).
SOCIAL_LINKS = (
    ("https://bsky.app/profile/averagejoematt.bsky.social", "Bluesky"),
    ("https://x.com/averagejoematt_", "X"),
    ("https://www.instagram.com/averagejoematt/", "Instagram"),
    ("https://www.reddit.com/user/averagejoematt/", "Reddit"),
    ("https://www.youtube.com/@averagejoematt", "YouTube"),
    ("https://www.tiktok.com/@averagejoematt", "TikTok"),
)
_SOCIAL_FOOT_HTML = "".join(f'<a href="{href}" target="_blank" rel="me noopener">{label}</a>' for href, label in SOCIAL_LINKS)


# The mega-menu, in LOOP ORDER (#1475). Before the wayfinding layer this was six
# columns in arrival order (Story first) with every heading ember — a directory whose
# accent carried no information. It is now the loop laid out left-to-right: the four
# causal stages fill the first grid row (Data → Coaching → Protocols → Story), and the
# two meta columns that sit OUTSIDE the loop — The Technology and Follow &amp; context —
# fill the second. Each stage column is keyed to its station (`data-station`) so the
# wayfinder ribbon above it can light the column it owns, and so the station the reader
# is currently inside is the one and only ember thing in the menu.
#
# (#1475 kept every pre-existing link; #4182 below is the deliberate IA edit that cut it.)
#
# The 25-page reach set (#4182, the 2026-09-26 panel ruling): the footer is re-poured from
# 42 links to the 23 page links below, under the doors' new labels plus FOLLOW. A newcomer
# meets the REACHABLE set, not the served one, so the pages this drops — /data/ledger/,
# /data/reading/, /data/glucose/, /coaching/team/ (→ By coach), /protocols/supplements/
# (pixel-identical to /protocols/), /protocols/challenges/, /story/chronicle/ (→ /story/),
# /story/timeline/, /story/agents/, /method/platform/ and the /method/{ask,cost,pipeline,…}
# cuts — stay SERVED at their URLs, just unlinked (no URL moves, no 301s, no deletions).
# `tests/site_vocabulary_residue.py::NAV_REACH_CEILING` (25) is the ratchet that holds it;
# `tests/test_wayfinding.py::FOOTER_LINKS_4182` pins the pour.
#   "How it's built" is the menu home for the platform-itself pages (#1110): the /method/
# hub, the build log (URL unchanged), the gear, and the score explainer.
#   FOLLOW keeps the six outbound social marks (#1620) — they are follow destinations, not
# pages, so they are outside the 23 and outside the reach count.
#   (station key or None, heading, links HTML)
FOOTER_COLUMNS = (
    (
        "data",
        "The numbers",
        '<a href="/data/physical/">Weight &amp; body</a><a href="/data/sleep/">Sleep</a>'
        '<a href="/data/training/">Training</a><a href="/data/nutrition/">Eating</a>'
        '<a href="/data/labs/">Blood tests</a>',
    ),
    (
        "coaching",
        "The coaches",
        '<a href="/coaching/">The read</a><a href="/coaching/by-coach/">By coach</a>'
        '<a href="/coaching/scorecard/">Their record</a>'
        '<a href="/coaching/lab-notes/">What the AI said, and how it felt</a>',
    ),
    (
        "protocols",
        "What he tries",
        '<a href="/protocols/">What he takes</a><a href="/protocols/experiments/">Experiments</a>',
    ),
    (
        "story",
        "The story",
        '<a href="/story/">The weekly write-up</a><a href="/story/journal/">In his own words</a>'
        '<a href="/story/panel/">The podcast</a>'
        '<a href="/story/about/">Who he is</a>',
    ),
    (
        None,
        "How it&#x27;s built",
        '<a href="/method/">Under the hood</a><a href="/story/build/">The build log</a>'
        '<a href="/gear/">The gear</a><a href="/method/character/">How the score works</a>',
    ),
    (
        None,
        "Follow",
        f'<a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a>{_SOCIAL_FOOT_HTML}' '<a href="/privacy/">Privacy</a>',
    ),
)


def site_footer(with_asof: bool = False, current_door: str | None = None) -> str:
    """The canonical `.site-foot` footer — the wayfinding layer on every page (#1475).

    Three stacked pieces, one source:
      1. the **wayfinder** (`v4_wayfinding.wayfinder`) — the loop's five stations with
         this page's station marked, the next one tagged, and the one it came from
         lifted. This is what makes "no reader is ever more than one interaction from
         the loop" structural rather than per-page: it ships inside the footer, and
         `v4_apply_chrome.py` puts the footer on every chrome-bearing page;
      2. the **mega-menu** (`FOOTER_COLUMNS`) — the same ~30 links as before, re-poured
         in loop order and keyed to their stations;
      3. the base line — brand, the optional live stamp, the home link.

    `current_door` is the door href the doors nav marks (`"/data/"`, `"/story/"`, …) —
    `v4_apply_chrome.py` detects it once per page and hands the SAME value to
    `doors_nav`, `loop_forward` and here, so the three surfaces can never disagree about
    where the reader is. `None` renders the unmarked ribbon (home, `/gear/`, utility).

    `with_asof` (home only, #1104) keeps the live "updated YYYY-MM-DD" stamp that
    home's old slim footer carried: `story.js` binds `data-bind="asof"` from the
    public-stats metadata, so the stamp rides in the base line between the brand
    and the home link (the `.sf-base` flex line spaces the three apart).
    """
    asof = ASOF_STAMP if with_asof else ""
    here = v4_wayfinding.STATION_BY_DOOR.get(current_door) if current_door else None
    cols = "".join(
        v4_wayfinding.menu_column(heading, links, station=station, is_here=bool(station and station == here))
        for station, heading, links in FOOTER_COLUMNS
    )
    return (
        f'<footer class="site-foot">{PAGE_FEEDBACK_FORM}{v4_wayfinding.wayfinder(current_door)}'
        f'<nav class="site-foot-cols" aria-label="Site map">{cols}</nav>'
        f'<p class="sf-base label"><span>averagejoematt</span>{asof}<a href="/">← home</a></p>'
        f"{ATTRIBUTION_TAG}{GLOSS_RUNTIME_TAG}{PAGE_FEEDBACK_TAG}</footer>"
    )


# #4182 (M2): the runtime half of the glossary — glosses registered terms in JS-rendered
# text (the build-time pass in v4_glossary.py cannot see it). Rides in the footer for the
# same reason as ATTRIBUTION_TAG: the footer is on every chrome-bearing page by
# construction and FOOT_RE rewrites it wholesale, so the tag is idempotent.
GLOSS_RUNTIME_TAG = '<script type="module" src="/assets/js/gloss_runtime.js"></script>'

# #4182 (M3, site half): the reader form — "did this page make sense?" Three radios + an
# optional ≤500-char "what were you looking for?". Ships `hidden`: page_feedback.js
# un-hides it, so a no-JS reader never meets a form that cannot send. It POSTs to
# /api/page_feedback, which lands separately (the engine half) — until then the endpoint
# 404s and the script stays silent, never claiming a send that didn't happen.
PAGE_FEEDBACK_FORM = (
    '<form class="page-feedback" hidden>'
    '<fieldset class="pf-set"><legend class="pf-q">Did this page make sense?</legend>'
    '<label class="pf-opt"><input type="radio" name="made_sense" value="yes" required> Yes</label>'
    '<label class="pf-opt"><input type="radio" name="made_sense" value="partly"> Partly</label>'
    '<label class="pf-opt"><input type="radio" name="made_sense" value="no"> No</label>'
    "</fieldset>"
    '<label class="pf-more">What were you looking for? <span class="pf-optional">(optional)</span>'
    '<textarea name="looking_for" maxlength="500" rows="2"></textarea></label>'
    '<button class="pf-send" type="submit">Send</button>'
    '<p class="pf-status" role="status" aria-live="polite"></p>'
    "</form>"
)
PAGE_FEEDBACK_TAG = '<script type="module" src="/assets/js/page_feedback.js"></script>'


# #1621: site-wide UTM capture. This rides in the canonical footer — INSIDE the
# `<footer>` element, not after it — because the footer is what `v4_apply_chrome.py`
# rewrites wholesale, so the tag is idempotent under FOOT_RE and cannot be duplicated
# or orphaned by a re-sweep. The footer is also the one piece of markup every
# chrome-bearing page provably carries, which is exactly the "capture on landing
# ANYWHERE on the site" guarantee the attribution needs: a capture scoped to the
# subscribe page alone would attribute almost nothing while appearing to work.
# `type="module"` defers execution to after parse, which is well before any
# subscribe-form click.
ATTRIBUTION_TAG = '<script type="module" src="/assets/js/attribution.js"></script>'


# ── The loop-forward close (#1468) ─────────────────────────────────────────────
#
# The journey audit (docs/design/JOURNEYS.md) found every door's exit was the mega-menu
# footer — a directory, not a DECISION. Every page now closes with one deliberate
# "next station on the loop" before the footer: a single forward link that advances the
# causal loop (data → coaching → protocols → story → cockpit, cycling — the same order
# `loop_ribbon` draws) plus one constant return trigger (follow by email — the
# north-star's return mechanism for all four audiences). Consistency is the point: one
# shape, everywhere, so no page is a dead end and no page improvises its own close.
#
# Keyed by the SAME `current_door` the doors nav already carries (href form), not
# `loop_ribbon`'s short key — Method/registry/game pages nav-highlight "/data/" (they're
# a deeper cut of the Data door, not a fifth door of their own; SITE_MAP_AND_INTENT.md),
# so their loop-forward correctly proposes Coaching next, matching what a reader who came
# for credibility would want next. `/gear/`, `/privacy/`, home, and the utility pages
# carry no current door — they fall to DEFAULT_NEXT (start the loop at the cockpit).
NEXT_STATION = {
    "/cockpit/": ("/data/", "the numbers", "See what's driving today's read"),
    "/data/": ("/coaching/", "the coaches", "See what the AI team makes of it"),
    "/coaching/": ("/protocols/", "what he tries", "See what levers get pulled next"),
    "/protocols/": ("/story/", "the story", "Follow whether it moved anything"),
    "/story/": ("/cockpit/", "today", "Check today's live read"),
}
DEFAULT_NEXT = ("/cockpit/", "today", "Start with today's live read")

RETURN_TRIGGER = ("/subscribe/", "follow by email", "for the next entry")
# The two pages the universal return trigger would self-link on — swap to a neutral
# "back into the loop" trigger there instead (#1468 audit finding).
_RETURN_SELF_SWAP = {"/subscribe/", "/subscribe/confirm/"}


def loop_forward(current_door: str | None, self_path: str | None = None) -> str:
    """The canonical closing "next station on the loop" CTA (#1468).

    `current_door` is the same value passed to `doors_nav()` for this page. `self_path`
    is this page's own viewer path (e.g. "/subscribe/") — only used to avoid the return
    trigger linking to the page the reader is already on.
    """
    href, label, hook = NEXT_STATION.get(current_door, DEFAULT_NEXT)
    if self_path in _RETURN_SELF_SWAP:
        return_bit = '<a href="/">keep exploring the loop</a>'
    else:
        r_href, r_label, r_hook = RETURN_TRIGGER
        return_bit = f'<a href="{r_href}">{r_label}</a> {r_hook}'
    return (
        '<aside class="loop-forward" aria-label="Continue the loop">'
        f'<p class="lf-next"><span class="label">next on the loop</span> '
        f'<a href="{href}">{_esc(label)}</a> — {_esc(hook)}</p>'
        f'<p class="lf-return"><span class="label">or come back</span> {return_bit}</p>'
        "</aside>"
    )
