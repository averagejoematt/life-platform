#!/usr/bin/env python3
"""
v4_build_evidence.py — generate the archive pillars (Data · Protocols · Method).

v5 (2026-06-27): the old single "Evidence" door is split into THREE pillars, all
served by one base-aware engine (assets/js/evidence.js):
  • /data/      — The body + Mind & accountability readouts (top-nav door)
  • /protocols/ — supplements · experiments · challenges · discoveries (top-nav door)
  • /method/    — how-it-holds-up + the-machine + reset-log (footer-tier, no door)

Each pillar emits an app shell (horizontal GROUP tabs · left topic TILES · center
readout) + per-slug shells, with __ARCHIVE_BASE__/__ARCHIVE_DOOR__/__ARCHIVE_TITLE__
set per page so the shared engine routes within the right base. The registry is
embedded as window.__EVIDENCE_REGISTRY__ (filtered to the pillar's groups).

Read-only inputs; writes under site/{data,protocols,method}/. Run from repo root:
    python3 scripts/v4_build_evidence.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

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
        "Weight & composition",
        "The daily weight cockpit — trend, milestones, projection — plus the episodic DEXA & bio-age arc.",
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
        "character",
        "The character",
        "What the Character Level means — 7 pillars, 100 levels, 5 tiers, and why level-ups are rare.",
        "Credibility & the machine",
        "editorial",
        None,
        None,
        None,
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
    # Promoted out of the footer tier (2026-06-21): survival + post-mortems are the honesty
    # moat made literal — they show the collapses and handicap the attempt with small-n humility,
    # which is exactly the credibility a skeptic/clinician comes for. They belong in "How it holds up".
    "postmortems": "How it holds up",
    "survival": "How it holds up",
    "methodology": "How it holds up",
    "character": "How it holds up",
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
    "character": (
        '<p class="rd-lede">The experiment has one number that tries to answer "is this actually working?" — a single RPG-style Character Level built from everything else. Here\'s what it means.</p>'
        '<section class="rd-sec"><h2 class="rd-h">One level, seven pillars</h2>'
        '<p class="rd-prose">Every day the engine scores seven pillars of the life — <strong>Sleep, Movement, Nutrition, Metabolic health, Mind, Relationships, and Consistency</strong> — each from its own real data (wearables, the food log, habits, labs). Those seven are weighted and rolled into one overall <strong>Character Level</strong> from 1 to 100. It\'s the closest thing to a single answer to the only question that matters over months: is the whole life trending up, or just one corner of it?</p></section>'
        '<section class="rd-sec"><h2 class="rd-h">Five tiers</h2>'
        '<p class="rd-prose">The 100 levels are grouped into five tiers, each a band of twenty:</p>'
        '<ul class="rd-tierlist">'
        "<li>🔨 <strong>Foundation</strong> — levels 1–20. Laying the base: the habits and the floor.</li>"
        "<li>🔥 <strong>Momentum</strong> — levels 21–40. The base holds and starts compounding.</li>"
        "<li>⚔️ <strong>Discipline</strong> — levels 41–60. Consistency under load, not just on good weeks.</li>"
        "<li>🏆 <strong>Mastery</strong> — levels 61–80. The system runs itself most days.</li>"
        "<li>👑 <strong>Elite</strong> — levels 81–100. The far end of what an N=1 can reach.</li>"
        "</ul>"
        '<p class="rd-prose">So "<strong>Level 8 · Foundation</strong>" — what the cockpit shows today — means level 8 of 100, still in the first tier: early, building the base, exactly where a few weeks in should be. The tier is the chapter; the level is the page.</p></section>'
        '<section class="rd-sec"><h2 class="rd-h">Why level-ups are rare (and mean something)</h2>'
        '<p class="rd-prose">A level only moves after a sustained shift — roughly <strong>five or more days of real improvement</strong> to go up, and <strong>seven or more of decline</strong> to go down. That deliberate stickiness means a single great (or terrible) day can\'t swing it, and an "up" is earned, not noise. Expect only a handful of level events in a month. When a pillar crosses a tier line, that\'s a genuine milestone — the kind of thing the weekly chronicle writes about.</p>'
        '<p class="correlative">It\'s a motivational lens on real data, not a medical score — every input is correlative and N=1. <span class="confidence conf-low">N=1</span></p></section>'
    ),
    "kitchen": (
        '<p class="rd-archive">The Kitchen is personalised meal intelligence — built from CGM response, macro tracking, and your real eating patterns. It needs data to work, and fills in automatically once daily nutrition logging and CGM readings accumulate over the first weeks. Until then, see Nutrition and Glucose &amp; meals for what\'s already flowing.</p>'
    ),
    "build": (
        '<p class="rd-lede">Most of these pages show the data. This one shows the machine that gathers it — built in public, by one person and a model, on a hard $75-a-month ceiling.</p>'
        # Hand-authored inline-SVG architecture diagram (themes via CSS vars; zero runtime cost).
        '<figure class="arch-fig" aria-label="System architecture: ingest, store, serve, with one AI chokepoint">'
        '<svg class="arch-svg" viewBox="0 0 760 250" role="img" preserveAspectRatio="xMidYMid meet">'
        '<defs><marker id="ahd" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">'
        '<path d="M0,0 L7,3 L0,6 Z" fill="var(--ink-faint)"/></marker></defs>'
        # ── Pipeline row: Sources → Ingest → Store → Compute → Serve ──
        '<g font-family="var(--font-mono)">'
        '<rect class="ab" x="8" y="22" width="132" height="62" rx="8"/>'
        '<text class="at" x="74" y="50">Sources</text><text class="as" x="74" y="68">20+ wearables · apps · labs</text>'
        '<rect class="ab" x="160" y="22" width="120" height="62" rx="8"/>'
        '<text class="at" x="220" y="50">Ingest</text><text class="as" x="220" y="68">15 λ · EventBridge</text>'
        '<rect class="ab" x="300" y="22" width="120" height="62" rx="8"/>'
        '<text class="at" x="360" y="50">Store</text><text class="as" x="360" y="68">S3 raw · DynamoDB</text>'
        '<rect class="ab" x="440" y="22" width="120" height="62" rx="8"/>'
        '<text class="at" x="500" y="50">Compute</text><text class="as" x="500" y="68">5 daily λ · Python</text>'
        '<rect class="ab" x="580" y="22" width="172" height="62" rx="8"/>'
        '<text class="at" x="666" y="50">Serve</text><text class="as" x="666" y="68">Site · MCP · Email · OG</text>'
        # arrows between stages
        '<line class="aa" x1="142" y1="53" x2="158" y2="53" marker-end="url(#ahd)"/>'
        '<line class="aa" x1="282" y1="53" x2="298" y2="53" marker-end="url(#ahd)"/>'
        '<line class="aa" x1="422" y1="53" x2="438" y2="53" marker-end="url(#ahd)"/>'
        '<line class="aa" x1="562" y1="53" x2="578" y2="53" marker-end="url(#ahd)"/>'
        # ── AI chokepoint band + governor ──
        '<rect class="ab abk" x="160" y="158" width="400" height="62" rx="8"/>'
        '<text class="at" x="360" y="184">bedrock_client.py — the one AI chokepoint</text>'
        '<text class="as" x="360" y="202">narrates pre-computed numbers · never does the math</text>'
        '<rect class="ab abg" x="580" y="158" width="172" height="62" rx="8"/>'
        '<text class="at" x="666" y="184">Budget governor</text><text class="as" x="666" y="202">tier 0–3 · caps the bill</text>'
        # dashed links: chokepoint feeds Compute + Serve; governor gates the chokepoint
        '<path class="ad" d="M500,158 L500,86" marker-end="url(#ahd)"/>'
        '<path class="ad" d="M540,158 C540,120 660,120 666,86" marker-end="url(#ahd)"/>'
        '<line class="ad" x1="580" y1="189" x2="562" y2="189" marker-end="url(#ahd)"/>'
        "</g></svg>"
        '<figcaption class="rd-figcap label">Ingest → store → serve. Every number is computed in Python; the model only narrates, through one Bedrock chokepoint, gated by a budget governor.</figcaption>'
        "</figure>"
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
# Motion layer (v5): fail-open head guard + the deferred motion.js. Reveal-on-scroll,
# chart draw-in, hover lifts — reduced-motion aware; content shows if motion.js never runs.
MOTION_HEAD = (
    '<script>(function(){try{if(!("IntersectionObserver" in window))return;'
    'if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;'
    'document.documentElement.classList.add("mo");'
    'window.__moFail=setTimeout(function(){document.documentElement.classList.remove("mo");},2600);}catch(e){}})();</script>'
)
MOTION_SCRIPT = '<script src="/assets/js/motion.js" defer></script>'
# The five doors, in loop order: cockpit · data · coaching · protocols · story.
DOORS = [
    ("/now/", "the cockpit", "cockpit", "Today's live instrument — your daily numbers, read back to you"),
    ("/data/", "the data", "data", "Every source the platform reads — trends now and over time"),
    ("/coaching/", "the coaching", "coaching", "The AI team & their arguments — stances, track records, disagreements"),
    ("/protocols/", "the protocols", "protocols", "The levers — supplements, experiments, challenges, discoveries"),
    ("/story/", "the story", "story", "The writing & the why — chronicle, journal, timeline, about"),
]


def door_icon(key: str) -> str:
    # Inline <use> of the shared sprite — server-rendered (no JS), inherits .ico-door colour.
    return (
        '<svg class="ico ico-door" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f'<use href="/assets/icons/icons.svg#i-door-{key}"></use></svg>'
    )


def topbar(active_key: str, brand_door: str) -> str:
    links = "".join(
        f'<a href="{href}" title="{esc(title)}"{" aria-current=\"page\"" if key == active_key else ""}>{door_icon(key)}{label}</a>'
        for href, label, key, title in DOORS
    )
    return (
        '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
        f'<span class="brand-name">averagejoematt</span> <span class="brand-door label">{esc(brand_door)}</span></a>'
        f'<nav class="doors" aria-label="Doors">{links}'
        '<button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button></nav></header>'
    )


def esc(s):
    return html.escape(str(s), quote=True)


# ── The three archive pillars, all served by one engine (assets/js/evidence.js).
#    Data + Protocols are top-nav doors; Method is footer-tier (the user's choice:
#    the machine / how-it-holds-up / reset-log demoted below the main pillars). ──
PILLARS = [
    {
        "dir": "data",
        "base": "/data/",
        "door": "data",
        "title": "Data",
        "nav_key": "data",
        "h1": "The Data",
        "lede": "Every source the platform reads — the body, the mind, and the signals the engine finds across them. Live now and over time. Correlative, read-only, flagged when thin.",
        "groups": ["The body", "Mind & accountability"],
    },
    {
        "dir": "protocols",
        "base": "/protocols/",
        "door": "protocols",
        "title": "Protocols",
        "nav_key": "protocols",
        "h1": "The Protocols",
        "lede": "The levers — supplements, experiments, challenges, and the discoveries they chase. What gets changed to move the data, and whether it moved.",
        "groups": ["Protocol & experiments"],
    },
    {
        "dir": "method",
        "base": "/method/",
        "door": "method",
        "title": "Method",
        "nav_key": "data",  # footer-tier: no door of its own; nav keeps 5 doors
        "h1": "The Method",
        "lede": "Under the hood — how the numbers are made, how honest they are, and the resets along the way. The machine, how it holds up, and the reset log.",
        "groups": ["How it holds up", "The machine", "The reset log"],
    },
]


def registry_json(groups):
    out = []
    for slug, title, blurb, group, mode, endpoint, root, legacy in REGISTRY:
        if group not in groups:
            continue
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


# Shared footer (5 doors + the footer-tier Method links) — one map on every archive page.
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


def shell(start_slug: str, canonical: str, title: str, desc: str, pillar) -> str:
    reg = json.dumps(registry_json(pillar["groups"]))
    return f"""<!DOCTYPE html>
<html lang="en" data-door="{pillar["door"]}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="https://averagejoematt.com{canonical}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com{canonical}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(desc)}">
  <link rel="icon" href="/favicon.ico">
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/evidence.css">
  {THEME}
  {MOTION_HEAD}
</head>
<body>
  <a class="skip" href="#ev">Skip to the content</a>
  {topbar(pillar["nav_key"], pillar["door"])}
  <main id="ev" class="ev-app">
    <div class="ev-head">
      <h1 class="ev-h1">{esc(pillar["h1"])}</h1>
      <p class="ev-lede">{esc(pillar["lede"])}</p>
    </div>
    <nav class="ev-tabs" data-tabs aria-label="Sections"></nav>
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
  {FOOTER}
  <script>window.__EVIDENCE_REGISTRY__ = {reg}; window.__START_SLUG__ = {json.dumps(start_slug)};
window.__ARCHIVE_BASE__ = {json.dumps(pillar["base"])}; window.__ARCHIVE_DOOR__ = {json.dumps(pillar["door"])}; window.__ARCHIVE_TITLE__ = {json.dumps(pillar["title"])};</script>
  {MOTION_SCRIPT}
  <script type="module" src="/assets/js/evidence.js"></script>
</body>
</html>
"""


def main() -> int:
    total = 0
    for pillar in PILLARS:
        out = Path("site") / pillar["dir"]
        out.mkdir(parents=True, exist_ok=True)
        slugs = [r[0] for r in REGISTRY if r[3] in pillar["groups"]]
        if not slugs:
            continue
        first = slugs[0]
        (out / "index.html").write_text(
            shell(first, pillar["base"], f"The {pillar['title']} — averagejoematt", pillar["lede"], pillar),
            encoding="utf-8",
        )
        n = 0
        for slug, title, blurb, group, *_ in REGISTRY:
            if group not in pillar["groups"]:
                continue
            d = out / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(
                shell(slug, f"{pillar['base']}{slug}/", f"{title} — The {pillar['title']} — averagejoematt", blurb, pillar),
                encoding="utf-8",
            )
            n += 1
        total += n
        print(f"  {pillar['base']}: index + {n} topic shells")
    print(f"archive app: {total} topic shells across {len(PILLARS)} pillars (data · protocols · method).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
