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
    # ── The body ───────────────────────────────────────────────────────────
    ("physical",    "Body composition", "DEXA: body fat, lean mass, visceral fat, bone density, biological age.", "The body", "data", "/api/physical_overview", None, "/legacy/physical/"),
    ("labs",        "Bloodwork",   "153 biomarkers over time — the inside view the wearables can't see.", "The body", "data", "/api/labs", None, "/legacy/labs/"),
    ("glucose",     "Glucose & meals", "Continuous glucose married to what you ate — peak, rise, return.", "The body", "data", "/api/glucose", None, "/legacy/glucose/"),
    ("sleep",       "Sleep",       "Score, efficiency, deep/REM, HRV, and the recovery it buys.",        "The body", "data", "/api/sleep_detail", None, "/legacy/sleep/"),
    ("training",    "Training & workouts", "Sessions, Zone-2, strain, steps, and strength 1RMs.",          "The body", "data", "/api/training_overview", None, "/legacy/training/"),
    ("nutrition",   "Nutrition",   "Intake, macros, frequent meals, and protein sources vs the deficit.", "The body", "data", "/api/nutrition_overview", None, "/legacy/nutrition/"),
    # ── Mind & accountability ──────────────────────────────────────────────
    ("mind",        "Mind & inner life", "Mood, journal, temptations resisted, and meditation.",          "Mind & accountability", "data", "/api/mind_overview", None, "/legacy/mind/"),
    ("habits",      "Habits",      "The daily adherence layer the Consistency pillar is built on.",       "Mind & accountability", "data", "/api/habits", None, "/legacy/habits/"),
    ("vices",       "Vice streaks", "Days held across the tracked vices — shown honestly, named privately.", "Mind & accountability", "data", "/api/vice_streaks", None, "/legacy/accountability/"),
    ("ledger",      "The ledger",  "Skin in the game — bounties earned, punishments donated.",            "Mind & accountability", "data", "/api/ledger", None, "/legacy/ledger/"),
    # ── Protocol & experiments ─────────────────────────────────────────────
    ("supplements", "Supplements", "What's taken, why, and what the evidence actually supports.",         "Protocol & experiments", "data", "/api/supplements", None, "/legacy/supplements/"),
    ("protocols",   "Protocols",   "Active deliberate interventions under test.",                         "Protocol & experiments", "data", "/api/protocols", None, "/legacy/protocols/"),
    ("experiments", "Experiments", "The N=1 instrument: hypotheses run as read-only proof.",              "Protocol & experiments", "data", "/api/experiments", None, "/legacy/experiments/"),
    ("challenges",  "Challenges",  "Time-boxed challenges — activated, completed, XP earned. Read-only.", "Protocol & experiments", "data", "/api/challenges", None, "/legacy/challenges/"),
    ("discoveries", "Discoveries", "Active hypotheses and the findings the engine surfaces.",             "Protocol & experiments", "data", "/api/discoveries", None, "/legacy/discoveries/"),
    # ── Credibility & the machine ──────────────────────────────────────────
    ("board",       "The board",   "The named AI experts who argue about the data — reads & roster.",     "Credibility & the machine", "data", "/api/coaching-dashboard", None, "/legacy/coaches/"),
    ("intelligence","Intelligence","Cross-source correlations the engine surfaces (correlative only).",   "Credibility & the machine", "data", "/api/correlations", None, "/legacy/intelligence/"),
    ("predictions", "Predictions", "The model's forward calls — logged, then scored against reality.",    "Credibility & the machine", "data", "/api/predictions", None, "/legacy/predictions/"),
    ("benchmarks",  "Benchmarks",  "Where the numbers sit vs age-band and centenarian targets.",          "Credibility & the machine", "data", "/api/benchmark_trends", None, "/legacy/benchmarks/"),
    ("biology",     "Biology & genome", "Genome risk by category — the baseline biology behind the numbers.", "Credibility & the machine", "data", "/api/genome_risks", None, "/legacy/biology/"),
    ("methodology", "Methodology", "How the scoring, pillars, and confidence rules actually work.",        "Credibility & the machine", "archive", None, None, "/legacy/methodology/"),
    ("cost",        "Cost",        "What running this costs to run — the radical-accessibility receipt.", "Credibility & the machine", "archive", None, None, "/legacy/cost/"),
    ("data",        "Data sources","Every source feeding the platform, and its freshness.",              "Credibility & the machine", "archive", None, None, "/legacy/data/"),
    ("platform",    "The platform","The architecture behind the three doors.",                           "Credibility & the machine", "archive", None, None, "/legacy/platform/"),
    ("results",     "Results",     "Outcomes to date — what moved, what didn't.",                        "Credibility & the machine", "archive", None, None, "/legacy/results/"),
    ("stack",       "The stack",   "The hardware and services feeding the experiment.",                  "Credibility & the machine", "archive", None, None, "/legacy/stack/"),
    ("kitchen",     "The kitchen", "How the food actually gets made on a deficit.",                      "Credibility & the machine", "archive", None, None, "/legacy/kitchen/"),
    ("tools",       "Tools",       "The MCP tools Claude uses to read the data back.",                   "Credibility & the machine", "archive", None, None, "/legacy/tools/"),
    ("explorer",    "Explorer",    "Browse the raw daily record yourself.",                              "Credibility & the machine", "archive", None, None, "/legacy/explorer/"),
    ("ask",         "Ask the data","Put a question to the experiment's data directly.",                  "Credibility & the machine", "archive", None, None, "/legacy/ask/"),
]

GROUP_ORDER = ["The body", "Mind & accountability", "Protocol & experiments", "Credibility & the machine"]

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
