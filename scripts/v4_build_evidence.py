#!/usr/bin/env python3
"""
v4_build_evidence.py — generate Door 3 (The Evidence) as a master-detail app.

Emits an app shell (horizontal GROUP tabs · left topic TILES · center readout
that loads dynamically) at site/evidence/index.html AND a per-slug shell at
site/evidence/<slug>/index.html (same app, pre-selected slug) so deep links and
the old-URL redirects resolve on static hosting. The full registry is embedded
as window.__EVIDENCE_REGISTRY__; assets/js/evidence.js does tabs/sidebar/routing
and the bespoke, data-bound readouts. Editorial topics carry authored content;
archive topics link to their preserved /legacy view.

Read-only inputs; writes only under site/evidence/. Run from repo root:
    python3 scripts/v4_build_evidence.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

OUT = Path("site/evidence")

# slug, title, blurb, group, mode, endpoint, root, legacy
#   mode: data (fetch+render) · interactive (render+wire, no fetch) ·
#         editorial (authored content) · archive (link to preserved legacy)
REGISTRY = [
    # ── The body ───────────────────────────────────────────────────────────
    (
        "vitals",
        "Vitals & pulse",
        "Today's pulse + the daily trend — weight, recovery, sleep, HRV, steps.",
        "The body",
        "data",
        "/api/pulse",
        None,
        "/legacy/live/",
    ),
    (
        "physical",
        "Body composition",
        "DEXA: body fat, lean mass, visceral fat, bone density, biological age.",
        "The body",
        "data",
        "/api/physical_overview",
        None,
        "/legacy/physical/",
    ),
    (
        "labs",
        "Bloodwork",
        "153 biomarkers over time — the inside view the wearables can't see.",
        "The body",
        "data",
        "/api/labs",
        None,
        "/legacy/labs/",
    ),
    (
        "glucose",
        "Glucose & meals",
        "Continuous glucose married to what you ate — peak, rise, return.",
        "The body",
        "data",
        "/api/glucose",
        None,
        "/legacy/glucose/",
    ),
    (
        "sleep",
        "Sleep",
        "Score, efficiency, deep/REM, HRV, and the recovery it buys.",
        "The body",
        "data",
        "/api/sleep_detail",
        None,
        "/legacy/sleep/",
    ),
    (
        "training",
        "Training & workouts",
        "Sessions, Zone-2, strain, steps, and strength 1RMs.",
        "The body",
        "data",
        "/api/training_overview",
        None,
        "/legacy/training/",
    ),
    (
        "nutrition",
        "Nutrition",
        "Intake, macros, frequent meals, and protein sources vs the deficit.",
        "The body",
        "data",
        "/api/nutrition_overview",
        None,
        "/legacy/nutrition/",
    ),
    # ── Mind & accountability ──────────────────────────────────────────────
    (
        "mind",
        "Mind & inner life",
        "Mood, journal, temptations resisted, and meditation.",
        "Mind & accountability",
        "data",
        "/api/mind_overview",
        None,
        "/legacy/mind/",
    ),
    (
        "habits",
        "Habits",
        "The daily adherence layer the Consistency pillar is built on.",
        "Mind & accountability",
        "data",
        "/api/habits",
        None,
        "/legacy/habits/",
    ),
    (
        "vices",
        "Vice streaks",
        "Days held across the tracked vices — shown honestly, named privately.",
        "Mind & accountability",
        "data",
        "/api/vice_streaks",
        None,
        "/legacy/accountability/",
    ),
    (
        "ledger",
        "The ledger",
        "Skin in the game — bounties earned, punishments donated.",
        "Mind & accountability",
        "data",
        "/api/ledger",
        None,
        "/legacy/ledger/",
    ),
    # ── Protocol & experiments ─────────────────────────────────────────────
    (
        "supplements",
        "Supplements",
        "What's taken, why, and what the evidence actually supports.",
        "Protocol & experiments",
        "data",
        "/api/supplements",
        None,
        "/legacy/supplements/",
    ),
    (
        "protocols",
        "Protocols",
        "Active deliberate interventions under test.",
        "Protocol & experiments",
        "data",
        "/api/protocols",
        None,
        "/legacy/protocols/",
    ),
    (
        "experiments",
        "Experiments",
        "The N=1 instrument: hypotheses run as read-only proof.",
        "Protocol & experiments",
        "data",
        "/api/experiments",
        None,
        "/legacy/experiments/",
    ),
    (
        "cycles",
        "Cycle vs cycle",
        "Same-window comparison across experiment restarts — what's different this time.",
        "Protocol & experiments",
        "data",
        "/api/cycle_compare",
        None,
        None,
    ),
    (
        "challenges",
        "Challenges",
        "Time-boxed challenges — activated, completed, XP earned. Read-only.",
        "Protocol & experiments",
        "data",
        "/api/challenges",
        None,
        "/legacy/challenges/",
    ),
    (
        "discoveries",
        "Discoveries",
        "Active hypotheses and the findings the engine surfaces.",
        "Protocol & experiments",
        "data",
        "/api/discoveries",
        None,
        "/legacy/discoveries/",
    ),
    # ── Credibility & the machine ──────────────────────────────────────────
    (
        "board",
        "The board",
        "The named AI experts who argue about the data — reads & roster.",
        "Credibility & the machine",
        "data",
        "/api/coaching-dashboard",
        None,
        "/legacy/coaches/",
    ),
    (
        "methodology",
        "Methodology",
        "How inputs become scores — N=1, the correlation engine, confidence.",
        "Credibility & the machine",
        "editorial",
        None,
        None,
        "/legacy/methodology/",
    ),
    (
        "build",
        "How it's built",
        "Build-in-public — the AI agents, the budget governor, and keeping a model honest about my own data.",
        "Credibility & the machine",
        "editorial",
        None,
        None,
        None,
    ),
    (
        "intelligence",
        "Intelligence",
        "Cross-source correlations the engine surfaces (correlative only).",
        "Credibility & the machine",
        "data",
        "/api/correlations",
        None,
        "/legacy/intelligence/",
    ),
    (
        "predictions",
        "Predictions",
        "The model's forward calls — logged, then scored against reality.",
        "Credibility & the machine",
        "data",
        "/api/predictions",
        None,
        "/legacy/predictions/",
    ),
    (
        "benchmarks",
        "Benchmarks",
        "Where the numbers sit vs age-band and centenarian targets.",
        "Credibility & the machine",
        "data",
        "/api/benchmark_trends",
        None,
        "/legacy/benchmarks/",
    ),
    (
        "biology",
        "Biology & genome",
        "Genome risk by category — the baseline biology behind the numbers.",
        "Credibility & the machine",
        "data",
        "/api/genome_risks",
        None,
        "/legacy/biology/",
    ),
    (
        "platform",
        "The platform",
        "The architecture by the numbers — sources, tools, lambdas, tests.",
        "Credibility & the machine",
        "data",
        "/api/platform_stats",
        None,
        "/legacy/platform/",
    ),
    (
        "data",
        "Data sources",
        "Every source feeding the platform, what it measures, how often.",
        "Credibility & the machine",
        "data",
        "/data/data_sources.json",
        None,
        "/legacy/data/",
    ),
    (
        "pipeline",
        "Pipeline status",
        "Which sources are flowing, which are paused, and when each last updated — live.",
        "Credibility & the machine",
        "data",
        "/api/source_freshness",
        None,
        "/legacy/data/",
    ),
    (
        "tools",
        "Tools",
        "The MCP tools Claude uses to read the data back.",
        "Credibility & the machine",
        "data",
        "/api/platform_stats",
        None,
        "/legacy/tools/",
    ),
    (
        "postmortems",
        "Post-mortems",
        "What each dead cycle taught — duration, collapse, and what changed next.",
        "Protocol & experiments",
        "data",
        "/api/survival",
        None,
        None,
    ),
    (
        "survival",
        "The survival curve",
        "The model handicaps its own human — odds this cycle reaches day 30.",
        "Protocol & experiments",
        "data",
        "/api/survival",
        None,
        None,
    ),
    (
        "mirror",
        "The mirror",
        "Type your numbers — see where you'd sit in this experiment. Nothing leaves the page.",
        "Credibility & the machine",
        "data",
        "/api/pulse_history",
        None,
        None,
    ),
    (
        "wrong",
        "The wrong page",
        "Every time the AI was wrong — caught claims, refuted calls, in public.",
        "Credibility & the machine",
        "data",
        "/api/wrong",
        None,
        None,
    ),
    (
        "inference",
        "The inference receipt",
        "Every AI call, priced — the meter behind the $75 ceiling, live.",
        "Credibility & the machine",
        "data",
        "/api/inference_receipt",
        None,
        None,
    ),
    (
        "cost",
        "Cost",
        "What running this costs — the radical-accessibility receipt.",
        "Credibility & the machine",
        "data",
        "/api/platform_stats",
        None,
        "/legacy/cost/",
    ),
    (
        "results",
        "Results",
        "Outcomes to date — what moved, and where the mechanisms live.",
        "Credibility & the machine",
        "data",
        "/api/journey",
        None,
        "/legacy/results/",
    ),
    (
        "explorer",
        "Explorer",
        "Today's raw record, straight from the pipeline.",
        "Credibility & the machine",
        "data",
        "/api/snapshot",
        None,
        "/legacy/explorer/",
    ),
    (
        "ask",
        "Ask the data",
        "Put a question to the experiment's data directly.",
        "Credibility & the machine",
        "interactive",
        None,
        None,
        "/legacy/ask/",
    ),
    (
        "kitchen",
        "The kitchen",
        "Meal intelligence from CGM + macros — fills as data accrues.",
        "Credibility & the machine",
        "editorial",
        None,
        None,
        "/legacy/kitchen/",
    ),
]

# IA regroup (2026-06-18): the old "Credibility & the machine" held 19 topics (too many
# for one menu) — split into "How it holds up" (does the science hold up) + "The machine"
# (how it's built & runs). And the reset-only pages (cycles / post-mortems / survival) move
# to a footer-tier "The reset log" group — they're for Matt's own record, not readers.
_REGROUP = {
    "cycles": "The reset log",
    "postmortems": "The reset log",
    "survival": "The reset log",
    "methodology": "How it holds up",
    "predictions": "How it holds up",
    "benchmarks": "How it holds up",
    "biology": "How it holds up",
    "wrong": "How it holds up",
    "results": "How it holds up",
    "mirror": "How it holds up",
    "board": "The machine",
    "build": "The machine",
    "intelligence": "The machine",
    "platform": "The machine",
    "data": "The machine",
    "pipeline": "The machine",
    "tools": "The machine",
    "inference": "The machine",
    "cost": "The machine",
    "explorer": "The machine",
    "ask": "The machine",
    "kitchen": "The machine",
}
REGISTRY = [(s, t, b, _REGROUP.get(s, g), *rest) for (s, t, b, g, *rest) in REGISTRY]

GROUP_ORDER = ["The body", "Mind & accountability", "Protocol & experiments", "How it holds up", "The machine", "The reset log"]

# Authored editorial content (faithful to the preserved legacy + the locked docs).
EDITORIAL = {
    "methodology": (
        '<p class="rd-lede">How raw inputs become scores — and why an experiment of one is built the way it is.</p>'
        '<section class="rd-sec"><h2 class="rd-h">Why N=1</h2>'
        '<p class="rd-prose">Population studies find the average effect across a group — real signal, but a statistical composite that may not resemble any individual. The N=1 approach turns that limitation into a feature: one subject means every measurement is directly relevant, with no between-person noise. The trade-off is external validity — you cannot generalise these results to you, and that is fine. <strong>The value is the framework, not the conclusions.</strong></p></section>'
        '<section class="rd-sec"><h2 class="rd-h">The correlation engine</h2>'
        '<p class="rd-prose">The core analytical layer is a rolling correlation engine that continuously computes Pearson <em>r</em> across metric pairs (sleep, recovery, nutrition, training, glucose). Running ~23 pairs at once creates a multiple-comparisons problem — the more tests you run, the more likely one is a false positive. So a Benjamini-Hochberg FDR correction controls the false-discovery rate across all simultaneous comparisons, and a minimum sample size is required before any correlation is surfaced.</p>'
        '<p class="rd-prose">A finding is only reported with its <em>p</em>-value alongside <em>r</em>, and an FDR-adjusted <em>q</em>-value used for filtering. Example: a confirmed pattern at p=0.003, n=47 paired days, BH-FDR q=0.014 — survives correction.</p></section>'
        '<section class="rd-sec"><h2 class="rd-h">Confidence vocabulary</h2>'
        '<p class="rd-prose">Everything is correlative, never causal. Fewer than 12 observations is a <strong>preliminary pattern</strong>; fewer than 30 is <strong>low confidence</strong>. The character model rolls these into a Level (1–100) across five tiers — Foundation → Momentum → Discipline → Mastery → Elite — over seven pillars: Sleep, Movement, Nutrition, Metabolic, Mind, Relationships, and Consistency.</p></section>'
        '<p class="correlative">The model never computes in prose — it interprets pre-computed numbers only. <span class="confidence conf-low">N=1</span></p>'
    ),
    "kitchen": (
        '<p class="rd-archive">The Kitchen is personalised meal intelligence — built from CGM response, macro tracking, and your real eating patterns. It needs data to work, and fills in automatically once daily nutrition logging and CGM readings accumulate over the first weeks. Until then, see Nutrition and Glucose &amp; meals for what\'s already flowing.</p>'
    ),
    "build": (
        '<p class="rd-lede">Most of these pages show the data. This one shows the machine that gathers it — built in public, by one person and a model, on a hard $75-a-month ceiling.</p>'
        '<section class="rd-sec"><h2 class="rd-h">A board of AI experts that argues</h2>'
        "<p class=\"rd-prose\">The coaching layer isn't one assistant — it's an ensemble of eight named personas (a sports scientist, a metabolic doctor, a behavioural coach, an N=1 statistician, and others) that each read the week from their own discipline. They disagree, and the disagreements are surfaced rather than averaged away — a single confident voice is exactly what an experiment of one should distrust. <em>(ADR-047 / ADR-055; <strong>coach_computation_engine.py</strong>.)</em></p></section>"
        '<section class="rd-sec"><h2 class="rd-h">Keeping a model honest about my own data</h2>'
        '<p class="rd-prose">The rule the whole system is built around: the model never does the math. Every number — correlations, scores, deltas — is computed in Python; the model only narrates pre-computed values, always correlatively, always with the confidence label attached. It cannot invent a statistic in prose because it is never handed the raw freedom to. All inference routes through one Bedrock chokepoint so there is a single place to audit what was asked and what came back. <em>(ADR-062; <strong>bedrock_client.py</strong>.)</em> <span class="confidence conf-low">interpretive only</span></p></section>'
        '<section class="rd-sec"><h2 class="rd-h">A governor that won\'t let the bill run away</h2>'
        '<p class="rd-prose">Putting an AI behind a public website is a way to get a surprise invoice. So a cost governor projects month-end spend every hour and writes a budget tier (0–3). As the projection climbs, AI features degrade on purpose — first the heavy ensemble narratives pause, then the public ask-the-data endpoint returns a friendly "paused" instead of a charge, and at the ceiling even the daily brief skips inference. One traffic spike cannot empty the budget and dark-fire the site. <em>(ADR-063; <strong>cost_governor_lambda.py</strong> + <strong>budget_guard.py</strong>.)</em></p></section>'
        '<section class="rd-sec"><h2 class="rd-h">An agent that fixes the platform while I sleep</h2>'
        '<p class="rd-prose">A self-healing agent runs each morning, triaging alarms, failed CI, and queue backlogs. The narrow, provably-safe fixes it merges itself — behind a deterministic gate that checks an allowlist, a diff-size cap, and the test subset before anything lands. Everything riskier becomes a pull request for a human, and the production deploy approval is never bypassed. The agent has read-only credentials; the gate, not the model, holds the keys. <em>(ADR-064 / ADR-065.)</em></p></section>'
        '<section class="rd-sec"><h2 class="rd-h">QA that looks at the screen, with a model\'s eyes</h2>'
        '<p class="rd-prose">After every deploy a headless browser walks the live site, opens the cockpit, exercises the interactions, and screenshots each page. Then a vision model reads each screenshot for things a pixel-diff would miss or false-alarm on — broken charts, overflow, a panel that rendered empty — robust to the fact that the underlying numbers change every day. The site you\'re reading was checked this way. <em>(ADR-076; <strong>tests/visual_qa.py</strong> + <strong>tests/visual_ai_qa.py</strong>.)</em></p></section>'
        '<p class="correlative">A note kept honest: the platform is deliberately further along than the result it documents. That\'s the joke, and the point — the engineering is the easy part; the weight is the hard part. This page is the receipt, not the trophy.</p>'
    ),
}

FONTS = '<link rel="stylesheet" href="/assets/css/fonts.css">'
THEME = (
    '<script>(function(){try{var t=localStorage.getItem("ajm-theme");'
    'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}})();</script>'
)
TOPBAR = (
    '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
    '<span class="brand-name">averagejoematt</span> <span class="brand-door label">evidence</span></a>'
    '<nav class="doors" aria-label="Doors"><a href="/now/">the cockpit</a><a href="/story/">the story</a><a href="/evidence/" aria-current="page">the evidence</a>'
    '<button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button></nav></header>'
)


def esc(s):
    return html.escape(str(s), quote=True)


def registry_json():
    out = []
    for slug, title, blurb, group, mode, endpoint, root, legacy in REGISTRY:
        e = {
            "slug": slug,
            "title": title,
            "blurb": blurb,
            "group": group,
            "mode": mode,
            "endpoint": endpoint,
            "root": root,
            "legacy": legacy,
        }
        if mode == "editorial":
            e["editorial"] = EDITORIAL.get(slug, "")
        out.append(e)
    return out


def shell(start_slug: str, canonical: str, title: str, desc: str) -> str:
    reg = json.dumps(registry_json())
    return f"""<!DOCTYPE html>
<html lang="en" data-door="evidence">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="https://averagejoematt.com{canonical}">
  <link rel="icon" href="/favicon.ico">
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/evidence.css">
  {THEME}
</head>
<body>
  <a class="skip" href="#ev">Skip to the evidence</a>
  {TOPBAR}
  <main id="ev" class="ev-app">
    <div class="ev-head">
      <h1 class="ev-h1">The Evidence</h1>
      <p class="ev-lede">What's the protocol, what's it built on, and does it hold up? Pick a section, then a topic — everything's correlative, read-only, and flagged when thin.</p>
    </div>
    <nav class="ev-tabs" data-tabs aria-label="Evidence sections"></nav>
    <div class="ev-layout">
      <aside class="ev-side" data-side aria-label="Topics"></aside>
      <section class="ev-main" data-main>
        <p class="ev-crumbs" data-crumb></p>
        <h2 class="topic-h1" data-title></h2>
        <p class="topic-lede" data-blurb></p>
        <div class="readout" data-readout></div>
        <p class="deeper" data-deeper></p>
      </section>
    </div>
  </main>
  <footer class="site-foot">
    <nav class="site-foot-cols" aria-label="Site map">
      <div class="sf-col"><p class="sf-h label">The Story</p>
        <a href="/story/chronicle/">Chronicle</a><a href="/story/lab-notes/">AI lab notes</a><a href="/story/coaches/">The Coaches</a><a href="/story/panel/">The Panel</a><a href="/story/journal/">In my own words</a><a href="/story/timeline/">Timeline</a><a href="/story/about/">About</a></div>
      <div class="sf-col"><p class="sf-h label">The Evidence</p>
        <a href="/evidence/">All topics</a><a href="/evidence/board/">The board</a><a href="/evidence/labs/">Labs</a><a href="/evidence/training/">Training</a><a href="/evidence/nutrition/">Nutrition</a></div>
      <div class="sf-col"><p class="sf-h label">The Cockpit</p>
        <a href="/now/">Live data</a><a href="/subscribe/">Follow by email</a><a href="/rss.xml">RSS</a></div>
      <div class="sf-col"><p class="sf-h label">Context</p>
        <a href="/evidence/methodology/">Methodology</a><a href="/story/about/">About the experiment</a><a href="/privacy/">Privacy</a></div>
    </nav>
    <p class="sf-base label"><span>averagejoematt · the evidence</span><a href="/">← home</a></p>
  </footer>
  <script>window.__EVIDENCE_REGISTRY__ = {reg}; window.__START_SLUG__ = {json.dumps(start_slug)};</script>
  <script type="module" src="/assets/js/evidence.js"></script>
</body>
</html>
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    first = REGISTRY[0][0]
    (OUT / "index.html").write_text(
        shell(
            first,
            "/evidence/",
            "The Evidence — averagejoematt",
            "The archival index of the experiment — correlative, read-only, browsable.",
        ),
        encoding="utf-8",
    )
    n = 0
    for slug, title, blurb, *_ in REGISTRY:
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            shell(slug, f"/evidence/{slug}/", f"{title} — The Evidence — averagejoematt", blurb), encoding="utf-8"
        )
        n += 1
    data_n = sum(1 for t in REGISTRY if t[4] in ("data", "interactive"))
    print(f"evidence app: index + {n} per-slug shells under {OUT}/ " f"({data_n} data/interactive, {n - data_n} editorial).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
