#!/usr/bin/env python3
"""
v4_build_coaching.py — generate Door 4 "The Coaching" (/coaching/).

Promoted out of the Story tabs (2026-06-20, Option A) into its own top-level door:
the AI team that reads the data — "My Team" → each coach (master-detail) → the AI
lab notes (the Third Wall). Emits an app shell at site/coaching/index.html AND a
per-section shell at site/coaching/<section>/index.html (same app, pre-selected
section) so sub-page URLs + old /story/coaches redirects resolve on static hosting.
The section list lives in assets/js/coaching.js; the shell embeds
window.__COACHING_START__. Reuses the dx- and coach- styles from story.css.

Read-only; writes only under site/coaching/. Run from repo root:
    python3 scripts/v4_build_coaching.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v4_kit import loop_ribbon  # noqa: E402  — shared .loop-ribbon (#578)
from v4_proof import load_scorecard, scorecard_block_html  # noqa: E402  — #729/#730 static proof

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
    (
        "lab-notes",
        "AI lab notes",
        "What the AI saw each week, and how it actually felt — the Third Wall, the AI's read against Matthew's response.",
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
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">
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
  <script>if("serviceWorker" in navigator){{window.addEventListener("load",function(){{navigator.serviceWorker.register("/sw.js").catch(function(){{}});}});}}</script>
  <link rel="alternate" type="application/rss+xml" title="averagejoematt" href="/rss.xml">
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
  <a class="skip" href="#dx">Skip to the coaching</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the coaching</span></a>
    <nav class="doors" aria-label="Doors">
      <a href="/now/" title="Today's live instrument — your daily numbers, read back to you"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-cockpit"></use></svg>the cockpit</a>
      <a href="/data/" title="Every source the platform reads — trends now and over time"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-data"></use></svg>the data</a>
      <a href="/coaching/" aria-current="page" title="The AI team &amp; their arguments — stances, track records, disagreements"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-coaching"></use></svg>the coaching</a>
      <a href="/protocols/" title="The levers — supplements, experiments, challenges, discoveries"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-protocols"></use></svg>the protocols</a>
      <a href="/story/" title="The writing &amp; the why — chronicle, journal, timeline, about"><svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-story"></use></svg>the story</a>
      <button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
    </nav>
  </header>
  <main id="dx" class="dx-main">
    <div class="page-hero">
      <p class="ph-kicker label">the coaching · the AI team reading the data</p>
      <p class="hero-day label" data-bind="genesisStamp" hidden></p>
      <h1 class="ph-title">The Coaching</h1>
      <p class="ph-promise">A board of named AI coaches reads the data and offers different takes on it. Start with <strong>the read</strong> — what they're saying about you right now — then go <strong>by coach</strong> to see their take sitting on top of the actual numbers. The weekly lab notes are the Third Wall: the AI's read against how it actually felt. Live data lives in <a href="/now/">the cockpit</a> and <a href="/data/">the data</a>.</p>
      {ribbon}
      <p class="dx-foot label">Coach portraits are commissioned illustrations of openly fictional AI personas — no real people are depicted.</p>
    </div>
    {proof}
    <nav class="dx-tabs" data-dx-tabs aria-label="Coaching sections"></nav>
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
  <script>window.__COACHING_START__ = "{start}";</script>
  <script src="/assets/js/motion.js" defer></script>
  <script type="module" src="/assets/js/coaching.js"></script>
</body>
</html>
"""

# #578 — inline the shared loop-ribbon once (constant for this door) before the
# per-page .format() calls, so the spine can't drift from the other builders.
SHELL = SHELL.replace("{ribbon}", loop_ribbon("coaching"))


def write(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def main() -> None:
    # #729/#730: bake the scorecard's honest empty-state + counts into the served
    # HTML (noscript) so a crawler / LLM / no-JS skeptic sees the falsifiable track
    # record, not an empty shell. JS still renders the rich interactive scorecard.
    scorecard_proof = scorecard_block_html(load_scorecard())

    write(
        OUT / "index.html",
        SHELL.format(
            title="The Coaching — averagejoematt",
            desc="What the AI board is saying about the data right now — the read, by coach, the disagreements, and the weekly lab notes.",
            canon="",
            start="read",
            proof="",
        ),
    )
    for key, label, desc in SECTIONS:
        write(
            OUT / key / "index.html",
            SHELL.format(
                title=f"{label} — The Coaching — averagejoematt",
                desc=desc,
                canon=f"{key}/",
                start=key,
                proof=scorecard_proof if key == "scorecard" else "",
            ),
        )
    print(f"✅ wrote site/coaching/index.html + {len(SECTIONS)} section shells: " + ", ".join(k for k, _, _ in SECTIONS))


if __name__ == "__main__":
    main()
