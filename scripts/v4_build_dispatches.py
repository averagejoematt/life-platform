#!/usr/bin/env python3
"""
v4_build_dispatches.py — generate "The Story" hub: the writing sub-pages (/story/).

CHROME NOTE (#1009): the `<nav class="doors">` and `<footer class="site-foot">` emitted
inline below are NOT the source of truth — `scripts/v4_apply_chrome.py` re-flattens them
to `scripts/v4_chrome.py` on every deploy (it runs last in `deploy/sync_site_to_s3.sh`).
Edit the doors nav / footer in `v4_chrome.py`, not here; the inline copy here will be
normalized away.

"The Story" is the writing/context — the chronicle, AI lab notes, journal,
timeline, and about — distinct from the real-time data (Cockpit/Evidence) and
from the separate cinematic landing at "/". Emits an app shell at
site/story/index.html AND a per-section shell at site/story/<section>/index.html
(same app, pre-selected section) so the sub-page URLs and old-URL redirects
resolve on static hosting. The section list is defined in assets/js/dispatches.js;
the shell only embeds window.__DISPATCH_START__. Reuses the dx-* styles from
story.css.

Read-only; writes only under site/story/. Run from repo root:
    python3 scripts/v4_build_dispatches.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v4_kit import loop_ribbon  # noqa: E402  — shared .loop-ribbon (#578)
from v4_proof import chronicle_list_html, load_chronicle, load_chronicle_pending  # noqa: E402  — #730/#803 static proof

OUT = Path("site/story")

# key, label, one-line description (for the per-section <meta>/<title>).
# NB: this list drives which SHELLS are emitted; the visible sub-nav tab list lives in
# assets/js/dispatches.js — the two must carry the same keys (a shell whose key the JS
# doesn't know renders the default section).
SECTIONS = [
    ("chronicle", "Chronicle", "The weekly chronicle, written by Elena Voss."),
    # "The Coaches" + "AI lab notes" moved to their own door /coaching/ (2026-06-20).
    ("panel", "Podcast", "A weekly two-host show — Elena and a rotating coach review the week."),
    ("journal", "In my own words", "The daily journal, first-person."),
    ("timeline", "Timeline", "Level-ups and milestones — the journey so far."),
    # #380: engineering exhaust, distilled — merged + deployed work only.
    # #1110: `unlisted: true` in dispatches.js — OUT of the story sub-nav (the footer's
    # "The Technology" column links it); the entry stays HERE so /story/build/ keeps
    # regenerating (URL unchanged — pinned by tests/test_build_dispatches.py).
    ("build", "Build log", "Engineering dispatches — what shipped, why it mattered, the gotcha, the honest miss."),
    ("about", "About", "The experiment, in context."),
]

# #1237: per-section OG card. The og-image sweep (lambdas/web/og_image_lambda.py PAGES)
# draws a fresh card daily for these story sections; point each section's social preview
# at its own card instead of the generic home card so the link preview carries real
# topic framing. Sections without a bespoke card fall through to og-home.png.
# Mapping rationale: chronicle→the weekly-dispatches card, build→the "For Builders" card,
# timeline→the "walk the journey one week at a time" weekly card. Regression guard:
# tests/test_og_card_coverage.py (every card in PAGES must be referenced non-legacy).
OG_CARD_BY_SECTION = {
    "chronicle": "og-chronicle.png",
    "build": "og-builders.png",
    "timeline": "og-weekly.png",
}
DEFAULT_OG_CARD = "og-home.png"

SHELL = """<!DOCTYPE html>
<html lang="en" data-door="story">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="https://averagejoematt.com/story/{canon}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com/story/{canon}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/{og_card}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{desc}">
  <meta name="theme-color" media="(prefers-color-scheme: light)" content="#F4EFE4">
  <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0E0C08">
  <link rel="icon" href="/favicon.ico">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Measured Life">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <!-- PWA island (#1020): /story/ is OUTSIDE the cockpit-PWA island (home + /cockpit/ + /coaching/) —
       long-form reading has no daily-return offline case, so these shells do NOT register sw.js. -->
  <link rel="alternate" type="application/rss+xml" title="averagejoematt" href="/rss.xml">
  <link rel="alternate" type="application/rss+xml" title="The Measured Life — read aloud (podcast)" href="/podcast/feed.xml">
  <link rel="alternate" type="application/rss+xml" title="The Measured Life — The Panel (podcast)" href="/panelcast/feed.xml">
    <link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/v4/6NU78FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0KxC9TeP2Xz5c.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
  <script>(function(){{try{{if(!("IntersectionObserver" in window))return;if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;document.documentElement.classList.add("mo");window.__moFail=setTimeout(function(){{document.documentElement.classList.remove("mo");}},2600);}}catch(e){{}}}})();</script>
</head>
<body class="dx-page">
  <a class="skip" href="#dx">Skip to the story</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the story</span></a>
    <nav class="doors" aria-label="Doors">
      <a href="/cockpit/" title="Today's live instrument — your daily numbers, read back to you"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-cockpit"></use></svg>the cockpit</a>
      <a href="/data/" title="Every source the platform reads — trends now and over time"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-data"></use></svg>the data</a>
      <a href="/coaching/" title="The AI team &amp; their arguments — stances, track records, disagreements"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-coaching"></use></svg>the coaching</a>
      <a href="/protocols/" title="The levers — supplements, experiments, challenges, discoveries"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-protocols"></use></svg>the protocols</a>
      <a href="/story/" aria-current="page" title="The writing &amp; the why — chronicle, journal, timeline, about"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-story"></use></svg>the story</a>
      <a href="/subscribe/" class="nav-follow" aria-label="Follow the experiment">follow</a><button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
    </nav>
  </header>
  <main id="dx" class="dx-main">
    <div class="page-hero">
      <p class="ph-kicker label">the story · the writing &amp; the context</p>
      <p class="hero-day label" data-bind="genesisStamp" hidden></p>
      <h1 class="ph-title">The Story</h1>
      <p class="ph-promise">The chronicle, the journal, the timeline, and what this whole experiment is for. The live data lives in <a href="/cockpit/">the cockpit</a> and <a href="/data/">the data</a>, the AI team in <a href="/coaching/">the coaching</a>; this is the why.</p>
      {ribbon}
    </div>
    {proof}
    <nav class="dx-tabs" data-dx-tabs aria-label="Story sections"></nav>
    <div class="dx-layout">
      <ul class="dx-list" data-dx-list aria-label="Entries"></ul>
      <article class="dx-read" data-dx-read></article>
    </div>
  </main>
  <footer class="site-foot">
    <nav class="site-foot-cols" aria-label="Site map">
      <div class="sf-col"><p class="sf-h label">The Story</p>
        <a href="/story/chronicle/">Chronicle</a><a href="/story/panel/">Podcast</a><a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a><a href="/story/about/">About</a></div>
      <div class="sf-col"><p class="sf-h label">The Coaching</p>
        <a href="/coaching/">The Team</a><a href="/coaching/lab-notes/">AI lab notes</a></div>
      <div class="sf-col"><p class="sf-h label">The Data</p>
        <a href="/data/">All topics</a><a href="/method/ask/">Ask the data</a><a href="/data/labs/">Labs</a><a href="/data/training/">Training</a><a href="/data/sleep/">Sleep</a></div>
      <div class="sf-col"><p class="sf-h label">The Protocols</p>
        <a href="/protocols/">All protocols</a><a href="/protocols/supplements/">Supplements</a><a href="/protocols/experiments/">Experiments</a><a href="/protocols/challenges/">Challenges</a></div>
      <div class="sf-col"><p class="sf-h label">Follow &amp; context</p>
        <a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a><a href="/method/">The method</a><a href="/story/about/">About</a><a href="/privacy/">Privacy</a></div>
    </nav>
    <p class="sf-base label"><span>averagejoematt · the story</span><a href="/">← home</a></p>
  </footer>
  <script>window.__DISPATCH_START__ = "{start}";</script>
  <script src="/assets/js/motion.js" defer></script>
  <script type="module" src="/assets/js/dispatches.js"></script>
</body>
</html>
"""

# #578 — inline the shared loop-ribbon once (constant for this door) before the
# per-page .format() calls, so the spine can't drift from the other builders.
SHELL = SHELL.replace("{ribbon}", loop_ribbon("story"))


def write(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def main() -> None:
    # #730: bake the dated chronicle post list into the served HTML (noscript) so the
    # best writing is crawlable/greppable, not locked behind JS. Shown on the hub
    # (which defaults to the chronicle view) and the /story/chronicle/ sub-page.
    # #803: also bakes an honest "why didn't this week land" disclosure — a currently
    # withheld week and/or a break in the Week-N numbering — instead of a silent skip.
    chronicle_proof = chronicle_list_html(load_chronicle(), pending=load_chronicle_pending())

    # hub (defaults to chronicle)
    write(
        OUT / "index.html",
        SHELL.format(
            title="The Story — averagejoematt",
            desc="The chronicle, the journal, the timeline, and the context behind the experiment.",
            canon="",
            start="chronicle",
            og_card=DEFAULT_OG_CARD,  # the /story/ hub is the general landing — keep the brand home card
            proof=chronicle_proof,
        ),
    )
    # per-section sub-pages
    for key, label, desc in SECTIONS:
        write(
            OUT / key / "index.html",
            SHELL.format(
                title=f"{label} — The Story — averagejoematt",
                desc=desc,
                canon=f"{key}/",
                start=key,
                og_card=OG_CARD_BY_SECTION.get(key, DEFAULT_OG_CARD),
                proof=chronicle_proof if key == "chronicle" else "",
            ),
        )
    print(f"✅ wrote site/story/index.html + {len(SECTIONS)} section shells: " + ", ".join(k for k, _, _ in SECTIONS))


if __name__ == "__main__":
    main()
