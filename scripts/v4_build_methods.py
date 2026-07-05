#!/usr/bin/env python3
"""v4_build_methods.py — generate /method/registry/ from lambdas/methods_registry.py (#544).

The Methods page: every statistic the platform publishes, with its formula, the
window it runs over, and its known limitations — rendered straight from
`lambdas/methods_registry.py`, never hand-authored, so the page cannot silently drift
from the code (ADR-105). Same registry backs the machine-readable `/api/methods`
endpoint (`lambdas/web/site_api_lambda.py::handle_methods`).

Deliberately standalone — its own builder, its own static HTML, no client-side JS
dependency. `evidence.js` (the shared /data//protocols//method/ engine) is mid-refactor
(#581); this page does not touch it and is not wired into its REGISTRY, so it can ship
independently. The page borrows the same visual chrome (fonts/tokens/doors/footer) as
the other /method/ pages purely by copying the same static markup — no shared code
path with v4_build_evidence.py.

Run from repo root:  python3 scripts/v4_build_methods.py
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from methods_registry import SOURCE_MODULES, list_categories, list_stats  # noqa: E402

SLUG = "registry"
CANONICAL = f"/method/{SLUG}/"
TITLE = "The Methods Registry — The Method — averagejoematt"
DESCRIPTION = "Every statistic the platform publishes — formula, window, and known limitations — generated straight from the code."


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# ── Shared site chrome. Copied (not imported) from scripts/v4_build_evidence.py so
# this page has zero coupling to that file or to evidence.js while it's mid-refactor
# (#581) — a deliberate, small duplication in exchange for independence. ──────────
FONTS = (
    '<link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/6NU58FyLNQOQZAnv9ZwNjucMHVn85Ni7emAe9lKqZTnbB-gzTK0K1ChjeveQ7ZXk8g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="stylesheet" href="/assets/css/fonts.css">'
)
THEME = (
    '<script>(function(){try{var t=localStorage.getItem("ajm-theme");'
    'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}})();</script>'
)
MOTION_HEAD = (
    '<script>(function(){try{if(!("IntersectionObserver" in window))return;'
    'if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;'
    'document.documentElement.classList.add("mo");'
    'window.__moFail=setTimeout(function(){document.documentElement.classList.remove("mo");},2600);}catch(e){}})();</script>'
)
MOTION_SCRIPT = '<script src="/assets/js/motion.js" defer></script>'
DOORS = [
    ("/now/", "the cockpit", "cockpit", "Today's live instrument — your daily numbers, read back to you"),
    ("/data/", "the data", "data", "Every source the platform reads — trends now and over time"),
    ("/coaching/", "the coaching", "coaching", "The AI team & their arguments — stances, track records, disagreements"),
    ("/protocols/", "the protocols", "protocols", "The levers — supplements, experiments, challenges, discoveries"),
    ("/story/", "the story", "story", "The writing & the why — chronicle, journal, timeline, about"),
]


def door_icon(key: str) -> str:
    return f'<svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-door-{key}"></use></svg>'


def topbar(active_key: str) -> str:
    links = "".join(
        f'<a href="{href}" title="{esc(title)}"{" aria-current=\"page\"" if key == active_key else ""}>{door_icon(key)}{label}</a>'
        for href, label, key, title in DOORS
    )
    return (
        '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
        '<span class="brand-name">averagejoematt</span> <span class="brand-door label">method</span></a>'
        f'<nav class="doors" aria-label="Doors">{links}'
        '<button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button></nav></header>'
    )


FOOTER = (
    '<footer class="site-foot"><nav class="site-foot-cols" aria-label="Site map">'
    '<div class="sf-col"><p class="sf-h label">The Story</p>'
    '<a href="/story/chronicle/">Chronicle</a><a href="/story/panel/">Podcast</a><a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a><a href="/story/about/">About</a></div>'
    '<div class="sf-col"><p class="sf-h label">The Data</p>'
    '<a href="/data/">All topics</a><a href="/method/ask/">Ask the data</a><a href="/data/labs/">Labs</a><a href="/data/training/">Training</a><a href="/data/sleep/">Sleep</a></div>'
    '<div class="sf-col"><p class="sf-h label">The Protocols</p>'
    '<a href="/protocols/">All protocols</a><a href="/protocols/supplements/">Supplements</a><a href="/protocols/experiments/">Experiments</a><a href="/protocols/challenges/">Challenges</a></div>'
    '<div class="sf-col"><p class="sf-h label">The Coaching</p>'
    '<a href="/coaching/">The Team</a><a href="/coaching/lab-notes/">AI lab notes</a></div>'
    '<div class="sf-col"><p class="sf-h label">Follow &amp; context</p>'
    '<a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a><a href="/method/">The method</a><a href="/story/about/">About</a><a href="/privacy/">Privacy</a></div>'
    '</nav><p class="sf-base label"><span>averagejoematt</span><a href="/">← home</a></p></footer>'
)

# Page-specific styling only — scoped under .mr-*, tokens-only (no hardcoded colour/
# spacing), additive per DESIGN_SYSTEM_V5 §3 ("reuse what already exists" first: this
# borrows .rd-sec/.rd-h/.rd-prose/.correlative/.confidence from evidence.css and only
# adds the bits those don't cover — the stat card grid + field labels).
STYLE = """
<style>
.mr-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.mr-cat-head { display: flex; align-items: baseline; gap: var(--sp-3); margin-top: var(--sp-8); }
.mr-cat-head .rd-h { border-top: 0; padding-top: 0; margin-bottom: 0; }
.mr-cat-count { color: var(--ink-faint); font-family: var(--font-mono); font-size: var(--fs-small); }
.mr-grid { display: grid; gap: var(--sp-5); margin-top: var(--sp-4); min-width: 0; }
.mr-stat { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.mr-stat-name { font-family: var(--font-serif); font-weight: var(--weight-med); font-size: var(--fs-h3); color: var(--ink); margin: 0; }
.mr-formula { margin-top: var(--sp-3); padding: var(--sp-3) var(--sp-4); border-radius: var(--radius-xs); background: var(--surface-sunken);
  font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink); line-height: var(--lh-relaxed); overflow-x: auto;
  white-space: pre-wrap; overflow-wrap: break-word; }
.mr-fields { margin-top: var(--sp-4); display: grid; gap: var(--sp-3); }
.mr-field dt { font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--ink-faint); }
.mr-field dd { margin: var(--sp-1) 0 0; color: var(--ink-muted); line-height: var(--lh-relaxed); max-width: var(--measure); }
.mr-source { margin-top: var(--sp-4); font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); }
.mr-source code { color: var(--ink-muted); }
.mr-modules { display: grid; gap: var(--sp-4); margin-top: var(--sp-4); min-width: 0; }
@media (min-width: 640px) { .mr-modules { grid-template-columns: 1fr 1fr; } }
.mr-module { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-4); min-width: 0; }
.mr-module h3 { margin: 0; font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink); }
.mr-module p { margin-top: var(--sp-2); color: var(--ink-muted); font-size: var(--fs-small); line-height: var(--lh-relaxed); }
.mr-module code { color: var(--ink-faint); }
</style>
"""


def _field(label: str, value) -> str:
    if value in (None, ""):
        return ""
    return f'<div class="mr-field"><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>'


def _stat_card(entry: dict) -> str:
    fields = "".join(
        [
            _field("Window", entry.get("window")),
            _field("Limitations", entry.get("limitations")),
            _field("Minimum n", entry.get("min_n")),
            _field("Used by", entry.get("used_by")),
        ]
    )
    return (
        f'<article class="mr-stat" id="stat-{esc(entry["id"])}">'
        f'<h3 class="mr-stat-name">{esc(entry["name"])}</h3>'
        f'<p class="mr-formula">{esc(entry["formula"])}</p>'
        f'<dl class="mr-fields">{fields}</dl>'
        f'<p class="mr-source">source: <code>{esc(entry["module"])}.py::{esc(entry["function"])}</code></p>'
        "</article>"
    )


def _module_card(key: str, mod: dict) -> str:
    return (
        '<div class="mr-module">'
        f'<h3>{esc(mod["title"])} — <code>{esc(mod["path"])}</code></h3>'
        f'<p>{esc(mod["description"])}</p>'
        "</div>"
    )


def render(stats: list[dict], categories: list[str]) -> str:
    by_cat: dict[str, list[dict]] = {c: [] for c in categories}
    for entry in stats:
        by_cat.setdefault(entry["category"], []).append(entry)

    sections = []
    for cat in categories:
        entries = by_cat.get(cat, [])
        if not entries:
            continue
        cards = "".join(_stat_card(e) for e in entries)
        sections.append(
            f'<div class="mr-cat-head"><h2 class="rd-h">{esc(cat)}</h2>'
            f'<span class="mr-cat-count">{len(entries)} stat{"s" if len(entries) != 1 else ""}</span></div>'
            f'<div class="mr-grid">{cards}</div>'
        )
    modules_html = "".join(_module_card(k, m) for k, m in SOURCE_MODULES.items())

    body = f"""<!DOCTYPE html>
<html lang="en" data-door="method">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(TITLE)}</title>
  <meta name="description" content="{esc(DESCRIPTION)}">
  <link rel="canonical" href="https://averagejoematt.com{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com{CANONICAL}">
  <meta property="og:title" content="{esc(TITLE)}">
  <meta property="og:description" content="{esc(DESCRIPTION)}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(TITLE)}">
  <meta name="twitter:description" content="{esc(DESCRIPTION)}">
  <link rel="icon" href="/favicon.ico">
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/evidence.css">
  {STYLE}
  {THEME}
  {MOTION_HEAD}
</head>
<body>
  <a class="skip" href="#mr">Skip to the content</a>
  {topbar("data")}
  <main id="mr">
    <div class="page-hero">
      <p class="ph-kicker label">the method &middot; under the hood</p>
      <h1 class="ph-title">The Methods Registry</h1>
      <p class="ph-promise">Every statistic this platform publishes — its formula, the window it runs over, and what it can't tell you — generated straight from the source modules below, not hand-written. If the code changes, this page is built to go stale until a human re-verifies it (see the fingerprint note).</p>
    </div>
    <div class="mr-wrap">
      <section class="rd-sec" style="margin-top:0">
        <h2 class="rd-h">Where this comes from</h2>
        <p class="rd-prose">Two modules currently back every number here — both pure, deterministic, stdlib-only Python with no AI and no I/O (ADR-105's "deterministic computation before any LLM verdict" rule, made literal).</p>
        <div class="mr-modules">{modules_html}</div>
      </section>
      {"".join(sections)}
      <p class="correlative">This page is generated by <code>scripts/v4_build_methods.py</code> from <code>lambdas/methods_registry.py</code>, the same registry served machine-readably at <code>/api/methods</code>. Each entry records a hash of the function it documents at the time its prose was last verified; a test in <code>tests/test_methods_registry.py</code> fails if the code changes without the entry being reviewed again — so this registry can be incomplete, but it cannot silently lie about a stat it already documents. <span class="confidence conf-low">generated, not authored</span></p>
    </div>
  </main>
  {FOOTER}
  {MOTION_SCRIPT}
</body>
</html>
"""
    return body


def main() -> int:
    stats = list_stats()
    categories = list_categories()
    out_dir = ROOT / "site" / "method" / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render(stats, categories), encoding="utf-8")
    print(f"{CANONICAL}: {len(stats)} stats across {len(categories)} categories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
