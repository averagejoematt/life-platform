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
     and the tap-target floor audit (#1010/#1249, gating: effective hit area ≥ 44px).
  6. Captures full-page + per-chart element screenshots.
  7. Optional --ai-qa: hands the screenshots to Claude (Bedrock) for semantic
     "does this actually render correctly" judgement — robust to daily data changes
     where pixel-diff would be brittle (see tests/visual_ai_qa.py).
  8. Detects stuck loading text, JS errors, 5xx responses, empty sections.
  9. axe-core accessibility audit per page (#1433, vendored bundle — no CDN):
     GATES on NEW serious/critical violations vs the committed baseline
     (tests/a11y_baseline.json); baselined + minor/moderate findings are
     recorded honestly as warnings, never hidden, never gating. Baseline
     shrinks/updates DELIBERATELY via --update-baseline (see tests/a11y_audit.py
     for the full semantics + review discipline).
  10. Leak-token sweep (#1448, deterministic, no AI, no browser): the SAME
      token-grep deploy/restart_verify_rendered.py runs at reset time
      (tests/leak_token_sweep.py) also runs here on every sweep, so a
      template/leak-token regression (a stale literal, a cached S3 JSON blob,
      a missed DDB partition) is caught within a day instead of only at the
      next reset. --no-leak-scan is the debug escape hatch.

The site is PUBLIC (no cf-auth gate) — no authentication needed.

Usage:
    python3 tests/visual_qa.py                      # full sweep, no AI
    python3 tests/visual_qa.py --page /cockpit/         # single page
    python3 tests/visual_qa.py --screenshot         # save full-page + chart crops
    python3 tests/visual_qa.py --screenshot --ai-qa # + Claude semantic verdict per image (full surface)
    python3 tests/visual_qa.py --screenshot --ai-qa --ai-qa-max-tier 1
                                                    # + Claude semantic verdict, tier-1 pages only (#1428;
                                                    #   what CI runs at deploy time)
    python3 tests/visual_qa.py --screenshot --ai-qa --reader-truth
                                                    # + phase-aware truth pass over each
                                                    #   page's rendered prose (#1095)
    python3 tests/visual_qa.py --update-baseline    # rewrite tests/a11y_baseline.json from
                                                    #   this run's axe findings (#1433; deliberate,
                                                    #   review the diff — the run still reds on NEW
                                                    #   violations so nothing is silently absorbed)
    python3 tests/visual_qa.py --no-a11y            # skip the axe pass (debug escape hatch;
                                                    #   every CI run keeps it on)
    python3 tests/visual_qa.py --browser webkit --mobile --max-tier 2 --screenshot
                                                    # the weekly ADVISORY iOS-Safari-engine run
                                                    #   (#1434; .github/workflows/webkit-mobile-qa.yml):
                                                    #   WebKit at an iPhone-class profile over the
                                                    #   tier-1/2 manifest pages

Cost: $0 for the browser sweep. --ai-qa adds a few Bedrock vision calls (Haiku,
~$0.001/image; pennies per run, and it no-ops cleanly if AI is unavailable/budget-paused).
Tiered by design (#1428): CI's deploy-time gate runs --ai-qa-max-tier 1 (the 6 flagship
doors only); the full untiered surface runs on the weekly standalone schedule
(.github/workflows/visual-qa.yml) to keep AI-vision spend bounded — see that
workflow's header comment for the exact cadence split.
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

# ── Page definitions — derived from THE page registry (tests/qa_manifest.py, #1426).
# The sweep's coverage facet is every manifest entry carrying a `visual` def (or
# `visual_variants` for deep-link sweeps). Adding a page to the sweep = setting
# `visual=` on its manifest entry — there is NO page list in this file anymore.
# Derivation verified identical to the pre-#1426 hand list (36 entries, same
# paths + checks); tests/test_qa_manifest.py gates the derivation from drifting.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a11y_audit  # noqa: E402  (#1433 — pure module, no Playwright import)
import leak_token_sweep  # noqa: E402  (#1448 — pure module, no Playwright import)
from qa_manifest import leak_scan_paths, visual_pages  # noqa: E402

PAGES = visual_pages()

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


def _constellation_edge_cpts(page):
    """#1215 regression guard. The home constellation's edge evidence (r, n, significance)
    must ride the site's ONE shared data-cpts readout (hover + tap + keyboard), not a
    hover-only native <title> that touch and keyboard can never reach.

    Assert the constellation svg CARRIES a data-cpts attribute (present even at zero edges)
    whose point count >= the number of served edge <line>s. Non-vacuous: the PRE-FIX svg has
    no data-cpts attribute at all, so this fails regardless of how many edges the live
    coupling data currently has (it fails even at 0 edges) — see test_constellation_edge_cpts.
    """
    return page.evaluate(
        """() => {
        const svg = document.querySelector('.constellation svg');
        if (!svg) return { skip: 'no constellation svg on this page' };
        const edges = svg.querySelectorAll('[data-edges] line').length;
        const raw = svg.getAttribute('data-cpts');
        if (raw === null)
            return { ok: false, edges, reason: 'svg carries no data-cpts attribute — edge evidence is still hover-only <title>' };
        let pts;
        try { pts = JSON.parse(raw); } catch (e) { return { ok: false, edges, reason: 'data-cpts is not valid JSON' }; }
        const n = Array.isArray(pts) ? pts.length : -1;
        if (n < edges) return { ok: false, edges, n, reason: `data-cpts has ${n} point(s) < ${edges} served edge line(s)` };
        return { ok: true, edges, n };
    }"""
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
                        const txt = w.currentNode.textContent;
                        if (s.pattern.test(txt)) {
                            // "coming soon" on /gear/ is sanctioned, permanent-until-launched
                            // affiliate-program copy (v4_build_gear.py — the page's own
                            // disclosure explains it), not stuck pre-launch placeholder text.
                            // Both occurrences carry "affiliate" in the same text node, so
                            // that's the discriminator — the genuine "site launching April"
                            // class has no reason to mention affiliates (#1427).
                            if (s.desc === 'Pre-launch copy still visible' && /affiliate/i.test(txt)) continue;
                            const el = w.currentNode.parentElement;
                            if (el && el.offsetParent !== null && el.offsetHeight > 0) {
                                issues.push({text: txt.trim().slice(0, 60), desc: s.desc});
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
# so they become regression tests, not lore. (a)-(d) all gate now — (d) the 44px
# tap-target floor (Epic B #1010) was promoted advisory → gating by #1249.

# Mirrors the reveal selector in site/assets/js/motion.js — an element matching this
# that stays opacity:0 after a scroll-through is the #1002 tall-section reveal bug.
MOBILE_REVEAL_SEL = (
    ".hero, .page-hero, .ev-head, .dx-head, .beat, .loop, .rd-sec, .two-voice, "
    ".coach-daily, .coach-progress, .coach-report, .coach-stance, .team-lead, "
    ".team-focus, .team-tension, .team-huddle, .supp, .cap-card, .vr-row, .figs, .ml-ladder"
)

# GATING (#1010/#1249): the cockpit's headline controls + site-wide chrome the review
# measured under the 44px floor, plus the home waveform day-bar anchors (.wave a.bar,
# #1249). The audit gates on the EFFECTIVE hit area (own box unioned with any generated
# ::after/::before overlay — the documented #1010 grammar) and only fails a target that
# is below the floor in BOTH axes, so a wide inline text link or a control expanded to
# 44px in one axis by the ::after grammar passes; a target tiny in both axes (the pre-fix
# 2px×13px day-bar) fails. This finishes #1013 as designed (advisory → gating).
TAP_TARGET_SEL = ".doors .theme-toggle, .tt-scrubber, .intro-close, .breadcrumbs a, .ev-link, .cta-quiet, .wave a.bar"


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
    """#1010/#1249 tap-target floor (GATING): interactive controls whose EFFECTIVE hit
    area is below the 44px floor in BOTH axes. The effective box is the element's own
    rect unioned with any generated ::before/::after overlay — the documented #1010
    grammar (a transparent, centered/anchored pseudo-element) enlarges the clickable
    region without a visual change, and getBoundingClientRect alone can't see it. A
    target below the floor in only ONE axis is an accepted affordance (a wide inline text
    link; a control lifted to 44px in one axis by the ::after grammar, e.g. the app-bar
    toggle or the #1249 waveform day-bars); a target tiny in BOTH axes is genuinely
    un-tappable and fails the sweep."""
    return page.evaluate(
        """(sel) => {
        const out = [];
        document.querySelectorAll(sel).forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;        // not rendered
            let w = r.width, h = r.height;
            // Fold in the #1010 hit-expander pseudo-elements: a generated ::after/::before
            // (content !== 'none') carries the real touch area. Chromium resolves its
            // width/height to used px, so max() over own+pseudo is the effective hit box.
            for (const pe of ['::before', '::after']) {
                const ps = getComputedStyle(el, pe);
                if (!ps || ps.content === 'none' || ps.content === 'normal') continue;
                const pw = parseFloat(ps.width), ph = parseFloat(ps.height);
                if (!isNaN(pw)) w = Math.max(w, pw);
                if (!isNaN(ph)) h = Math.max(h, ph);
            }
            if (w < 44 && h < 44) {
                out.push(`${(el.className||el.tagName).toString().slice(0,28)} ${Math.round(w)}x${Math.round(h)} eff`);
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


def _write_step_summary(path, passed, failed, warns, results, reader_truth_status=None, ai_vision_status=None):
    """Append a Markdown summary to $GITHUB_STEP_SUMMARY (CI job summary)."""
    lines = [f"## Visual + AI-vision QA — {passed} passed, {failed} failed, {warns} warnings\n"]
    # #1440/#1428: a budget-tier pause must render as its own line in the CI
    # summary — never silently absent, never indistinguishable from a clean run.
    if ai_vision_status and ai_vision_status.get("status") == "skipped_by_budget":
        lines.append(f"⏸ **AI-vision QA: SKIPPED-BY-BUDGET** (tier {ai_vision_status['tier']}) — not run, not a pass.\n")
    if reader_truth_status and reader_truth_status.get("status") == "skipped_by_budget":
        lines.append(f"⏸ **Reader-truth QA: SKIPPED-BY-BUDGET** (tier {reader_truth_status['tier']}) — not run, not a pass.\n")
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


def run_leak_token_sweep(base_url=None):
    """Deterministic, AI-free leak-token sweep (#1448).

    Reuses the SAME token-grep deploy/restart_verify_rendered.py runs at reset
    time (tests/leak_token_sweep.py) so a template/leak-token regression — a
    hardcoded stale literal, a cached S3 JSON blob, a missed DDB partition — is
    caught within a day instead of only at the next reset. Plain urllib + regex
    over leak_scan_paths() + the JSON endpoints; no Playwright, no Bedrock, no
    cost. tokens_for_daily_run() drops the reset-window-only checks (Day-30+,
    character level, ...) once the current cycle has legitimately matured past
    them, so real progress never reds this.

    Returns {"ok": bool, "checked": int, "issues": [str, ...]}.
    """
    base_url = base_url or SITE_URL
    tokens = leak_token_sweep.tokens_for_daily_run()
    pages = leak_scan_paths()
    page_results = leak_token_sweep.sweep(
        base_url,
        pages,
        leak_token_sweep.JSON_ENDPOINTS,
        tokens=tokens,
        allow_503_paths=leak_token_sweep.ALLOW_503_NOT_COMPUTED,
    )
    issues = []
    for r in page_results:
        for label, samples in r["hits"]:
            issues.append(f"{r['path']} — [{label}] {' | '.join(samples)}")
    return {"ok": not issues, "checked": len(page_results), "issues": issues}


# ══════════════════════════════════════════════════════════════════════════════
# Main sweep
# ══════════════════════════════════════════════════════════════════════════════


def capture_page(context, page_def, screenshot_dir, save_screenshots=False, capture_prose=False, a11y_baseline=None):
    """Drive one page def in an open browser context and return its result dict.

    Pure capture: navigate, scroll/reveal, run element/chart/interaction checks,
    blank/stale-text scan, optional screenshots (full + chart crops + 390px mobile),
    HTTP/JS failure collection. No printing, no AI-QA, no report writing — those
    stay in run_sweep so its CI behaviour is byte-for-byte unchanged. Returns:
        {"page", "path", "status", "issues", "warnings", "screenshots"}

    a11y_baseline (#1433): pass a loaded tests/a11y_baseline.json dict to run the
    axe-core audit on this page (run_sweep does; NEW serious/critical violations
    vs the baseline become gating issues). The default None skips it, so the
    direct capture_page callers (site_review, pr_render_gate) are byte-for-byte
    unchanged — they render against mocked/partial data where axe findings
    would not match the live-surface baseline.

    Extracted from run_sweep's per-page loop (2026-06-20) so tests/site_review.py
    can reuse identical capture without forking the gating visual-qa harness.
    """
    page = context.new_page()
    page.add_init_script(_PERF_INIT_SCRIPT)
    path, name = page_def["path"], page_def["name"]
    a11y_result = None
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

        # ── #1215: the home constellation's edge evidence must ride the shared data-cpts
        #    readout (hover + tap + keyboard), not a hover-only native <title>. GATING. ──
        if path == "/":
            ec = _constellation_edge_cpts(page)
            if ec and not ec.get("ok") and not ec.get("skip"):
                issues.append(f"Constellation edge readout gap (#1215): {ec.get('reason')}")

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

        # ── axe-core accessibility audit (#1433) — desktop viewport, post-reveal ──
        # Runs after _scroll_and_reveal forced every section visible so axe sees the
        # page a reader sees (color-contrast on revealed content, not opacity:0).
        # Gate: NEW serious/critical vs the committed baseline red the page; every
        # other finding (baselined debt, new minor/moderate, fixed-vs-baseline) is
        # recorded honestly as a warning — visible, never gating, never hidden.
        if a11y_baseline is not None:
            try:
                observed = a11y_audit.run_axe(page)
            except Exception as e:
                observed = None
                warnings.append(f"a11y audit did not run (axe inject/run failed: {str(e)[:100]}) — not a pass (#1433)")
            if observed is not None:
                a11y_result = a11y_audit.gate_findings(path, observed, a11y_baseline)
                for v in a11y_result["new"]:
                    tgt = f" e.g. {v['targets'][0]}" if v.get("targets") else ""
                    issues.append(f"NEW {v['impact']} a11y violation (axe: {v['id']}): {v['help']} — {v['nodes']} node(s){tgt} (#1433)")
                if a11y_result["baselined"]:
                    ids = ", ".join(sorted(v["id"] for v in a11y_result["baselined"]))
                    warnings.append(
                        f"a11y baseline debt: {len(a11y_result['baselined'])} known violation(s) ({ids}) — recorded, not gating (#1433)"
                    )
                if a11y_result["advisory"]:
                    ids = ", ".join(sorted(v["id"] for v in a11y_result["advisory"]))
                    warnings.append(
                        f"a11y advisory: {len(a11y_result['advisory'])} new minor/moderate violation(s) ({ids}) — not gating (#1433)"
                    )
                if a11y_result["fixed"]:
                    warnings.append(
                        f"a11y fixed vs baseline: {', '.join(a11y_result['fixed'])} — shrink the ledger via --update-baseline (#1433)"
                    )

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
        # (d) #1010/#1249 — tap-target floor, GATING: any known-good control whose
        #     effective hit area is below 44px in BOTH axes fails the sweep (advisory →
        #     gating, finishing #1013; #1249 added .wave a.bar after the day-bars got the
        #     vertical ::after expander).
        small = _tap_target_audit(page, TAP_TARGET_SEL)
        if small:
            issues.append(f"Tap targets < 44px in both axes @390px (#1010/#1249): {', '.join(small[:5])}")
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
        "tier": page_def.get("tier"),  # #1428: lets run_sweep restrict the AI-vision layer by tier
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "warnings": warnings,
        "screenshots": shots,
        "perf": perf_result,
        "a11y": a11y_result,  # #1433: new/baselined/advisory/fixed/observed, or None if the audit didn't run
    }


def sweep_pages(pages, max_tier=None):
    """Which page defs the DETERMINISTIC sweep drives (#1434).

    Pure/testable (no Playwright dependency), mirroring ai_qa_targets semantics:
    max_tier=None returns the list unchanged (every existing caller — the gating
    deploy-time sweep and the daily standalone run — passes nothing, so their
    coverage is byte-for-byte what it was). An int restricts to page defs whose
    qa_manifest `tier` is <= max_tier: the weekly WebKit run passes 2 to sweep
    exactly the flagship doors + live-data topic pages. A missing/None tier is
    treated as tier 0 (always included) rather than silently dropped.
    """
    if max_tier is None:
        return pages
    return [p for p in pages if (p.get("tier") if p.get("tier") is not None else 0) <= max_tier]


def ai_qa_targets(results, max_tier=None):
    """Which captured-page results get handed to the AI-vision pass (#1428).

    Pure/testable (no Playwright/Bedrock dependency): max_tier=None returns every
    result unchanged (the weekly full-surface behavior); an int restricts to results
    whose `tier` is <= max_tier (deploy-time passes 1 for exactly the flagship doors).
    A missing/None tier on a result is treated as tier 0 (always included) rather than
    silently dropped — an untiered page should never vanish from AI coverage by accident.
    """
    if max_tier is None:
        return results
    return [r for r in results if (r.get("tier") if r.get("tier") is not None else 0) <= max_tier]


def run_sweep(
    pages=None,
    save_screenshots=False,
    screenshot_dir=None,
    ai_qa=False,
    reader_truth=False,
    ai_qa_max_tier=None,
    browser_name="chromium",
    mobile=False,
    max_tier=None,
    a11y=True,
    update_a11y_baseline=False,
    leak_scan=True,
):
    """Run the v4 visual QA sweep. Returns True if no page FAILED.

    leak_scan (#1448): runs the deterministic, AI-free leak-token sweep
    (tests/leak_token_sweep.py — the same checks deploy/restart_verify_rendered.py
    runs at reset time) against SITE_URL and folds any hit into the pass/fail
    tally as a synthetic "page" result. True by default (every existing gating
    run gets it automatically); the CLI's --no-leak-scan is the debug escape
    hatch, mirroring --no-a11y.

    a11y / update_a11y_baseline (#1433): the axe-core audit runs per page by
    default (a11y=False is the debug escape hatch — CI never passes it); NEW
    serious/critical violations vs tests/a11y_baseline.json gate like any other
    page issue. update_a11y_baseline=True rewrites the baseline from this run's
    observations for the pages actually swept (the deliberate, reviewed update
    path — the run STILL reports new violations red so nothing is silently
    absorbed; the committed baseline diff is the review surface).

    ai_qa_max_tier (#1428): when set, restricts the Claude-vision assessment to
    pages whose qa_manifest tier is <= this value (deploy-time passes `1` to cover
    exactly the 6 flagship doors). The deterministic Playwright sweep above is
    NEVER affected by this — `pages` (or the full PAGES list) still drives it, so
    coverage there stays exactly what it is today. None (the default, used by the
    weekly full-surface run) assesses every captured page — unchanged behavior.

    browser_name / mobile / max_tier (#1434): the weekly advisory WebKit run
    (.github/workflows/webkit-mobile-qa.yml) passes browser_name="webkit",
    mobile=True, max_tier=2 to drive the iOS-Safari engine at an iPhone-class
    viewport over the tier-1/2 pages — the backdrop-filter/position:fixed bug
    class Chromium emulation cannot see (memory: project_mobile_pwa). mobile=True
    opens the context at 390x844, dpr 3, is_mobile + has_touch (explicit metrics
    rather than a Playwright device descriptor so a descriptor rename between
    Playwright versions can never silently change the run; the UA stays the
    engine default — the site does no UA sniffing, the ENGINE is the coverage).
    capture_page's own in-page viewport passes (390/844, 360/800, 1280) behave
    exactly as before. Defaults reproduce today's gating runs byte-for-byte.
    """
    from playwright.sync_api import sync_playwright

    if screenshot_dir is None:
        screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "qa-screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    results = []
    # AI-QA needs the screenshots, so force-enable capture when --ai-qa is set.
    if ai_qa:
        save_screenshots = True

    # #1433: load the committed a11y baseline once; None disables the audit.
    a11y_baseline = a11y_audit.load_baseline() if (a11y or update_a11y_baseline) else None

    with sync_playwright() as p:
        browser = getattr(p, browser_name).launch(headless=True)
        if mobile:
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
                color_scheme="dark",
            )
        else:
            context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")

        for page_def in sweep_pages(pages or PAGES, max_tier):
            # --reader-truth needs each page's rendered innerText (the prose dump).
            result = capture_page(
                context, page_def, screenshot_dir, save_screenshots, capture_prose=reader_truth, a11y_baseline=a11y_baseline
            )
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
    # #1428: restrict WHICH pages get assessed to ai_qa_max_tier (deploy-time
    # passes 1 → exactly the tier-1 doors); the deterministic checks above already
    # ran over every page in `pages`/PAGES regardless, so tiering the AI layer
    # never reduces deterministic coverage. None (weekly full-surface run) skips
    # the filter and assesses every captured page, same as before #1428.
    ai_vision_status = None
    if ai_qa:
        try:
            from visual_ai_qa import assess_results
        except ImportError:
            sys.path.insert(0, os.path.dirname(__file__))
            from visual_ai_qa import assess_results
        ai_targets = ai_qa_targets(results, ai_qa_max_tier)
        if ai_qa_max_tier is not None:
            print(f"\n── AI-vision QA (Claude / Bedrock) — tier <= {ai_qa_max_tier}: {len(ai_targets)}/{len(results)} pages ──")
        else:
            print("\n── AI-vision QA (Claude / Bedrock) — full surface ──")
        ai_vision_status = assess_results(ai_targets)  # mutates ai_targets in place: adds ai_verdict + may add issues

    # ── optional phase-aware reader-truth QA over the captured prose (#1095) ──
    reader_truth_status = None
    if reader_truth:
        try:
            from visual_ai_qa import assess_reader_truth
        except ImportError:
            sys.path.insert(0, os.path.dirname(__file__))
            from visual_ai_qa import assess_reader_truth
        print("\n── Reader-truth QA (phase-aware, Claude / Bedrock) ──")
        reader_truth_status = assess_reader_truth(results)  # mutates results: truth_findings + high → FAIL

    # ── deliberate a11y-baseline rewrite (#1433) — only the pages this run swept ──
    if update_a11y_baseline:
        observed_by_path = {r["path"]: r["a11y"]["observed"] for r in results if r.get("a11y") is not None}
        skipped = [r["path"] for r in results if r.get("a11y") is None]
        if observed_by_path:
            new_baseline = a11y_audit.update_baseline(observed_by_path)
            counts = a11y_audit.summarize(new_baseline)
            counts_str = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "clean — no violations"
            print(f"\na11y baseline rewritten ({len(observed_by_path)} page(s) captured) → tests/a11y_baseline.json")
            print(f"  ledger now: {counts_str} — review + commit the diff deliberately (#1433)")
        if skipped:
            print(f"  ⚠ a11y baseline NOT updated for {len(skipped)} page(s) where the audit failed to run: {', '.join(skipped[:5])}")

    # ── deterministic leak-token sweep (#1448) — no AI, no browser; reuses the
    # SAME token-grep deploy/restart_verify_rendered.py runs at reset time, so a
    # template/leak-token regression is caught within a day instead of only at
    # the next reset. Appended AFTER the AI-vision/reader-truth/a11y passes
    # above so it never becomes an accidental AI-vision or a11y target (it has
    # no screenshot/a11y payload) — it only affects the pass/fail tally + the
    # reports below.
    if leak_scan:
        leak_status = run_leak_token_sweep()
        icon = "✅" if leak_status["ok"] else "❌"
        print("\n── Leak-token sweep (deterministic, #1448) ──")
        print(f"  {icon} {leak_status['checked']} URL(s) checked, {len(leak_status['issues'])} finding(s)")
        for x in leak_status["issues"]:
            print(f"      → {x}")
        results.append(
            {
                "page": "Leak-token sweep",
                "path": "(cross-cutting — leak_scan_paths + JSON endpoints)",
                "status": "PASS" if leak_status["ok"] else "FAIL",
                "issues": leak_status["issues"],
                "warnings": [],
                "screenshots": {},
            }
        )

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warns = sum(len(r.get("warnings", [])) for r in results)
    print(f"\n{'=' * 56}")
    print(f"Visual QA: {passed} passed, {failed} failed, {warns} warning(s) across {len(results)} pages")
    # #1440/#1428: a budget-tier pause of an AI QA pass must read as its own
    # explicit state, never blend into "passed" — this is the one line a human
    # or a CI summary skim is guaranteed to see regardless of page-level warnings.
    if ai_vision_status and ai_vision_status.get("status") == "skipped_by_budget":
        print(f"AI-vision QA: SKIPPED-BY-BUDGET (tier {ai_vision_status['tier']}) — not run, not a pass")
    if reader_truth_status and reader_truth_status.get("status") == "skipped_by_budget":
        print(f"Reader-truth QA: SKIPPED-BY-BUDGET (tier {reader_truth_status['tier']}) — not run, not a pass")
    if save_screenshots:
        print(f"Screenshots: {screenshot_dir}/")

    with open(os.path.join(screenshot_dir, "report.json"), "w") as f:
        json.dump(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "browser": browser_name,
                "mobile": mobile,
                "max_tier": max_tier,
                "passed": passed,
                "failed": failed,
                "warnings": warns,
                "ai_vision_status": ai_vision_status,
                "reader_truth_status": reader_truth_status,
                "results": results,
            },
            f,
            indent=2,
        )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        _write_step_summary(summary_path, passed, failed, warns, results, reader_truth_status, ai_vision_status)

    return failed == 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="v4 visual QA sweep for averagejoematt.com")
    ap.add_argument("--page", help="Test a single page path (e.g. /cockpit/)")
    ap.add_argument("--screenshot", action="store_true", help="Save full-page + chart-crop + mobile screenshots")
    ap.add_argument("--ai-qa", action="store_true", help="Run Claude (Bedrock) semantic QA over the screenshots")
    ap.add_argument(
        "--ai-qa-max-tier",
        type=int,
        default=None,
        help=(
            "Restrict --ai-qa to qa_manifest pages with tier <= N (#1428; deploy-time CI passes 1 to cover exactly "
            "the 6 flagship doors). Omit for the full-surface pass (the weekly scheduled run). Never affects the "
            "deterministic Playwright coverage, which always runs over every page in --page/PAGES."
        ),
    )
    ap.add_argument(
        "--reader-truth",
        action="store_true",
        help="Run the phase-aware reader-truth QA over each page's rendered prose (#1095; high severity gates like --ai-qa)",
    )
    ap.add_argument(
        "--browser",
        choices=["chromium", "webkit", "firefox"],
        default="chromium",
        help="Playwright engine to drive (#1434; the weekly advisory iOS-Safari-engine run passes webkit)",
    )
    ap.add_argument(
        "--mobile",
        action="store_true",
        help="Open the browser context at an iPhone-class mobile profile (390x844, dpr 3, touch) instead of 1440x900 desktop (#1434)",
    )
    ap.add_argument(
        "--no-a11y",
        action="store_true",
        help="Skip the axe-core accessibility audit (#1433). Debug escape hatch only — every CI run keeps the audit on.",
    )
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Rewrite tests/a11y_baseline.json from this run's axe findings for the pages swept (#1433). DELIBERATE path: "
            "the run still reds on NEW serious/critical violations, and the committed baseline diff is the review surface "
            "(added entries = newly accepted debt, removed = fixes). See tests/a11y_audit.py."
        ),
    )
    ap.add_argument(
        "--max-tier",
        type=int,
        default=None,
        help=(
            "Restrict the DETERMINISTIC sweep to qa_manifest pages with tier <= N (#1434; the weekly WebKit run passes 2 "
            "for the flagship doors + live-data topic pages). Omit for full coverage — every existing gating run does."
        ),
    )
    ap.add_argument(
        "--no-leak-scan",
        action="store_true",
        help=(
            "Skip the deterministic leak-token sweep (#1448; tests/leak_token_sweep.py — the same checks "
            "deploy/restart_verify_rendered.py runs at reset time). Debug escape hatch only — every CI run keeps it on."
        ),
    )
    args = ap.parse_args()

    pages = None
    if args.page:
        pages = [p for p in PAGES if p["path"] == args.page]
        if not pages:
            print(f"Unknown page: {args.page}\nAvailable: {', '.join(p['path'] for p in PAGES)}")
            sys.exit(1)

    profile = f" [{args.browser}{', mobile' if args.mobile else ''}{f', tier<={args.max_tier}' if args.max_tier is not None else ''}]"
    print(f"v4 Visual QA Sweep — {SITE_URL}{profile if profile != ' [chromium]' else ''}\n{'=' * 56}")
    ok = run_sweep(
        pages=pages,
        save_screenshots=args.screenshot,
        ai_qa=args.ai_qa,
        reader_truth=args.reader_truth,
        ai_qa_max_tier=args.ai_qa_max_tier,
        browser_name=args.browser,
        mobile=args.mobile,
        max_tier=args.max_tier,
        a11y=not args.no_a11y,
        update_a11y_baseline=args.update_baseline,
        leak_scan=not args.no_leak_scan,
    )
    sys.exit(0 if ok else 1)
