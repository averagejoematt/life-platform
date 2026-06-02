#!/usr/bin/env python3
"""
v4_build_evidence.py — generate Door 3 (The Evidence) from a topic registry.

Emits site/evidence/index.html (archival index, grouped) and
site/evidence/<slug>/index.html for every topic in REGISTRY. Pages are static
and consistent; the shared assets/js/evidence.js does the live, honest readout.

Two modes per topic:
  - "data":    fetches a published /api endpoint and renders the actual data
               (correlative framing applied client-side).
  - "archive": a v4-styled intro that links into the preserved /legacy view
               (used for interactive/meta sections not yet rebuilt bespoke).

Every topic links "deeper →" to its preserved legacy page so nothing is lost.

Read-only inputs; writes only under site/evidence/. Run from repo root:
    python3 scripts/v4_build_evidence.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

OUT = Path("site/evidence")

# slug, title, blurb, group, mode, endpoint, root(json key or None), legacy
REGISTRY = [
    # ── Protocol & inputs ──────────────────────────────────────────────────
    ("nutrition",   "Nutrition",   "Intake, macros, and how the plate tracks against the deficit.", "Protocol & inputs", "data", "/api/observatory_week?domain=nutrition", None, "/legacy/nutrition/"),
    ("training",    "Training",    "The work: sessions, load, and how movement scores accrue.",     "Protocol & inputs", "data", "/api/observatory_week?domain=training",   None, "/legacy/training/"),
    ("sleep",       "Sleep",       "Duration, quality, and the recovery it does (or doesn't) buy.",  "Protocol & inputs", "data", "/api/observatory_week?domain=sleep",      None, "/legacy/sleep/"),
    ("supplements", "Supplements", "What's taken, why, and what the evidence actually supports.",     "Protocol & inputs", "data", "/api/supplements", None, "/legacy/supplements/"),
    ("protocols",   "Protocols",   "Active protocols — the deliberate interventions under test.",     "Protocol & inputs", "data", "/api/protocols", None, "/legacy/protocols/"),
    ("habits",      "Habits",      "The daily adherence layer the consistency pillar is built on.",   "Protocol & inputs", "data", "/api/habits", None, "/legacy/habits/"),
    ("stack",       "The stack",   "The hardware and services feeding the experiment.",               "Protocol & inputs", "archive", None, None, "/legacy/stack/"),
    ("kitchen",     "The kitchen", "How the food actually gets made on a deficit.",                   "Protocol & inputs", "archive", None, None, "/legacy/kitchen/"),
    # ── Body & biomarkers ──────────────────────────────────────────────────
    ("labs",        "Bloodwork",   "Lab panels over time — the inside view the wearables can't see.",  "Body & biomarkers", "data", "/api/labs", None, "/legacy/labs/"),
    ("biology",     "Biology",     "Genome and baseline biology context behind the numbers.",          "Body & biomarkers", "archive", None, None, "/legacy/biology/"),
    ("glucose",     "Glucose",     "Continuous glucose: meal response and metabolic flexibility.",      "Body & biomarkers", "archive", None, None, "/legacy/glucose/"),
    ("physical",    "Physical",    "Body composition, measurements, and the physical trend.",           "Body & biomarkers", "data", "/api/observatory_week?domain=physical", None, "/legacy/physical/"),
    ("mind",        "Mind",        "Mood, stress, and the autonomic picture.",                          "Body & biomarkers", "data", "/api/observatory_week?domain=mind", None, "/legacy/mind/"),
    ("benchmarks",  "Benchmarks",  "Where the numbers sit against age-band and centenarian targets.",   "Body & biomarkers", "archive", None, None, "/legacy/benchmarks/"),
    ("predictions", "Predictions", "The model's forward calls — logged, then scored against reality.",  "Body & biomarkers", "data", "/api/predictions", None, "/legacy/predictions/"),
    # ── Method & machine ───────────────────────────────────────────────────
    ("experiments", "Experiments", "The N=1 instrument: hypotheses run as read-only proof.",            "Method & machine", "data", "/api/experiments", None, "/legacy/experiments/"),
    ("challenges",  "Challenges",  "Time-boxed challenges — read-only here, by design.",                "Method & machine", "archive", None, None, "/legacy/challenges/"),
    ("methodology", "Methodology", "How the scoring, pillars, and confidence rules actually work.",      "Method & machine", "archive", None, None, "/legacy/methodology/"),
    ("intelligence","Intelligence","Cross-source correlations the engine surfaces (correlative only).",  "Method & machine", "data", "/api/correlations", None, "/legacy/intelligence/"),
    ("results",     "Results",     "Outcomes to date — what moved, what didn't.",                       "Method & machine", "archive", None, None, "/legacy/results/"),
    ("cost",        "Cost",        "What running this costs to run — the radical-accessibility receipt.","Method & machine", "archive", None, None, "/legacy/cost/"),
    ("data",        "Data sources","Every source feeding the platform, and its freshness.",             "Method & machine", "archive", None, None, "/legacy/data/"),
    ("platform",    "The platform","The architecture behind the three doors.",                          "Method & machine", "archive", None, None, "/legacy/platform/"),
    ("tools",       "Tools",       "The MCP tools Claude uses to read the data back.",                  "Method & machine", "archive", None, None, "/legacy/tools/"),
    ("explorer",    "Explorer",    "Browse the raw daily record yourself.",                             "Method & machine", "archive", None, None, "/legacy/explorer/"),
    ("ask",         "Ask the data","Put a question to the experiment's data directly.",                 "Method & machine", "archive", None, None, "/legacy/ask/"),
]

GROUP_ORDER = ["Protocol & inputs", "Body & biomarkers", "Method & machine"]

# Self-hosted fonts (CSP: font-src 'self') — never the blocked Google CDN.
FONTS = '<link rel="stylesheet" href="/assets/css/fonts.css">'

THEME_INIT = ('<script>(function(){try{var t=localStorage.getItem("ajm-theme");'
              'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}})();</script>')

TOPBAR = ('<header class="ev-top">\n'
          '    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
          '<span class="brand-name">averagejoematt</span> <span class="brand-door label">evidence</span></a>\n'
          '    <nav class="doors" aria-label="Doors"><a href="/now/">the cockpit</a><a href="/">the story</a>'
          '<button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button></nav>\n'
          '  </header>')


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def index_html() -> str:
    groups = {g: [] for g in GROUP_ORDER}
    for i, t in enumerate(REGISTRY):
        slug, title, blurb, group, mode, *_ = t
        groups.setdefault(group, []).append((i, slug, title, blurb, mode))
    sections = []
    for g in GROUP_ORDER:
        cards = []
        for i, slug, title, blurb, mode in groups.get(g, []):
            tag = "live readout" if mode == "data" else "archive"
            cards.append(
                f'<a class="ev-card" data-mode="{mode}" href="/evidence/{slug}/">'
                f'<span class="idx">{i+1:02d}</span>'
                f'<span class="ev-title">{esc(title)}</span>'
                f'<span class="ev-blurb">{esc(blurb)}</span>'
                f'<span class="ev-tag">{tag}</span></a>')
        sections.append(
            f'<section class="ev-group"><span class="label">{esc(g)}</span>'
            f'<div class="ev-list">{"".join(cards)}</div></section>')
    return f"""<!DOCTYPE html>
<html lang="en" data-door="evidence">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>The Evidence — averagejoematt</title>
  <meta name="description" content="What's the protocol, what's it built on, and does the data hold up? The archival index of the experiment — correlative, read-only, honest.">
  <link rel="canonical" href="https://averagejoematt.com/evidence/">
  <link rel="icon" href="/favicon.ico">
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/evidence.css">
  {THEME_INIT}
</head>
<body>
  <a class="skip" href="#ev">Skip to the index</a>
  {TOPBAR}
  <main id="ev" class="ev">
    <div class="ev-head">
      <h1 class="ev-h1">The Evidence</h1>
      <p class="ev-lede">What's the protocol, what's it built on, and does it hold up? Everything here is correlative and read-only — an N=1 instrument exposed as proof, with thin data flagged as preliminary.</p>
    </div>
    {"".join(sections)}
  </main>
  <footer class="ev-foot"><span class="label">averagejoematt · the evidence</span>
    <span class="label"><a href="/">← the story</a></span></footer>
</body>
</html>
"""


def topic_html(i: int, t: tuple) -> str:
    slug, title, blurb, group, mode, endpoint, root, legacy = t
    cfg = {"slug": slug, "mode": mode, "endpoint": endpoint, "root": root,
           "archive_note": f"{title} is preserved in full below while this section is rebuilt into the new Evidence readout."}
    cfg_json = json.dumps(cfg)
    deeper = (f'<p class="deeper"><a href="{esc(legacy)}">Open the full {esc(title.lower())} view (preserved) →</a></p>'
              if legacy else "")
    return f"""<!DOCTYPE html>
<html lang="en" data-door="evidence">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(title)} — The Evidence — averagejoematt</title>
  <meta name="description" content="{esc(blurb)}">
  <link rel="canonical" href="https://averagejoematt.com/evidence/{slug}/">
  <link rel="icon" href="/favicon.ico">
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/evidence.css">
  {THEME_INIT}
</head>
<body>
  <a class="skip" href="#topic">Skip to the readout</a>
  {TOPBAR}
  <main id="topic" class="ev">
    <p class="ev-crumbs"><a href="/evidence/">evidence</a> / {esc(slug)} · {i+1:02d}</p>
    <h1 class="topic-h1">{esc(title)}</h1>
    <p class="topic-lede">{esc(blurb)}</p>
    <div class="readout" data-readout><p class="ev-note"><span class="shimmer">Loading the readout…</span></p></div>
    {deeper}
  </main>
  <footer class="ev-foot"><span class="label">averagejoematt · the evidence</span>
    <span class="label"><a href="/evidence/">← all evidence</a></span></footer>
  <script>window.__EVIDENCE_TOPIC__ = {cfg_json};</script>
  <script type="module" src="/assets/js/evidence.js"></script>
</body>
</html>
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(index_html(), encoding="utf-8")
    n = 0
    for i, t in enumerate(REGISTRY):
        slug = t[0]
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(topic_html(i, t), encoding="utf-8")
        n += 1
    print(f"evidence: wrote index + {n} topic pages under {OUT}/")
    data_topics = sum(1 for t in REGISTRY if t[4] == "data")
    print(f"  {data_topics} live-readout, {n - data_topics} archive (link to preserved /legacy).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
