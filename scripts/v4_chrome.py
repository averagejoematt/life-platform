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


def doors_nav(
    current_door: str | None = None, with_follow: bool = False, base: str | None = None
) -> str:  # noqa: ARG001 — the follow pill retired
    """The canonical page nav — since the cut-over (ADR-157, #4182) the five-item v7 bar.

    `current_door` marks `aria-current="page"`. Two spellings are accepted, because two
    writers call this: `scripts/v7_build.py` passes the page path under the base ("" home,
    "cockpit/" …); `v4_apply_chrome.py` re-detects the door from an existing page's own
    nav, where the href is the viewer path ("/data/", or "/next/data/" on a preview shell).
    Every spelling normalises to the page key; a door outside the nine (an archive page
    whose old nav marked "/data/") marks nothing, never raises — the archive pages are
    served-but-unlisted and their bar is the same bar as everyone else's.

    `base` is the viewer prefix the bar links under (None → `V7_BASE`): the chrome pass
    hands "/next/" for a preview shell so its bar keeps pointing into the preview.
    """
    if EDITION != "v7":
        raise RuntimeError("the v4 doors nav was retired at the cut-over (ADR-157, #4182) — EDITION must be 'v7'")
    return v7_bar(_v7_page_key(current_door, base), base)


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


def site_footer(
    with_asof: bool = False, current_door: str | None = None, base: str | None = None
) -> str:  # noqa: ARG001 — generators' call sites
    """The canonical footer — since the cut-over (ADR-157, #4182) the one-line v7 footer
    tier (`v7_foot`): the four footer-tier pages, RSS and Privacy, plus the two functional
    tags every page has always carried (attribution capture, the runtime glossary pass).

    `with_asof` and `current_door` are accepted and ignored: the v4 mega-menu, the #1475
    wayfinder and home's live "updated" stamp retired with the v4 footer (the wayfinding
    module `scripts/v4_wayfinding.py` was deleted in the same PR). The generators that
    still pass them need no edit — the signature is the contract, the pour is the edition's.
    """
    if EDITION != "v7":
        raise RuntimeError("the v4 footer was retired at the cut-over (ADR-157, #4182) — EDITION must be 'v7'")
    return v7_foot(base)


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


# ── The loop-forward close (#1468) — RETIRED at the cut-over (ADR-157, #4182) ──────────
#
# The "next station on the loop" aside argued one forward step under every v4 page. v7 has
# no loop to advance: the five-item bar is fixed on every page, so no page is a dead end by
# construction, and the archive pages (served, unlisted) carry the same bar. `NEXT_STATION`,
# `DEFAULT_NEXT` and the return trigger went with `scripts/v4_wayfinding.py`.
# `loop_forward()` stays as the generators' call site and returns nothing; the chrome pass
# removes any aside a committed page still carries.


def loop_forward(current_door: str | None, self_path: str | None = None) -> str:  # noqa: ARG001 — retired close; the call sites stay
    """Retired (ADR-157): the v7 bar replaces the close. Always the empty string."""
    return ""


# ── The v7 edition (#4182, epic — the rebuild as one serialised investigation) ────────
#
# `EDITION` is the ONE switch between the live v4 chrome above and the v7 chrome below.
# The default is "v4": nothing on the live pages changes until the cut-over PR flips it and
# re-pours every chrome-bearing page through `v4_apply_chrome.py`. `scripts/v7_build.py`
# sets EDITION = "v7" (and `V7_BASE`) for its own process only, so the preview shells at
# `site/next/**` are poured from the same `doors_nav()` / `site_footer()` call sites the
# live pages use — the cut-over is a flag flip, not a second chrome.
#
# `V7_BASE` is the viewer prefix the nine v7 pages are served under: "/" once live,
# "/next/" for the preview subtree (plan §1b). Page links carry it; asset and API paths
# never do (they stay root-absolute — the hasher rewrites `/assets/(js|css)/<name>` and
# would point a `/next/assets/…` reference at a hash that does not exist under `/next/`).
EDITION = "v7"  # flipped at the cut-over (ADR-157, #4182) — the v4 branches above now raise
V7_BASE = "/"

# The bottom bar: the five pages a reader reaches with a thumb (CONCEPT §3 rows 1–5).
# (page path under V7_BASE, label). "" is the v7 home.
V7_BAR = (
    ("", "Home"),
    ("cockpit/", "Today"),
    ("story/", "This week"),
    ("data/", "His numbers"),
    ("coaching/", "The coaches"),
)

# The footer tier: the four pages that are one tap from any of the five (CONCEPT §3 rows 6–9).
V7_FOOT = (
    ("protocols/", "What he’s trying"),
    ("story/about/", "Who he is"),
    ("method/", "Under the hood"),
    ("subscribe/", "Follow"),
)

REPO_URL = "https://github.com/averagejoematt/life-platform"

# The nine (ADR-157): the bar's five + the footer tier's four, in CONCEPT §3 order. Derived,
# not re-listed — `v4_apply_chrome.write_page` refuses to let a v4 generator overwrite one of
# these paths with a non-v7 page (the deploy's coaching/dispatches/evidence builders still
# emit the old hubs; `scripts/v7_build.py` is the only writer of the nine).
V7_PAGES = tuple(p for p, _ in V7_BAR) + tuple(p for p, _ in V7_FOOT)


def _v7_page_key(door: str | None, base: str | None = None) -> str | None:
    """Normalise a door spelling to the page key under `base` (None → `V7_BASE`), or None.

    "" / "cockpit/" (a page key) → itself; "/" → ""; "/data/" → "data/"; "/next/data/"
    (a preview shell's own href, base "/next/") → "data/". Anything outside the nine → None.
    """
    if door is None:
        return None
    b = V7_BASE if base is None else base
    key = door
    if b != "/" and key.startswith(b):
        key = key[len(b) :]
    elif key.startswith("/"):
        key = key[1:]
    return key if key in V7_PAGES else None


def v7_href(page: str, base: str | None = None) -> str:
    """Viewer href of a v7 page under the edition's base ("" → the base itself)."""
    b = V7_BASE if base is None else base
    if not b.startswith("/") or not b.endswith("/"):
        raise ValueError(f"V7_BASE must start and end with '/', got {b!r}")
    return b + page


def v7_bar(current: str | None = None, base: str | None = None) -> str:
    """The five-item v7 bar. `current` is the page path under the base ("" for home,
    "cockpit/" …) to mark `aria-current="page"`, or None."""
    items = []
    for page, label in V7_BAR:
        cur = ' aria-current="page"' if page == current else ""
        items.append(f'<a href="{v7_href(page, base)}"{cur}>{_esc(label)}</a>')
    return f'<nav class="v7-bar" aria-label="Pages">{"".join(items)}</nav>'


def v7_masthead(base: str | None = None) -> str:
    """The v7 masthead: the brand (home) and the repo link. One line, no menu."""
    return (
        '<header class="v7-mast">'
        f'<a class="v7-brand" href="{v7_href("", base)}">averagejoematt</a>'
        f'<a class="v7-repo" href="{REPO_URL}" rel="noopener">the code</a>'
        "</header>"
    )


def v7_foot(base: str | None = None) -> str:
    """The v7 footer: the four footer-tier pages plus privacy, one line."""
    links = "".join(f'<a href="{v7_href(page, base)}">{_esc(label)}</a>' for page, label in V7_FOOT)
    # RSS stays reachable from every page (cut-over deviation recorded on ADR-157: the v4
    # footer linked /rss.xml; the feed is real and non-empty, so the link is kept). The two
    # script tags are invisible chrome the whole site has always carried: #1621 UTM capture
    # and #4182 M2's runtime glossary pass — dropping them silently would be a regression,
    # not a design. The #4182 M3 reader form (`PAGE_FEEDBACK_FORM`) is NOT poured here: v7
    # ships no footer form; its return is a design decision for the driver, recorded in the
    # cut-over PR.
    return (
        f'<footer class="v7-foot"><nav aria-label="More">{links}<a href="/rss.xml">RSS</a><a href="/privacy/">Privacy</a></nav>'
        f"{ATTRIBUTION_TAG}{GLOSS_RUNTIME_TAG}</footer>"
    )
