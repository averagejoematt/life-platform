"""Shared site chrome — the doors nav + the footer — from ONE source (#1009).

The doors nav and the `.site-foot` footer are the platform's chrome: they appear on
every v4 page. Historically each `v4_build_*` generator hand-wrote its own copy, so the
markup drifted (icon-less navs on 5 pages, a richer coaching-column footer on the
coaching section, per-section base labels, a stray `/gear/` link). This module is the
single source of truth for both, so a chrome edit is a one-file change and
`v4_apply_chrome.py` can re-flatten every page to it.

Two axes of per-page nav variation are DELIBERATE and are parameters here — nothing else
varies:
  * `current_door` — the door the page lives under, marked `aria-current="page"`
    (one of "/now/" "/data/" "/coaching/" "/protocols/" "/story/", or None).
  * `with_follow` — the "follow" pill, present on the 15 reader-facing pages.

The byte layout matches the canonical nav/footer that ships on the ~51 dominant pages
exactly (HTML-entity apostrophes via `html.escape`, `&amp;`, single-line, no stray
whitespace) so regenerating a canonical page is a zero-diff no-op.
"""

from __future__ import annotations

import html

# The five doors, in loop order: cockpit · data · coaching · protocols · story.
# (href, label, sprite-key, title) — title becomes the hover tooltip, HTML-escaped.
DOORS = [
    ("/now/", "the cockpit", "cockpit", "Today's live instrument — your daily numbers, read back to you"),
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

    `current_door` is the door path ("/now/" "/data/" "/coaching/" "/protocols/"
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


def site_footer() -> str:
    """The canonical `.site-foot` footer — one site map on every page.

    Based on the dominant footer (the ~51 data/method/protocols pages) but unified
    UP for the coaching column: it carries the FULLER "The Coaching" set (The Read /
    By Coach / Scorecard / The Team / AI lab notes) so no live coaching link is lost
    site-wide, and it fixes the dominant footer's mislabel (/coaching/ is "The Read",
    /coaching/team/ is "The Team"). Additive for the dominant pages (#1009 review).
    """
    return (
        '<footer class="site-foot"><nav class="site-foot-cols" aria-label="Site map">'
        '<div class="sf-col"><p class="sf-h label">The Story</p>'
        '<a href="/story/chronicle/">Chronicle</a><a href="/story/panel/">Podcast</a>'
        '<a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a>'
        '<a href="/story/about/">About</a></div>'
        '<div class="sf-col"><p class="sf-h label">The Data</p>'
        '<a href="/data/">All topics</a><a href="/method/ask/">Ask the data</a>'
        '<a href="/data/labs/">Labs</a><a href="/data/training/">Training</a>'
        '<a href="/data/sleep/">Sleep</a></div>'
        '<div class="sf-col"><p class="sf-h label">The Protocols</p>'
        '<a href="/protocols/">All protocols</a><a href="/protocols/supplements/">Supplements</a>'
        '<a href="/protocols/experiments/">Experiments</a><a href="/protocols/challenges/">Challenges</a></div>'
        '<div class="sf-col"><p class="sf-h label">The Coaching</p>'
        '<a href="/coaching/">The Read</a><a href="/coaching/by-coach/">By Coach</a>'
        '<a href="/coaching/scorecard/">Scorecard</a><a href="/coaching/team/">The Team</a>'
        '<a href="/coaching/lab-notes/">AI lab notes</a></div>'
        '<div class="sf-col"><p class="sf-h label">Follow &amp; context</p>'
        '<a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a>'
        '<a href="/method/">The method</a><a href="/story/about/">About</a>'
        '<a href="/privacy/">Privacy</a></div>'
        '</nav><p class="sf-base label"><span>averagejoematt</span><a href="/">← home</a></p></footer>'
    )
