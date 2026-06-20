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

from pathlib import Path

OUT = Path("site/coaching")

# key, label, one-line description (for the per-section <meta>/<title>)
SECTIONS = [
    ("coaches", "The Team", "The AI team reading the data — each coach's stance, report card, and the team's collective read."),
    (
        "lab-notes",
        "AI lab notes",
        "What the AI saw each week, and how it actually felt — the Third Wall, the AI's read against Matthew's response.",
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
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
</head>
<body class="dx-page">
  <a class="skip" href="#dx">Skip to the coaching</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the coaching</span></a>
    <nav class="doors" aria-label="Doors">
      <a href="/now/">the cockpit</a>
      <a href="/story/">the story</a>
      <a href="/coaching/" aria-current="page">the coaching</a>
      <a href="/evidence/">the evidence</a>
      <button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
    </nav>
  </header>
  <main id="dx" class="dx-main">
    <div class="dx-head">
      <p class="beat-kicker label">the coaching · the AI team reading the data</p>
      <h1 class="dx-h1">The Coaching</h1>
      <p class="dx-lede">A board of named AI coaches reads the data and argues about it — each with a stance, a track record, and a voice. The weekly lab notes are the Third Wall: the AI's read against how it actually felt. The live data lives in <a href="/now/">the cockpit</a> and <a href="/evidence/">the evidence</a>; the writing's in <a href="/story/">the story</a>.</p>
    </div>
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
        <a href="/coaching/">The Team</a><a href="/coaching/lab-notes/">AI lab notes</a></div>
      <div class="sf-col"><p class="sf-h label">The Evidence</p>
        <a href="/evidence/">All topics</a><a href="/evidence/board/">The board</a><a href="/evidence/labs/">Labs</a><a href="/evidence/training/">Training</a><a href="/evidence/nutrition/">Nutrition</a></div>
      <div class="sf-col"><p class="sf-h label">The Cockpit</p>
        <a href="/now/">Live data</a><a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a></div>
      <div class="sf-col"><p class="sf-h label">Context</p>
        <a href="/evidence/methodology/">Methodology</a><a href="/story/about/">About the experiment</a><a href="/privacy/">Privacy</a></div>
    </nav>
    <p class="sf-base label"><span>averagejoematt · the coaching</span><a href="/">← home</a></p>
  </footer>
  <script>window.__COACHING_START__ = "{start}";</script>
  <script type="module" src="/assets/js/coaching.js"></script>
</body>
</html>
"""


def write(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def main() -> None:
    write(
        OUT / "index.html",
        SHELL.format(
            title="The Coaching — averagejoematt",
            desc="The AI team reading the data — each coach's stance and track record, plus the weekly lab notes.",
            canon="",
            start="coaches",
        ),
    )
    for key, label, desc in SECTIONS:
        write(
            OUT / key / "index.html", SHELL.format(title=f"{label} — The Coaching — averagejoematt", desc=desc, canon=f"{key}/", start=key)
        )
    print(f"✅ wrote site/coaching/index.html + {len(SECTIONS)} section shells: " + ", ".join(k for k, _, _ in SECTIONS))


if __name__ == "__main__":
    main()
