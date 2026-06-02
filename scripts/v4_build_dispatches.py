#!/usr/bin/env python3
"""
v4_build_dispatches.py — generate Door 2's narrative sub-pages (/dispatches/).

The slower "overlay of what's going on" — the writing and context, distinct
from the real-time data in the Cockpit/Evidence. Emits an app shell at
site/dispatches/index.html AND a per-section shell at
site/dispatches/<section>/index.html (same app, pre-selected section) so the
sub-page URLs and old-URL redirects resolve on static hosting. The section list
is defined in assets/js/dispatches.js; the shell only embeds
window.__DISPATCH_START__. Reuses the dx-* master-detail styles from story.css.

Read-only; writes only under site/dispatches/. Run from repo root:
    python3 scripts/v4_build_dispatches.py
"""
from __future__ import annotations

from pathlib import Path

OUT = Path("site/dispatches")

# key, label, one-line description (for the per-section <meta>/<title>)
SECTIONS = [
    ("chronicle", "Chronicle", "The weekly chronicle, written by Elena Voss."),
    ("lab-notes", "AI lab notes", "What the AI saw each week, and how it actually felt — the Third Wall, archived."),
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
  <link rel="canonical" href="https://averagejoematt.com/dispatches/{canon}">
  <link rel="icon" href="/favicon.ico">
  <link rel="alternate" type="application/rss+xml" title="averagejoematt" href="/rss.xml">
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <script>(function(){{try{{var t=localStorage.getItem("ajm-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
</head>
<body class="dx-page">
  <a class="skip" href="#dx">Skip to the dispatches</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">dispatches</span></a>
    <nav class="doors" aria-label="Doors">
      <a href="/now/">the cockpit</a>
      <a href="/">the story</a>
      <a href="/evidence/">the evidence</a>
      <button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
    </nav>
  </header>
  <main id="dx" class="dx-main">
    <div class="dx-head">
      <p class="beat-kicker label">dispatches · the writing &amp; the context</p>
      <h1 class="dx-h1">Dispatches</h1>
      <p class="dx-lede">The slower layer — the chronicle, the AI's weekly lab notes, the journal, the timeline, and what this whole experiment is for. The data lives in <a href="/now/">the cockpit</a> and <a href="/evidence/">the evidence</a>; this is the why.</p>
    </div>
    <nav class="dx-tabs" data-dx-tabs aria-label="Dispatch sections"></nav>
    <div class="dx-layout">
      <ul class="dx-list" data-dx-list aria-label="Entries"></ul>
      <article class="dx-read" data-dx-read></article>
    </div>
  </main>
  <footer class="dx-foot-bar"><span class="label">averagejoematt · dispatches</span>
    <span class="label"><a href="/">← the story</a></span></footer>
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
    write(OUT / "index.html", SHELL.format(
        title="Dispatches — averagejoematt",
        desc="The chronicle, the AI's weekly lab notes, the journal, the timeline, and the context behind the experiment.",
        canon="", start="chronicle"))
    # per-section sub-pages
    for key, label, desc in SECTIONS:
        write(OUT / key / "index.html", SHELL.format(
            title=f"{label} — Dispatches — averagejoematt",
            desc=desc, canon=f"{key}/", start=key))
    print(f"✅ wrote site/dispatches/index.html + {len(SECTIONS)} section shells: " + ", ".join(k for k, _, _ in SECTIONS))


if __name__ == "__main__":
    main()
