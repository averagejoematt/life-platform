#!/usr/bin/env python3
"""
v4_build_coaching.py — generate Door 4 "The Coaching" (/coaching/).

CHROME NOTE (#1009): the `<nav class="doors">` and `<footer class="site-foot">` emitted
inline below are NOT the source of truth — `scripts/v4_apply_chrome.py` re-flattens them
to `scripts/v4_chrome.py` on every deploy (it runs last in `deploy/sync_site_to_s3.sh`).
Edit the doors nav / footer in `v4_chrome.py`, not here; the inline copy here will be
normalized away.

Promoted out of the Story tabs (2026-06-20, Option A) into its own top-level door:
the AI team that reads the data — "My Team" → each coach (master-detail) → the weekly
lab notes ("What the AI said, and how it felt"). Emits an app shell at site/coaching/index.html AND a
per-section shell at site/coaching/<section>/index.html (same app, pre-selected
section) so sub-page URLs + old /story/coaches redirects resolve on static hosting.
The section list lives in assets/js/coaching.js; the shell embeds
window.__COACHING_START__. Reuses the dx- and coach- styles from story.css.

#4182/#4188 (the first screen): the hub and /coaching/read/ carry a [data-coach-today]
mount directly under the hero — coaching.js renders ONE coach read there, dated in words,
then the week's call labelled weekly, where they disagree, and the other coaches one line
each. The hero's promise is the 11-word definition, its numeral derived from the persona
registry's operational roster (never typed); the portraits disclaimer sits below the
first screen.

Read-only; writes only under site/coaching/. Run from repo root:
    python3 scripts/v4_build_coaching.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))
import v4_apply_chrome as _apply_chrome  # noqa: E402 — the post-build chrome normalizer (#3721)
from coach import persona_registry  # noqa: E402 — #4182: the roster count the hero states
from v4_kit import loop_ribbon  # noqa: E402  — shared .loop-ribbon (#578)
from v4_proof import (  # noqa: E402  — #729/#730/#804 static proof + #1395 data-driven OG
    coaching_og,
    coaching_read_block_html,
    load_coaching_read,
    load_scorecard,
    scorecard_block_html,
)

_OG_HOME = "https://averagejoematt.com/assets/images/og-home.png"

OUT = Path("site/coaching")

# key, label, one-line description (for the per-section <meta>/<title>)
# 2026-06-28 commentary-first re-cut (COACHING_SECTION_REVIEW): read-first, roster demoted.
SECTIONS = [
    (
        "read",
        "The Read",
        "What the AI board is saying about the data right now — today and this week, the disagreements, and each coach's live read.",
    ),
    (
        "by-coach",
        "By Coach",
        "Each coach's read on a domain, on top of the actual data — cardio, lifts, volume, sleep, glucose — this week.",
    ),
    (
        "scorecard",
        "Scorecard",
        "The board's falsifiable track record — every call the coaches make, graded confirmed/refuted/open by a deterministic evaluator.",
    ),
    ("team", "The Team", "Who the coaches are — their personalities, voice, and how each one is built."),
    # #4182 (panel ruling vii-8): "the Third Wall" is cut from reader surfaces; the URL stays.
    (
        "lab-notes",
        "What the AI said, and how it felt",
        "What the AI read in each week's numbers, set beside how the week actually felt to Matthew.",
    ),
    (
        "qa",
        "Reader Q&A",
        "Ask the AI board a question — and read the ones it has answered. Matthew picks a selection and the board responds.",
    ),
]

SHELL = """<!DOCTYPE html>
<html lang="en" data-door="coaching">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="https://averagejoematt.com/coaching/{canon}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com/coaching/{canon}">
  <meta property="og:title" content="{og_title}">
  <meta property="og:description" content="{og_desc}">
  <meta property="og:image" content="{og_image}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{og_title}">
  <meta name="twitter:description" content="{og_desc}">
  <meta name="theme-color" media="(prefers-color-scheme: light)" content="#F4EFE4">
  <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0E0C08">
  <link rel="icon" href="/favicon.ico">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Measured Life">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <!-- PWA island (#1020): /coaching/ is INSIDE the cockpit-PWA island (home + /cockpit/ + /coaching/) —
       the daily check-in loop — so these shells deliberately register sw.js. -->
  <script src="/assets/js/boot_sw.js"></script>
  <link rel="alternate" type="application/rss+xml" title="averagejoematt" href="/rss.xml">
    <link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/v4/6NU78FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0KxC9TeP2Xz5c.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script src="/assets/js/boot_theme.js"></script>
  <script src="/assets/js/boot_motion.js"></script>
</head>
<body class="dx-page">
  <a class="skip" href="#dx">Skip to the coaching</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the coaching</span></a>
    <nav class="doors" aria-label="Doors">
      <a href="/cockpit/" title="Today's live instrument — your daily numbers, read back to you"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-cockpit"></use></svg>the cockpit</a>
      <a href="/data/" title="Every source the platform reads — trends now and over time"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-data"></use></svg>the data</a>
      <a href="/coaching/" aria-current="page" title="The AI team &amp; their arguments — stances, track records, disagreements"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-coaching"></use></svg>the coaching</a>
      <a href="/protocols/" title="The levers — supplements, experiments, challenges, discoveries"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-protocols"></use></svg>the protocols</a>
      <a href="/story/" title="The writing &amp; the why — chronicle, journal, timeline, about"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-story"></use></svg>the story</a>
      <button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
    </nav>
  </header>
  <main id="dx" class="dx-main">
    <div class="page-hero">
      <p class="ph-kicker label">the coaching<span data-bind="coachingDay" hidden></span></p>
      <h1 class="ph-title">The Coaching</h1>
      <p class="ph-promise">{roster_word} AI characters, software not people, read his numbers every morning.</p>
      {ribbon}
    </div>
    {proof}{today}
    <p class="dx-foot label">Coach portraits are commissioned illustrations of openly fictional AI personas — no real people are depicted.</p>
    <nav class="dx-tabs" data-dx-tabs aria-label="Coaching sections"></nav>
    <div class="dx-layout">
      <ul class="dx-list" data-dx-list aria-label="Entries"></ul>
      <!-- #3548: div, not article — tabs.js::markActiveTab assigns role="tabpanel" to
           this element, and <article>'s implicit strong native semantics don't permit
           that role override (axe aria-allowed-role). A <div> allows any role. -->
      <div class="dx-read" data-dx-read></div>
    </div>
  </main>
  <footer class="site-foot">
    <nav class="site-foot-cols" aria-label="Site map">
      <div class="sf-col"><p class="sf-h label">The Story</p>
        <a href="/story/chronicle/">Chronicle</a><a href="/story/panel/">Podcast</a><a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a><a href="/story/about/">About</a></div>
      <div class="sf-col"><p class="sf-h label">The Coaching</p>
        <a href="/coaching/">The Read</a><a href="/coaching/by-coach/">By Coach</a><a href="/coaching/scorecard/">Scorecard</a><a href="/coaching/team/">The Team</a><a href="/coaching/lab-notes/">AI lab notes</a></div>
      <div class="sf-col"><p class="sf-h label">The Data</p>
        <a href="/data/">All topics</a><a href="/method/ask/">Ask the data</a><a href="/data/labs/">Labs</a><a href="/data/training/">Training</a><a href="/data/sleep/">Sleep</a></div>
      <div class="sf-col"><p class="sf-h label">The Protocols</p>
        <a href="/protocols/">All protocols</a><a href="/protocols/supplements/">Supplements</a><a href="/protocols/experiments/">Experiments</a><a href="/protocols/challenges/">Challenges</a></div>
      <div class="sf-col"><p class="sf-h label">Follow &amp; context</p>
        <a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a><a href="/method/">The method</a><a href="/story/about/">About</a><a href="/privacy/">Privacy</a></div>
    </nav>
    <p class="sf-base label"><span>averagejoematt · the coaching</span><a href="/">← home</a></p>
  </footer>
  <script type="application/json" id="page-data">{{"start": "{start}"}}</script>
  <script src="/assets/js/motion.js" defer></script>
  <script type="module" src="/assets/js/coaching.js"></script>
</body>
</html>
"""

# #578 — inline the shared loop-ribbon once (constant for this door) before the
# per-page .format() calls, so the spine can't drift from the other builders.
SHELL = SHELL.replace("{ribbon}", loop_ribbon("coaching"))

# #4182: the first-screen mount — emitted on the hub and /coaching/read/ only (the two
# shells whose default view IS the read); every other section opens on its own content.
TODAY_MOUNT = '\n    <div class="coach-today" data-coach-today aria-live="polite" hidden></div>'

_NUMBER_WORDS = {n: w for n, w in enumerate("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve".split())}


def roster_size() -> int:
    """The served roster's size — the SAME composition /api/coaches serves
    (site_api_coach_profile.handle_coaches): every operational persona, plus the lead who
    chairs when the registry marks one. Derived, never typed: the panel's draft said
    "seven" when the served roster was eight (#4182 §3)."""
    ops = persona_registry.operational_personas()
    lead = persona_registry.lead_persona()
    has_lead = bool(lead.get("lead")) and persona_registry.LEAD_PERSONA_ID not in ops
    return len(ops) + (1 if has_lead else 0)


def roster_word() -> str:
    """roster_size(), in words, for the hero's promise line."""
    n = roster_size()
    if n < 1:
        raise SystemExit("v4_build_coaching: the persona registry has no operational roster — refusing to print a count")
    return _NUMBER_WORDS.get(n, str(n))


def write(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _apply_chrome.write_page(path, html_text)  # #3721


def main() -> None:
    # #729/#730: bake the scorecard's honest empty-state + counts into the served
    # HTML (noscript) so a crawler / LLM / no-JS skeptic sees the falsifiable track
    # record, not an empty shell. JS still renders the rich interactive scorecard.
    scorecard_proof = scorecard_block_html(load_scorecard())
    # #804 (R22-UX-02): bake the board's actual read — the weekly priority + each
    # coach's live read — into the "read" landing (the default section) so a no-JS
    # visitor / crawler / LLM / the first seconds before scripts load sees the site's
    # core differentiator (the coach voices), not an empty shell. JS still renders the
    # rich interactive read. Falls back to the committed snapshot when offline.
    read = load_coaching_read()
    read_proof = coaching_read_block_html(read)
    # #1395: the /coaching/ HUB carries a data-driven OG (the pre-start convene date, or
    # the live read's stamp) instead of the generic boilerplate. Section shells keep the
    # topical title/desc + the generic home card.
    hub_og = coaching_og(read)
    word = roster_word()

    write(
        OUT / "index.html",
        SHELL.format(
            title="The Coaching — averagejoematt",
            desc="What the AI board is saying about the data right now — the read, by coach, the disagreements, and the weekly lab notes.",
            canon="",
            start="read",
            proof=read_proof,
            today=TODAY_MOUNT,
            roster_word=word,
            og_title=hub_og[("property", "og:title")],
            og_desc=hub_og[("property", "og:description")],
            og_image=hub_og[("property", "og:image")],
        ),
    )
    for key, label, desc in SECTIONS:
        if key == "read":
            proof = read_proof
        elif key == "scorecard":
            proof = scorecard_proof
        else:
            proof = ""
        section_title = f"{label} — The Coaching — averagejoematt"
        write(
            OUT / key / "index.html",
            SHELL.format(
                title=section_title,
                desc=desc,
                canon=f"{key}/",
                start=key,
                proof=proof,
                today=TODAY_MOUNT if key == "read" else "",
                roster_word=word,
                og_title=section_title,
                og_desc=desc,
                og_image=_OG_HOME,
            ),
        )
    print(f"✅ wrote site/coaching/index.html + {len(SECTIONS)} section shells: " + ", ".join(k for k, _, _ in SECTIONS))


if __name__ == "__main__":
    main()
