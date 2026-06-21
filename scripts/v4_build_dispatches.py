#!/usr/bin/env python3
"""
v4_build_dispatches.py — generate "The Story" hub: the writing sub-pages (/story/).

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

from pathlib import Path

OUT = Path("site/story")

# key, label, one-line description (for the per-section <meta>/<title>)
SECTIONS = [
    ("chronicle", "Chronicle", "The weekly chronicle, written by Elena Voss."),
    # "The Coaches" + "AI lab notes" moved to their own door /coaching/ (2026-06-20).
    ("panel", "Podcast", "A weekly two-host show — Elena and a rotating coach review the week."),
    ("journal", "In my own words", "The daily journal, first-person."),
    ("timeline", "Timeline", "Level-ups and milestones — the journey so far."),
    ("about", "About", "The experiment, in context."),
]

SHELL = """<!DOCTYPE html>
<html lang="en" data-door="story">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="https://averagejoematt.com/story/{canon}">
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
  <link rel="alternate" type="application/rss+xml" title="The Measured Life — read aloud (podcast)" href="/podcast/feed.xml">
  <link rel="alternate" type="application/rss+xml" title="The Measured Life — The Panel (podcast)" href="/panelcast/feed.xml">
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
</head>
<body class="dx-page">
  <a class="skip" href="#dx">Skip to the story</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the story</span></a>
    <nav class="doors" aria-label="Doors">
      <a href="/now/">the cockpit</a>
      <a href="/story/" aria-current="page">the story</a>
      <a href="/coaching/">the coaching</a>
      <a href="/evidence/">the evidence</a>
      <button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
    </nav>
  </header>
  <main id="dx" class="dx-main">
    <div class="dx-head">
      <p class="beat-kicker label">the story · the writing &amp; the context</p>
      <p class="hero-day label" data-bind="genesisStamp" hidden></p>
      <h1 class="dx-h1">The Story</h1>
      <p class="dx-lede">The chronicle, the journal, the timeline, and what this whole experiment is for. The live data lives in <a href="/now/">the cockpit</a> and <a href="/evidence/">the evidence</a>, the AI team in <a href="/coaching/">the coaching</a>; this is the why.</p>
    </div>
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
      <div class="sf-col"><p class="sf-h label">The Evidence</p>
        <a href="/evidence/">All topics</a><a href="/evidence/board/">The board</a><a href="/evidence/labs/">Labs</a><a href="/evidence/training/">Training</a><a href="/evidence/nutrition/">Nutrition</a></div>
      <div class="sf-col"><p class="sf-h label">The Cockpit</p>
        <a href="/now/">Live data</a><a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a></div>
      <div class="sf-col"><p class="sf-h label">Context</p>
        <a href="/evidence/methodology/">Methodology</a><a href="/story/about/">About the experiment</a><a href="/privacy/">Privacy</a></div>
    </nav>
    <p class="sf-base label"><span>averagejoematt · the story</span><a href="/">← home</a></p>
  </footer>
  <script>window.__DISPATCH_START__ = "{start}";</script>
  <script type="module" src="/assets/js/dispatches.js"></script>
</body>
</html>
"""


def write(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def main() -> None:
    # hub (defaults to chronicle)
    write(
        OUT / "index.html",
        SHELL.format(
            title="The Story — averagejoematt",
            desc="The chronicle, the journal, the timeline, and the context behind the experiment.",
            canon="",
            start="chronicle",
        ),
    )
    # per-section sub-pages
    for key, label, desc in SECTIONS:
        write(OUT / key / "index.html", SHELL.format(title=f"{label} — The Story — averagejoematt", desc=desc, canon=f"{key}/", start=key))
    print(f"✅ wrote site/story/index.html + {len(SECTIONS)} section shells: " + ", ".join(k for k, _, _ in SECTIONS))


if __name__ == "__main__":
    main()
