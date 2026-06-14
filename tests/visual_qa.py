#!/usr/bin/env python3
"""
visual_qa.py — Playwright visual QA sweep for averagejoematt.com (v4 "The Measured Life")

Deep render verification of the three-door v4 site (ADR-071), over the unchanged
read-only engine:
  1. Drives Chromium over the v4 surfaces (Home/Cockpit/Story/Evidence + topics).
  2. Scrolls each page top-to-bottom (triggers lazy data fetch + .reveal animations).
  3. Verifies key containers rendered + inline-SVG charts have drawn geometry.
  4. Exercises one interaction (cockpit pillar disclosure → Day-Grade Replay detail).
  5. Checks responsive overflow at a mobile width (390px).
  6. Captures full-page + per-chart element screenshots.
  7. Optional --ai-qa: hands the screenshots to Claude (Bedrock) for semantic
     "does this actually render correctly" judgement — robust to daily data changes
     where pixel-diff would be brittle (see tests/visual_ai_qa.py).
  8. Detects stuck loading text, JS errors, 5xx responses, empty sections.

The site is PUBLIC (no cf-auth gate) — no authentication needed.

Usage:
    python3 tests/visual_qa.py                      # full sweep, no AI
    python3 tests/visual_qa.py --page /now/         # single page
    python3 tests/visual_qa.py --screenshot         # save full-page + chart crops
    python3 tests/visual_qa.py --screenshot --ai-qa # + Claude semantic verdict per image

Cost: $0 for the browser sweep. --ai-qa adds a few Bedrock vision calls (Haiku,
~$0.001/image; pennies per run, and it no-ops cleanly if AI is unavailable/budget-paused).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SITE_URL = "https://averagejoematt.com"

# Topics whose readout is expected to include at least one inline-SVG chart.
# (Others are tables/cards — and even chart topics legitimately show an honest
# "N readings so far" text instead of a chart when data is sparse, per
# site/assets/js/charts.js's >=4-points rule — so missing-chart is a WARNING.)
CHART_TOPICS = {"vitals", "physical", "glucose", "sleep", "training"}
EVIDENCE_TOPICS = [
    "vitals",
    "physical",
    "labs",
    "glucose",
    "sleep",
    "training",
    "nutrition",
    "habits",
    "board",
    "pipeline",
    # S-05 (2026-06-06): the 3 bespoke renderers added by S-02. Empty this
    # genesis week (honest empty-states), rich readouts as data accrues —
    # the [data-readout] not_empty check covers both states.
    "intelligence",
    "predictions",
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
                "selector": "a[href='/now/'], a[href='/story/'], a[href='/evidence/']",
                "min_count": 2,
                "desc": "the three door links present",
            },
        ],
        "charts": [".constellation svg"],
    },
    {
        "path": "/now/",
        "name": "Cockpit",
        "wait_for": "[data-bind='level']",
        "checks": [
            {"selector": "[data-bind='level']", "not_empty": True, "desc": "character level rendered"},
            {"selector": ".row", "min_count": 1, "desc": "at least one pillar row"},
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
            {"selector": "a[href='/evidence/'], a[href='/now/']", "min_count": 1, "desc": "door links present"},
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
        "path": "/story/coaches/",
        "name": "Story · The Coaches (roster)",
        "wait_for": ".dx-item",
        "checks": [
            {"selector": ".dx-item", "min_count": 1, "desc": "coach roster list rendered"},
            {"selector": ".dx-read .coach-stance, .dx-read .dx-title", "not_empty": True, "desc": "a coach page renders in the reader"},
        ],
    },
    {
        "path": "/story/coaches/#sleep_coach",
        "name": "Story · coach page (deep-link)",
        "wait_for": ".coach-report",
        "checks": [
            {"selector": ".coach-stance", "not_empty": True, "desc": "stance section (lead)"},
            {"selector": ".coach-report", "not_empty": True, "desc": "report card present"},
            {"selector": ".dx-disclosure", "not_empty": True, "desc": "AI-character disclosure present"},
        ],
    },
    {
        "path": "/evidence/",
        "name": "Evidence hub",
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "evidence readout rendered"}],
    },
]
# Evidence live-data topics — readout must render; chart topics get a soft chart check + crop.
for _slug in EVIDENCE_TOPICS:
    PAGES.append(
        {
            "path": f"/evidence/{_slug}/",
            "name": f"Evidence · {_slug}",
            "wait_for": "[data-readout]",
            "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": f"{_slug} readout rendered"}],
            "charts": ["[data-readout] svg"] if _slug in CHART_TOPICS else [],
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


def run_sweep(pages=None, save_screenshots=False, screenshot_dir=None, ai_qa=False):
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
            page = context.new_page()
            path, name = page_def["path"], page_def["name"]
            issues, warnings, js_errors, failed_responses, shots = [], [], [], [], []

            _noncrit = ["favicon", "sub_count", "subscriber_count"]
            page.on(
                "console", lambda m: js_errors.append(m.text) if m.type == "error" and not any(nc in m.text for nc in _noncrit) else None
            )
            page.on("pageerror", lambda err: js_errors.append(str(err)))
            page.on(
                "response",
                lambda r: (
                    failed_responses.append((r.status, r.url)) if r.status >= 400 and not any(nc in r.url for nc in _noncrit) else None
                ),
            )

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

                # ── responsive overflow @ 390px ──
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(400)
                overflow = _mobile_overflow(page)
                if overflow and overflow > 4:
                    issues.append(f"Horizontal overflow at 390px — content exceeds viewport by {overflow}px")
                if save_screenshots:
                    mob = os.path.join(screenshot_dir, f"{slug}-mobile.png")
                    page.screenshot(path=mob, full_page=True)
                    shots.append({"kind": "mobile", "path": mob})

                # ── failed HTTP calls (broken /api/ calls fail; other resources warn) ──
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

            results.append(
                {
                    "page": name,
                    "path": path,
                    "status": "PASS" if not issues else "FAIL",
                    "issues": issues,
                    "warnings": warnings,
                    "screenshots": shots,
                }
            )
            icon = "✅" if not issues else "❌"
            warn = f" ({len(warnings)} warning{'s' if len(warnings) != 1 else ''})" if warnings else ""
            print(f"  {icon} {name} ({path}){warn}")
            for x in issues:
                print(f"      → {x}")
            for w in warnings:
                print(f"      ⚠ {w}")
            page.close()

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
    ap.add_argument("--page", help="Test a single page path (e.g. /now/)")
    ap.add_argument("--screenshot", action="store_true", help="Save full-page + chart-crop + mobile screenshots")
    ap.add_argument("--ai-qa", action="store_true", help="Run Claude (Bedrock) semantic QA over the screenshots")
    args = ap.parse_args()

    pages = None
    if args.page:
        pages = [p for p in PAGES if p["path"] == args.page]
        if not pages:
            print(f"Unknown page: {args.page}\nAvailable: {', '.join(p['path'] for p in PAGES)}")
            sys.exit(1)

    print(f"v4 Visual QA Sweep — {SITE_URL}\n{'=' * 56}")
    ok = run_sweep(pages=pages, save_screenshots=args.screenshot, ai_qa=args.ai_qa)
    sys.exit(0 if ok else 1)
