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

The byte layout matches the canonical nav/footer that ships on the ~51 dominant pages
exactly (HTML-entity apostrophes via `html.escape`, `&amp;`, single-line, no stray
whitespace) so regenerating a canonical page is a zero-diff no-op.
"""

from __future__ import annotations

import html

# The five doors, in loop order: cockpit · data · coaching · protocols · story.
# (href, label, sprite-key, title) — title becomes the hover tooltip, HTML-escaped.
DOORS = [
    ("/cockpit/", "the cockpit", "cockpit", "Today's live instrument — your daily numbers, read back to you"),
    ("/data/", "the data", "data", "Every source the platform reads — trends now and over time"),
    ("/coaching/", "the coaching", "coaching", "The AI team & their arguments — stances, track records, disagreements"),
    ("/protocols/", "the protocols", "protocols", "The levers — supplements, experiments, challenges, discoveries"),
    ("/story/", "the story", "story", "The writing & the why — chronicle, journal, timeline, about"),
]

_VALID_DOORS = {href for href, _, _, _ in DOORS}

FOLLOW_PILL = '<a href="/subscribe/" class="nav-follow" aria-label="Follow the experiment">follow</a>'

THEME_TOGGLE = (
    '<button class="theme-toggle" type="button" aria-label="Toggle light and dark">'
    '<span class="theme-dot" aria-hidden="true"></span></button>'
)


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


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


def site_footer(with_asof: bool = False) -> str:
    """The canonical `.site-foot` footer — one site map on every page.

    Based on the dominant footer (the ~51 data/method/protocols pages) but unified
    UP for the coaching column: it carries the FULLER "The Coaching" set (The Read /
    By Coach / Scorecard / The Team / AI lab notes) so no live coaching link is lost
    site-wide, and it fixes the dominant footer's mislabel (/coaching/ is "The Read",
    /coaching/team/ is "The Team"). Additive for the dominant pages (#1009 review).

    `with_asof` (home only, #1104) keeps the live "updated YYYY-MM-DD" stamp that
    home's old slim footer carried: `story.js` binds `data-bind="asof"` from the
    public-stats metadata, so the stamp rides in the base line between the brand
    and the home link (the `.sf-base` flex line spaces the three apart).

    IA notes (2026-07-12): "The Technology" column (#1110) is the menu home for the
    platform-itself content — the /method/ hub, the build log (moved here OUT of the
    story sub-nav; URL unchanged), the curated machine pages, and /gear/ (#1111 — the
    devices behind the data). "The ledger" (#1109) and "The agents" (#1111) are footer-
    linked so neither is an unaccounted orphan; the ledger stays OFF the /data/ tile
    rail by explicit registry intent (`"unlisted"` in v4_build_evidence.REGISTRY).
    """
    asof = ASOF_STAMP if with_asof else ""
    return (
        '<footer class="site-foot"><nav class="site-foot-cols" aria-label="Site map">'
        '<div class="sf-col"><p class="sf-h label">The Story</p>'
        '<a href="/story/chronicle/">Chronicle</a><a href="/story/panel/">Podcast</a>'
        '<a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a>'
        '<a href="/story/attempts/">The attempts</a>'
        '<a href="/story/agents/">The agents</a><a href="/story/about/">About</a></div>'
        '<div class="sf-col"><p class="sf-h label">The Data</p>'
        '<a href="/data/">All topics</a><a href="/method/ask/">Ask the data</a>'
        '<a href="/data/labs/">Labs</a><a href="/data/training/">Training</a>'
        '<a href="/data/sleep/">Sleep</a><a href="/data/ledger/">The ledger</a></div>'
        '<div class="sf-col"><p class="sf-h label">The Protocols</p>'
        '<a href="/protocols/">All protocols</a><a href="/protocols/supplements/">Supplements</a>'
        '<a href="/protocols/experiments/">Experiments</a><a href="/protocols/challenges/">Challenges</a></div>'
        '<div class="sf-col"><p class="sf-h label">The Coaching</p>'
        '<a href="/coaching/">The Read</a><a href="/coaching/by-coach/">By Coach</a>'
        '<a href="/coaching/scorecard/">Scorecard</a><a href="/coaching/team/">The Team</a>'
        '<a href="/coaching/lab-notes/">AI lab notes</a></div>'
        '<div class="sf-col"><p class="sf-h label">The Technology</p>'
        '<a href="/method/">The machine</a><a href="/story/build/">Build log</a>'
        '<a href="/method/platform/">The platform</a><a href="/method/pipeline/">Pipeline status</a>'
        '<a href="/method/cost/">Cost</a><a href="/gear/">The gear</a></div>'
        '<div class="sf-col"><p class="sf-h label">Follow &amp; context</p>'
        '<a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a>'
        '<a href="/story/about/">About</a>'
        '<a href="/privacy/">Privacy</a></div>'
        f'</nav><p class="sf-base label"><span>averagejoematt</span>{asof}<a href="/">← home</a></p></footer>'
    )


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
    "/cockpit/": ("/data/", "the data", "See what's driving today's read"),
    "/data/": ("/coaching/", "the coaching", "See what the AI team makes of it"),
    "/coaching/": ("/protocols/", "the protocols", "See what levers get pulled next"),
    "/protocols/": ("/story/", "the story", "Follow whether it moved anything"),
    "/story/": ("/cockpit/", "the cockpit", "Check today's live read"),
}
DEFAULT_NEXT = ("/cockpit/", "the cockpit", "Start with today's live read")

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
