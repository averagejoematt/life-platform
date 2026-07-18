#!/usr/bin/env python3
"""
visual_qa.py — Playwright visual QA sweep for averagejoematt.com (v4 "The Measured Life")

Deep render verification of the three-door v4 site (ADR-071), over the unchanged
read-only engine:
  1. Drives Chromium over the v4 surfaces (Home/Cockpit/Story/Evidence + topics).
  2. Scrolls each page top-to-bottom (triggers lazy data fetch + .reveal animations).
  3. Verifies key containers rendered + inline-SVG charts have drawn geometry.
  4. Exercises one interaction (cockpit pillar disclosure → Day-Grade Replay detail).
  5. Mobile pass at 390px (+ chrome at 360px): horizontal overflow, plus the Epic-A
     failure classes as regression tests (#1013) — app-bar row ≤ viewport (#1003),
     no reveal stuck at opacity:0 after scroll (#1002), viewport meta present (#1004),
     and a tap-target advisory audit (#1010, non-gating).
  6. Captures full-page + per-chart element screenshots.
  7. Optional --ai-qa: hands the screenshots to Claude (Bedrock) for semantic
     "does this actually render correctly" judgement — robust to daily data changes
     where pixel-diff would be brittle (see tests/visual_ai_qa.py).
  8. Detects stuck loading text, JS errors, 5xx responses, empty sections.

The site is PUBLIC (no cf-auth gate) — no authentication needed.

Usage:
    python3 tests/visual_qa.py                      # full sweep, no AI
    python3 tests/visual_qa.py --page /cockpit/         # single page
    python3 tests/visual_qa.py --screenshot         # save full-page + chart crops
    python3 tests/visual_qa.py --screenshot --ai-qa # + Claude semantic verdict per image
    python3 tests/visual_qa.py --screenshot --ai-qa --reader-truth
                                                    # + phase-aware truth pass over each
                                                    #   page's rendered prose (#1095)

Cost: $0 for the browser sweep. --ai-qa adds a few Bedrock vision calls (Haiku,
~$0.001/image; pennies per run, and it no-ops cleanly if AI is unavailable/budget-paused).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Default target is live prod. The PR-time render gate (tests/pr_render_gate.py)
# overrides this to a local static server (http://127.0.0.1:PORT) via QA_SITE_URL
# so the same capture_page() harness can shift-left onto site PRs without a deploy.
SITE_URL = os.environ.get("QA_SITE_URL", "https://averagejoematt.com")

# ── Performance budgets (#580) ─────────────────────────────────────────────────
# Baselines measured 2026-07-05 against production (headless Chromium, single run,
# 33 swept pages): LCP 72-1136ms (p90 984ms), CLS 0.059-0.614 (p90 0.570), total
# JS 119-408KB/page. Budgets below carry headroom over that observed max so CI
# network jitter doesn't flake the gate, while still catching a real regression.
# See docs/DESIGN_SYSTEM_V5.md "Performance budget" for the full writeup — update
# both places if the numbers move.
LCP_BUDGET_MS = 2500  # ~2.2x the observed baseline max (1136ms)
CLS_BUDGET = 0.75  # ~1.2x the observed baseline max (0.614); the high current
# baseline is async data-render shifting layout as "··" placeholders resolve —
# a known characteristic, not something this issue fixes (see docs note).
JS_BYTES_SOFT_BUDGET = 550_000  # ~1.35x the observed baseline max (408KB); soft
# (warning only) — the site's largest page type (data/method/protocols, which
# share evidence.js) sets the ceiling other page types have plenty of room under.

_PERF_INIT_SCRIPT = """
window.__perf = {lcp: 0, cls: 0};
try {
    new PerformanceObserver((list) => {
        for (const e of list.getEntries()) { window.__perf.lcp = e.renderTime || e.loadTime || e.startTime; }
    }).observe({type: 'largest-contentful-paint', buffered: true});
} catch (e) {}
try {
    new PerformanceObserver((list) => {
        for (const e of list.getEntries()) { if (!e.hadRecentInput) window.__perf.cls += e.value; }
    }).observe({type: 'layout-shift', buffered: true});
} catch (e) {}
"""

# Topics whose readout is expected to include at least one inline-SVG chart.
# (Others are tables/cards — and even chart topics legitimately show an honest
# "N readings so far" text instead of a chart when data is sparse, per
# site/assets/js/charts.js's >=4-points rule — so missing-chart is a WARNING.)
CHART_TOPICS = {"vitals", "physical", "glucose", "sleep", "training", "character"}
# /data/ door topics — the body + mind/accountability readouts.
EVIDENCE_TOPICS = [
    "vitals",
    "physical",
    "labs",
    "glucose",
    "sleep",
    "training",
    "nutrition",
    "habits",
    "character",
]
# /method/ door topics — "how it holds up" + "the machine" (footer-tier in the v5 IA).
# These were 404ing under /data/ because the harness used the wrong base path
# (truth audit C1, 2026-06-27); they are live at /method/<slug>/.
METHOD_TOPICS = [
    "board",
    "pipeline",
    "intelligence",
    "predictions",
    "scenarios",
    "benchmarks",
]

# ── Page definitions (v4 surfaces) ────────────────────────────────────────────
PAGES = [
    {
        "path": "/",
        "name": "Home (constellation)",
        "wait_for": ".constellation svg",
        "checks": [
            {
                "selector": ".constellation svg a, .constellation svg .node",
                "min_count": 7,
                "desc": "7 pillar nodes drawn in the constellation",
            },
            {
                "selector": "a[href='/cockpit/'], a[href='/story/'], a[href='/data/']",
                "min_count": 2,
                "desc": "the three door links present",
            },
        ],
        "charts": [".constellation svg"],
    },
    {
        "path": "/cockpit/",
        "name": "Cockpit",
        "wait_for": "[data-bind='level']",
        "checks": [
            {"selector": "[data-bind='level']", "not_empty": True, "desc": "character level rendered"},
            {"selector": ".row", "min_count": 1, "desc": "at least one pillar row"},
            {"selector": ".site-foot-cols .sf-col", "min_count": 4, "desc": "footer mega-menu (4 columns) present (CC-05)"},
        ],
        "interact": {"click": ".row", "expect": ".pillar-detail", "desc": "pillar disclosure opens with the Day-Grade Replay detail"},
    },
    {
        "path": "/story/",
        "name": "Story hub",
        "wait_for": "[data-dx-tabs], [data-dx-read]",
        "checks": [
            {
                "selector": "[data-dx-tabs], [data-dx-list]",
                "min_count": 1,
                "desc": "dispatches reader (chronicle/journal/lab-notes tabs) rendered",
            },
            {"selector": "a[href='/data/'], a[href='/cockpit/']", "min_count": 1, "desc": "door links present"},
        ],
    },
    {
        "path": "/story/chronicle/",
        "name": "Story · chronicle",
        "checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "chronicle content"}],
    },
    {
        "path": "/story/journal/",
        "name": "Story · journal",
        "checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "journal content"}],
    },
    {
        "path": "/story/about/",
        "name": "Story · about",
        "checks": [{"selector": "main, article", "not_empty": True, "desc": "about content"}],
    },
    {
        "path": "/story/agents/",
        "name": "Story · the agents",
        "checks": [{"selector": "[data-roster], .agent-card, [data-feed]", "not_empty": True, "desc": "agent roster + feed"}],
    },
    # NB: "The Coaches" + "AI lab notes" moved to their own door /coaching/ (2026-06-20);
    # their page defs now live in the PAGES.extend([...]) Coaching block below.
    {
        "path": "/data/",
        "name": "Data hub",
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "data readout rendered"}],
    },
    {
        "path": "/protocols/",
        "name": "Protocols hub",
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "protocols readout rendered"}],
    },
    # S2 protocols uplevel (2026-07): the three upleveled topic pages get their own defs.
    {
        "path": "/protocols/experiments/",
        "name": "Protocols · experiments",
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "experiments readout rendered"}],
    },
    {
        "path": "/protocols/challenges/",
        "name": "Protocols · challenges",
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "challenges readout rendered"}],
    },
    {
        "path": "/protocols/supplements/",
        "name": "Protocols · supplements",
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "supplements readout rendered"}],
    },
    {
        "path": "/method/character/",
        "name": "Method · character explainer",
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "character explainer rendered"}],
    },
]
# Evidence live-data topics — readout must render; chart topics get a soft chart check + crop.
for _slug in EVIDENCE_TOPICS:
    PAGES.append(
        {
            "path": f"/data/{_slug}/",
            "name": f"Evidence · {_slug}",
            "wait_for": "[data-readout]",
            "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": f"{_slug} readout rendered"}],
            "charts": ["[data-readout] svg"] if _slug in CHART_TOPICS else [],
        }
    )
# Method-tier topics live under /method/<slug>/, not /data/.
for _slug in METHOD_TOPICS:
    PAGES.append(
        {
            "path": f"/method/{_slug}/",
            "name": f"Method · {_slug}",
            "wait_for": "[data-readout]",
            "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": f"{_slug} readout rendered"}],
        }
    )

# Door 4 "The Coaching" (/coaching/) — promoted out of Story (2026-06-20). Master-detail
# like the Story door, over /api/coaches · /api/coach_team · /api/coach/<id> · /api/field_notes.
# Checks stay lenient (reader not-empty) so honest empty-states before data accrues don't FAIL.
PAGES.extend(
    [
        {
            "path": "/coaching/",
            "name": "Coaching hub (My Team)",
            "wait_for": "[data-dx-tabs]",
            "checks": [
                {"selector": "[data-dx-tabs], [data-dx-list]", "min_count": 1, "desc": "coaching tabs + roster rendered"},
                {"selector": "[data-dx-read]", "not_empty": True, "desc": "team/coach readout rendered"},
            ],
        },
        {
            "path": "/coaching/by-coach/#training_coach",
            "name": "Coaching · By Coach (read-on-data, deep-link)",
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "coach read + domain data rendered"}],
        },
        {
            # #1112 — the head coach (Eli Marsh) at lead tier: the lead header must
            # mount (config-authored, independent of engine data) alongside the
            # standard dossier sections (honest-empty pre-data).
            "path": "/coaching/by-coach/#eli_marsh",
            "name": "Coaching · By Coach (head coach, lead tier)",
            "wait_for": "[data-dx-read]",
            "checks": [
                {"selector": ".coach-head--lead", "min_count": 1, "desc": "lead-tier header rendered for the head coach"},
                {"selector": "[data-dx-read] .team-lead", "min_count": 1, "desc": "running-the-program block rendered"},
            ],
        },
        {
            "path": "/coaching/scorecard/",
            "name": "Coaching · Scorecard (graded track record)",
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "scorecard tiles + per-coach record rendered"}],
        },
        {
            "path": "/coaching/team/",
            "name": "Coaching · The Team (roster/config)",
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "team roster/profile rendered"}],
        },
        {
            "path": "/coaching/lab-notes/",
            "name": "Coaching · AI lab notes",
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "lab-notes readout rendered"}],
        },
    ]
)

# The Mind pillar (reading, ADR-097) — consolidated into the Data door (#298/#299);
# /mind/ now 301s to /data/reading/ at the edge (#313). Follow the redirect and
# assert the READING readout renders in the archive chrome (the old standalone
# .ph-title/.shelf-block/.round-wrap selectors died with the standalone page —
# they red-flagged the first full run after the consolidation). Checks stay
# lenient: an honest empty shelf is an invitation, not a failure.
PAGES.append(
    {
        "path": "/mind/",
        "name": "Mind → /data/reading (redirect + readout)",
        "wait_for": ".ev-app",
        "checks": [
            {"selector": ".ev-tile", "min_count": 3, "desc": "archive tiles render after the redirect"},
            {"selector": ".readout, .ev-main", "min_count": 1, "desc": "the reading readout mounts"},
        ],
    }
)

# Text that should never be visible (stuck/placeholder states).
_EMPTY_SENTINELS = ("", "—", "...", "··", "•", "Loading", "LOADING", "Loading…")


# ══════════════════════════════════════════════════════════════════════════════
# Page-level checks (run in the browser)
# ══════════════════════════════════════════════════════════════════════════════


def _scroll_and_reveal(page):
    """Scroll the page top-to-bottom, then force all .reveal animations visible."""
    page.evaluate(
        """
        () => new Promise(resolve => {
            let y = 0; const step = 400;
            const timer = setInterval(() => {
                window.scrollBy(0, step); y += step;
                document.querySelectorAll('.reveal').forEach(el => {
                    el.classList.add('is-visible'); el.style.opacity = '1'; el.style.transform = 'none';
                });
                if (y >= document.body.scrollHeight) { clearInterval(timer); window.scrollTo(0, 0); resolve(); }
            }, 80);
            setTimeout(() => { clearInterval(timer); window.scrollTo(0, 0); resolve(); }, 10000);
        })
    """
    )
    page.evaluate(
        """
        () => document.querySelectorAll('.reveal').forEach(el => {
            el.classList.add('is-visible'); el.style.opacity = '1'; el.style.transform = 'none';
        })
    """
    )
    page.wait_for_timeout(1500)


def _check_svg_charts(page, selectors):
    """For each chart selector, report whether the SVG has drawn geometry + is visible."""
    return page.evaluate(
        """(selectors) => {
        const out = [];
        for (const sel of selectors) {
            document.querySelectorAll(sel).forEach((svg, i) => {
                if (!svg) return;
                const drawn = svg.querySelectorAll('path, polyline, line, circle, rect, a .node, .node').length;
                const box = svg.getBoundingClientRect();
                out.push({sel, index: i, drawn, visible: box.width > 4 && box.height > 4});
            });
        }
        return out;
    }""",
        selectors,
    )


def _check_sections_for_blank(page):
    """Visible sections >100px tall with <5 chars of text and no chart (excludes closed <details>)."""
    return page.evaluate(
        """
        () => {
            const issues = [];
            const insideClosedDetails = (el) => {
                let p = el.parentElement;
                while (p) { if (p.tagName === 'DETAILS' && !p.hasAttribute('open')) return true; p = p.parentElement; }
                return false;
            };
            document.querySelectorAll('section, [class*=section]').forEach(s => {
                const rect = s.getBoundingClientRect();
                if (rect.height < 20 || insideClosedDetails(s)) return;
                const text = s.innerText.trim();
                if (rect.height > 100 && text.length < 5 && !s.querySelector('canvas, svg, img')) {
                    issues.push({class: s.className.slice(0, 60), id: s.id, height: Math.round(rect.height)});
                }
            });
            return issues;
        }
    """
    )


def _check_stale_text(page):
    """Visible development/placeholder/stuck-loading copy that should never ship."""
    return page.evaluate(
        r"""
        () => {
            const body = document.body.innerText;
            const issues = [];
            const suspects = [
                {pattern: /launching april|coming soon|ships after april/i, desc: 'Pre-launch copy still visible'},
                {pattern: /(?<![a-z])TODO(?![a-z])|FIXME|lorem ipsum/i, desc: 'Development placeholder'},
                {pattern: /Loading\.\.\.\./i, desc: 'Stuck loading indicator'},
            ];
            for (const s of suspects) {
                if (s.pattern.test(body)) {
                    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    while (w.nextNode()) {
                        if (s.pattern.test(w.currentNode.textContent)) {
                            const el = w.currentNode.parentElement;
                            if (el && el.offsetParent !== null && el.offsetHeight > 0) {
                                issues.push({text: w.currentNode.textContent.trim().slice(0, 60), desc: s.desc});
                                break;
                            }
                        }
                    }
                }
            }
            return issues;
        }
    """
    )


def _mobile_overflow(page):
    """Horizontal overflow in px at the current (mobile) viewport — >4 means a layout break."""
    return page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


# ── Mobile failure-class assertions (#1013) ───────────────────────────────────
# These pin the EXACT classes the 2026-07-11 mobile review found live and Epic A
# fixed (#1002 stuck reveals, #1003 app-bar overflow, #1004 missing viewport meta),
# so they become regression tests, not lore. (a)-(c) gate; (d) tap-targets is
# advisory output only (the 44px floor is Epic B #1010, not yet enforced).

# Mirrors the reveal selector in site/assets/js/motion.js — an element matching this
# that stays opacity:0 after a scroll-through is the #1002 tall-section reveal bug.
MOBILE_REVEAL_SEL = (
    ".hero, .page-hero, .ev-head, .dx-head, .beat, .loop, .rd-sec, .two-voice, "
    ".coach-daily, .coach-progress, .coach-report, .coach-stance, .team-lead, "
    ".team-focus, .team-tension, .team-huddle, .supp, .cap-card, .vr-row, .figs, .ml-ladder"
)

# Advisory only: the cockpit's headline controls + the site-wide chrome the review
# measured under the 44px floor (#1010). Reported, never gated (yet).
TAP_TARGET_SEL = ".doors .theme-toggle, .tt-scrubber, .intro-close, .breadcrumbs a, .ev-link, .cta-quiet"


def _app_bar_overflow(page):
    """px by which the fixed bottom app-bar (.doors) row exceeds the viewport at the
    current width — >2 is the #1003 overflow (clipped toggle / truncated door)."""
    return page.evaluate(
        """() => {
        const bar = document.querySelector('.doors');
        if (!bar) return null;                       // page has no app-bar → n/a
        const vw = document.documentElement.clientWidth;
        // scrollWidth catches children pushed past the edge even when the bar itself
        // is clipped to viewport width; also check the rightmost child's edge.
        let far = 0;
        bar.querySelectorAll(':scope > *').forEach(c => {
            const style = getComputedStyle(c);
            if (style.display === 'none') return;
            far = Math.max(far, c.getBoundingClientRect().right);
        });
        return Math.round(Math.max(bar.scrollWidth - vw, far - vw));
    }"""
    )


def _stuck_reveals(page, sel):
    """Reveal-selector elements that are real-sized but stuck at opacity:0 after scroll
    (the #1002 bug). Excludes zero-size / honest-empty elements to avoid false positives."""
    return page.evaluate(
        """(sel) => {
        const out = [];
        document.querySelectorAll(sel).forEach(el => {
            const r = el.getBoundingClientRect();
            // Only substantial, laid-out sections count — the #1002 bug strands whole
            // content blocks (hero/rd-sec/backlog cards, all >100px). Requiring ≥24px
            // excludes empty/collapsed elements and tiny transient labels so the live
            // post-deploy sweep can't false-positive on an honest sparse-data element.
            if (r.width < 24 || r.height < 24) return;
            if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') return;
            const op = parseFloat(getComputedStyle(el).opacity);
            if (op < 0.05) out.push((el.className || el.tagName).toString().slice(0, 40));
        });
        return out;
    }""",
        sel,
    )


def _viewport_meta_ok(page):
    """True if a width=device-width viewport meta is present (the #1004 class)."""
    return page.evaluate(
        """() => {
        const m = document.querySelector('meta[name="viewport"]');
        return !!(m && /width\\s*=\\s*device-width/i.test(m.getAttribute('content') || ''));
    }"""
    )


def _tap_target_audit(page, sel):
    """Advisory (#1010): interactive controls whose effective hit area is < 44px."""
    return page.evaluate(
        """(sel) => {
        const out = [];
        document.querySelectorAll(sel).forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;        // not rendered
            if (r.width < 44 || r.height < 44) {
                out.push(`${(el.className||el.tagName).toString().slice(0,28)} ${Math.round(r.width)}x${Math.round(r.height)}`);
            }
        });
        return out;
    }""",
        sel,
    )


# ── SVG-text legibility floor (#1210) ─────────────────────────────────────────
# Inline-SVG <text> is sized in viewBox units, so its ON-SCREEN size scales with
# the svg's rendered width: a 10px radar label in a 320-unit viewBox drawn 280px
# wide lands at ~8.8px, below the 11px smallest-shipping register (DESIGN_SYSTEM_V5
# §10.5). #1017 fixed this for the home constellation; #1210 generalized it
# (site/assets/js/svgtype.js floors the registered labels to max(base, 11/scale)).
# This audit is the arbiter that retired the comment-level `fs-ok: SVG viewBox
# units` sanction: it measures the RENDERED result — computed font-size × the live
# getScreenCTM scale — for EVERY svg <text>, at both widths, so no future
# viewBox-unit label can ship sub-floor behind a comment again.
SVG_TEXT_FLOOR_PX = 11.0

_SVG_TEXT_AUDIT_JS = """(floor) => {
    const out = [];
    document.querySelectorAll('svg text').forEach(t => {
        const txt = (t.textContent || '').trim();
        if (!txt) return;                                  // empty <text> — nothing to read
        let box; try { box = t.getBoundingClientRect(); } catch (e) { return; }
        if (!box || box.width < 1 || box.height < 1) return; // not laid out / off the tree
        const cs = getComputedStyle(t);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        const fs = parseFloat(cs.fontSize) || 0;           // user-unit font-size (px)
        let scale = 1;
        // hypot(a,b) is the uniform scale magnitude — correct even for a rotated
        // axis label (a -90deg text has ctm.a≈0, which would falsely read as 1x).
        try { const m = t.getScreenCTM(); if (m) { const s = Math.hypot(m.a, m.b); if (s > 0) scale = s; } } catch (e) {}
        const eff = fs * scale;                            // effective ON-SCREEN px
        if (eff < floor - 0.05) {
            out.push({
                cls: (t.getAttribute('class') || '(none)'),
                txt: txt.slice(0, 24),
                fs: Math.round(fs * 100) / 100,
                scale: Math.round(scale * 1000) / 1000,
                eff: Math.round(eff * 100) / 100,
            });
        }
    });
    return out;
}"""


def _svg_text_floor_findings(page, width):
    """Set `width`, let svgtype.js re-floor (rAF-debounced on resize), then return
    every svg <text> whose effective on-screen size is below the 11px floor."""
    page.set_viewport_size({"width": width, "height": 900 if width >= 1000 else 844})
    page.wait_for_timeout(300)  # let the resize handler's rAF re-floor + layout settle
    try:
        return page.evaluate(_SVG_TEXT_AUDIT_JS, SVG_TEXT_FLOOR_PX) or []
    except Exception:
        return []


def _write_step_summary(path, passed, failed, warns, results):
    """Append a Markdown summary to $GITHUB_STEP_SUMMARY (CI job summary)."""
    lines = [f"## Visual + AI-vision QA — {passed} passed, {failed} failed, {warns} warnings\n"]
    for r in results:
        v = r.get("ai_verdict") or {}
        if r["status"] == "FAIL" or r.get("warnings") or v.get("severity") in ("med", "high"):
            icon = "❌" if r["status"] == "FAIL" else "⚠️"
            lines.append(f"- {icon} **{r['page']}** (`{r['path']}`)")
            for i in r.get("issues", []):
                lines.append(f"  - 🔴 {i}")
            for w in r.get("warnings", []):
                lines.append(f"  - ⚠️ {w}")
            if v:
                lines.append(f"  - 🤖 AI[{v.get('severity')}]: {v.get('summary', '')}")
    try:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def _navigate_with_fallback(page, url, primary_timeout=15000, fallback_timeout=20000):
    """Navigate; try networkidle, fall back to domcontentloaded (pages poll/async-load)."""
    try:
        page.goto(url, wait_until="networkidle", timeout=primary_timeout)
        return None
    except Exception:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=fallback_timeout)
            return "networkidle timed out; fell back to domcontentloaded"
        except Exception as e2:
            return f"Page load failed: {e2}"


# ══════════════════════════════════════════════════════════════════════════════
# Main sweep
# ══════════════════════════════════════════════════════════════════════════════


def capture_page(context, page_def, screenshot_dir, save_screenshots=False, capture_prose=False):
    """Drive one page def in an open browser context and return its result dict.

    Pure capture: navigate, scroll/reveal, run element/chart/interaction checks,
    blank/stale-text scan, optional screenshots (full + chart crops + 390px mobile),
    HTTP/JS failure collection. No printing, no AI-QA, no report writing — those
    stay in run_sweep so its CI behaviour is byte-for-byte unchanged. Returns:
        {"page", "path", "status", "issues", "warnings", "screenshots"}

    Extracted from run_sweep's per-page loop (2026-06-20) so tests/site_review.py
    can reuse identical capture without forking the gating visual-qa harness.
    """
    page = context.new_page()
    page.add_init_script(_PERF_INIT_SCRIPT)
    path, name = page_def["path"], page_def["name"]
    issues, warnings, js_errors, failed_responses, shots = [], [], [], [], []
    perf_result = {"lcp_ms": None, "cls": None, "js_bytes": 0}
    _js_bytes = [0]  # mutable box (perf_js_bytes) — total JS response bytes for the page

    _noncrit = ["favicon", "sub_count", "subscriber_count"]
    page.on("console", lambda m: js_errors.append(m.text) if m.type == "error" and not any(nc in m.text for nc in _noncrit) else None)
    page.on("pageerror", lambda err: js_errors.append(str(err)))

    def _on_response(r):
        if r.status >= 400 and not any(nc in r.url for nc in _noncrit):
            failed_responses.append((r.status, r.url))
        try:
            ct = r.headers.get("content-type", "")
            if r.url.endswith(".js") or "javascript" in ct:
                _js_bytes[0] += len(r.body())
        except Exception:
            pass  # opaque/redirected/aborted responses — skip, don't fail the sweep over it

    page.on("response", _on_response)

    try:
        nav = _navigate_with_fallback(page, f"{SITE_URL}{path}")
        if nav and nav.startswith("Page load failed"):
            issues.append(nav)
            raise RuntimeError("nav_failed")
        if nav:
            warnings.append(nav)

        wait_for = page_def.get("wait_for")
        if wait_for:
            try:
                page.wait_for_selector(wait_for, state="visible", timeout=8000)
            except Exception:
                issues.append(f"Container '{wait_for}' never became visible")

        # ── performance budget: LCP + CLS (#580) ──
        # Read before _scroll_and_reveal's synthetic scrolling runs, so this reflects
        # what a real visitor's browser reports for natural page load — not our own
        # forced scroll/reveal. A short settle wait lets async data-driven re-renders
        # (the site's "·· -> real number" pattern) mostly finish, same as how a real
        # LCP/CLS measurement window works.
        page.wait_for_timeout(600)
        try:
            _perf = page.evaluate("() => window.__perf") or {}
        except Exception:
            _perf = {}
        lcp_ms = _perf.get("lcp") or None
        cls = _perf.get("cls")
        perf_result["lcp_ms"] = round(lcp_ms, 1) if lcp_ms else None
        perf_result["cls"] = round(cls, 4) if cls is not None else None
        if lcp_ms and lcp_ms > LCP_BUDGET_MS:
            issues.append(f"LCP {lcp_ms:.0f}ms exceeds budget {LCP_BUDGET_MS}ms")
        if cls is not None and cls > CLS_BUDGET:
            issues.append(f"CLS {cls:.3f} exceeds budget {CLS_BUDGET}")

        _scroll_and_reveal(page)

        # ── element/text checks ──
        for check in page_def.get("checks", []):
            els = page.query_selector_all(check["selector"])
            if "min_count" in check and len(els) < check["min_count"]:
                issues.append(f"Expected {check['min_count']}+ '{check['selector']}', found {len(els)} — {check['desc']}")
            if check.get("not_empty"):
                empties = 0
                for el in els:
                    try:
                        txt = (el.inner_text() or "").strip()
                    except Exception:
                        txt = (el.text_content() or "").strip()
                    if txt in _EMPTY_SENTINELS:
                        empties += 1
                if els and empties == len(els):
                    issues.append(f"All '{check['selector']}' empty/placeholder — {check['desc']}")
                elif not els:
                    issues.append(f"'{check['selector']}' not found — {check['desc']}")

        # ── SVG chart geometry (soft: warn, the AI layer judges render quality) ──
        if page_def.get("charts"):
            svg = _check_svg_charts(page, page_def["charts"])
            visible = [c for c in svg if c["visible"]]
            if not svg:
                warnings.append(f"No chart SVG matched {page_def['charts']} (may be an honest sparse-data state)")
            elif visible and all(c["drawn"] == 0 for c in visible):
                issues.append(f"Chart SVG present but no drawn geometry: {page_def['charts']}")

        # ── interaction (cockpit pillar disclosure) ──
        if page_def.get("interact"):
            it = page_def["interact"]
            target = page.query_selector(it["click"])
            if not target:
                warnings.append(f"Interaction skipped — '{it['click']}' not present")
            else:
                try:
                    target.click(timeout=3000)
                    page.wait_for_selector(it["expect"], state="visible", timeout=4000)
                    # The cockpit disclosure animates via View Transitions — a
                    # screenshot mid-crossfade captures both frames overlapped
                    # ("garbled text" AI-vision false-FAIL, found 2026-06-12).
                    # Let the transition settle before anything is captured.
                    page.wait_for_timeout(800)
                except Exception:
                    issues.append(f"Interaction failed: clicking '{it['click']}' did not reveal '{it['expect']}' — {it['desc']}")

        # ── blank sections + stale copy ──
        for bs in _check_sections_for_blank(page)[:2]:
            issues.append(f"Empty section: .{bs['class'][:40]} (h={bs['height']}px)")
        for st in _check_stale_text(page):
            issues.append(f"Stale text: \"{st['text'][:50]}\" — {st['desc']}")

        # ── screenshots (full page + chart crops) ──
        slug = path.strip("/").replace("/", "-") or "home"
        if save_screenshots:
            full = os.path.join(screenshot_dir, f"{slug}.png")
            page.screenshot(path=full, full_page=True)
            shots.append({"kind": "page", "path": full})
            for ci, sel in enumerate(page_def.get("charts", [])):
                el = page.query_selector(sel)
                if el:
                    try:
                        crop = os.path.join(screenshot_dir, f"{slug}-chart{ci}.png")
                        el.screenshot(path=crop)
                        shots.append({"kind": "chart", "path": crop, "selector": sel})
                    except Exception:
                        pass

        # ── rendered prose dump (accuracy-audit / Axis B+C reads the visitor's text) ──
        # Default off so the CI visual sweep is unchanged; site_review/accuracy_audit opt in.
        if capture_prose and screenshot_dir:
            try:
                prose = page.evaluate("() => document.body.innerText") or ""
                with open(os.path.join(screenshot_dir, f"{slug}.txt"), "w") as pf:
                    pf.write(prose)
                shots.append({"kind": "prose", "path": os.path.join(screenshot_dir, f"{slug}.txt")})
            except Exception:
                pass

        # ── mobile @ 390px: overflow + the Epic-A failure classes (#1013) ──
        page.set_viewport_size({"width": 390, "height": 844})
        # Re-scroll at the mobile viewport so motion.js's IntersectionObserver fires
        # at the 844px height — the #1002 stuck-reveal bug is viewport-height-dependent
        # (a section too tall to reach the threshold never reveals), and some pages
        # only overflow the threshold on desktop. This makes the mobile-only case real.
        _scroll_and_reveal(page)
        overflow = _mobile_overflow(page)
        if overflow and overflow > 4:
            issues.append(f"Horizontal overflow at 390px — content exceeds viewport by {overflow}px")
        # (b) #1002 — reveal-selector elements stuck at opacity:0 after scroll-through.
        stuck = _stuck_reveals(page, MOBILE_REVEAL_SEL)
        if stuck:
            issues.append(
                f"Scroll-reveal stuck at opacity:0 on {len(stuck)} element(s) @390px (#1002 class): {', '.join(sorted(set(stuck))[:4])}"
            )
        # (a) #1003 — bottom app-bar row overflows the viewport at 390px.
        bar390 = _app_bar_overflow(page)
        if bar390 is not None and bar390 > 2:
            issues.append(f"App-bar row exceeds viewport by {bar390}px @390px (#1003 class)")
        # (c) #1004 — the page must carry a width=device-width viewport meta.
        if not _viewport_meta_ok(page):
            issues.append("Missing width=device-width viewport meta (#1004 class)")
        # (d) #1010 — tap-target floor, ADVISORY only (not gated yet).
        small = _tap_target_audit(page, TAP_TARGET_SEL)
        if small:
            warnings.append(f"Tap targets < 44px @390px (advisory #1010): {', '.join(small[:5])}")
        if save_screenshots:
            mob = os.path.join(screenshot_dir, f"{slug}-mobile.png")
            page.screenshot(path=mob, full_page=True)
            shots.append({"kind": "mobile", "path": mob})
        # ── chrome @ 360px: the app-bar is tightest here (#1003 verified at 360) ──
        page.set_viewport_size({"width": 360, "height": 800})
        page.wait_for_timeout(200)
        bar360 = _app_bar_overflow(page)
        if bar360 is not None and bar360 > 2:
            issues.append(f"App-bar row exceeds viewport by {bar360}px @360px (#1003 class)")

        # ── SVG-text legibility floor (#1210): every inline-SVG <text> must render
        #    >=11px effective at BOTH 1280 and 390. viewBox-unit text scales with the
        #    svg's rendered width, so a label legible on desktop can fall sub-floor at
        #    another width (and vice-versa) — measure at both. svgtype.js floors the
        #    registered labels; this is the guard that it held. ──
        for _floor_w in (1280, 390):
            for f in _svg_text_floor_findings(page, _floor_w):
                issues.append(
                    f"SVG text below 11px floor @{_floor_w}px (#1210): .{f['cls']} '{f['txt']}' = "
                    f"{f['fs']}px x scale {f['scale']} = {f['eff']}px effective"
                )

        # ── failed HTTP calls (broken /api/ calls fail; other resources warn) ──
        # A 429 is throttle noise, not a broken endpoint: the sweep's parallel
        # page loads can exceed site-api's reserved concurrency (20) — observed
        # flaking the gating CI job on a different endpoint each run (2026-07-04).
        # Re-probe each API 429 once, sequentially, after the page settles: a
        # <400 re-probe downgrades to a warning; a persistent 429 still fails.
        _kept = []
        for s, u in failed_responses:
            if s == 429 and "/api/" in u:
                try:
                    if page.request.get(u, timeout=10000).status < 400:
                        warnings.append(f"429 throttle recovered on re-probe: {u.replace(SITE_URL, '')[:90]}")
                        continue
                except Exception:
                    pass
            _kept.append((s, u))
        failed_responses = _kept
        api_fails = sorted({f"{s} {u.replace(SITE_URL, '')[:90]}" for s, u in failed_responses if "/api/" in u})
        other_fails = sorted({f"{s} {u.replace(SITE_URL, '')[:90]}" for s, u in failed_responses if "/api/" not in u})
        if api_fails:
            issues.append(f"{len(api_fails)} broken API call(s): {'; '.join(api_fails[:4])}")
        if other_fails:
            warnings.append(f"{len(other_fails)} non-API resource issue(s): {'; '.join(other_fails[:3])}")
        code_errors = [e for e in js_errors if "Failed to load resource" not in e]
        if code_errors:
            issues.append(f"{len(code_errors)} JS error(s): {code_errors[0][:160]}")

    except Exception as e:
        if str(e) not in ("auth_failed", "nav_failed"):
            issues.append(f"Page load failed: {e}")

    perf_result["js_bytes"] = _js_bytes[0]
    if _js_bytes[0] > JS_BYTES_SOFT_BUDGET:
        warnings.append(f"Total JS {_js_bytes[0] // 1024}KB exceeds soft budget {JS_BYTES_SOFT_BUDGET // 1024}KB")

    page.close()
    return {
        "page": name,
        "path": path,
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "warnings": warnings,
        "screenshots": shots,
        "perf": perf_result,
    }


def run_sweep(pages=None, save_screenshots=False, screenshot_dir=None, ai_qa=False, reader_truth=False):
    """Run the v4 visual QA sweep. Returns True if no page FAILED."""
    from playwright.sync_api import sync_playwright

    if screenshot_dir is None:
        screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "qa-screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    results = []
    # AI-QA needs the screenshots, so force-enable capture when --ai-qa is set.
    if ai_qa:
        save_screenshots = True

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")

        for page_def in pages or PAGES:
            # --reader-truth needs each page's rendered innerText (the prose dump).
            result = capture_page(context, page_def, screenshot_dir, save_screenshots, capture_prose=reader_truth)
            results.append(result)
            icon = "✅" if not result["issues"] else "❌"
            n_warn = len(result["warnings"])
            warn = f" ({n_warn} warning{'s' if n_warn != 1 else ''})" if result["warnings"] else ""
            print(f"  {icon} {result['page']} ({result['path']}){warn}")
            for x in result["issues"]:
                print(f"      → {x}")
            for w in result["warnings"]:
                print(f"      ⚠ {w}")

        browser.close()

    # ── optional Claude-vision semantic QA over the captured screenshots ──
    if ai_qa:
        try:
            from visual_ai_qa import assess_results
        except ImportError:
            sys.path.insert(0, os.path.dirname(__file__))
            from visual_ai_qa import assess_results
        print("\n── AI-vision QA (Claude / Bedrock) ──")
        assess_results(results)  # mutates results in place: adds ai_verdict + may add issues

    # ── optional phase-aware reader-truth QA over the captured prose (#1095) ──
    if reader_truth:
        try:
            from visual_ai_qa import assess_reader_truth
        except ImportError:
            sys.path.insert(0, os.path.dirname(__file__))
            from visual_ai_qa import assess_reader_truth
        print("\n── Reader-truth QA (phase-aware, Claude / Bedrock) ──")
        assess_reader_truth(results)  # mutates results: truth_findings + high → FAIL

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warns = sum(len(r.get("warnings", [])) for r in results)
    print(f"\n{'=' * 56}")
    print(f"Visual QA: {passed} passed, {failed} failed, {warns} warning(s) across {len(results)} pages")
    if save_screenshots:
        print(f"Screenshots: {screenshot_dir}/")

    with open(os.path.join(screenshot_dir, "report.json"), "w") as f:
        json.dump(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "passed": passed,
                "failed": failed,
                "warnings": warns,
                "results": results,
            },
            f,
            indent=2,
        )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        _write_step_summary(summary_path, passed, failed, warns, results)

    return failed == 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="v4 visual QA sweep for averagejoematt.com")
    ap.add_argument("--page", help="Test a single page path (e.g. /cockpit/)")
    ap.add_argument("--screenshot", action="store_true", help="Save full-page + chart-crop + mobile screenshots")
    ap.add_argument("--ai-qa", action="store_true", help="Run Claude (Bedrock) semantic QA over the screenshots")
    ap.add_argument(
        "--reader-truth",
        action="store_true",
        help="Run the phase-aware reader-truth QA over each page's rendered prose (#1095; high severity gates like --ai-qa)",
    )
    args = ap.parse_args()

    pages = None
    if args.page:
        pages = [p for p in PAGES if p["path"] == args.page]
        if not pages:
            print(f"Unknown page: {args.page}\nAvailable: {', '.join(p['path'] for p in PAGES)}")
            sys.exit(1)

    print(f"v4 Visual QA Sweep — {SITE_URL}\n{'=' * 56}")
    ok = run_sweep(pages=pages, save_screenshots=args.screenshot, ai_qa=args.ai_qa, reader_truth=args.reader_truth)
    sys.exit(0 if ok else 1)
