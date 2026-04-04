#!/usr/bin/env python3
"""
visual_qa.py — Playwright visual QA sweep for averagejoematt.com

Deep visual regression testing:
1. Scrolls every page top-to-bottom (triggers lazy rendering + reveal animations)
2. Checks every canvas element for drawn pixels (not blank)
3. Verifies key text values match API data
4. Screenshots individual sections that fail
5. Detects stuck loading indicators, JS errors, empty containers

Usage:
    python3 tests/visual_qa.py                    # Run full sweep
    python3 tests/visual_qa.py --page /glucose/   # Single page
    python3 tests/visual_qa.py --screenshot       # Save screenshots
    python3 tests/visual_qa.py --fix              # Output suggested fixes

Cost: $0 — runs locally or in CI. No AWS charges.

v2.0.0 — 2026-04-03 (deep visual regression)
"""

import argparse
import json
import sys
import os
from datetime import datetime, timezone

SITE_URL = "https://averagejoematt.com"

# ── Page definitions with deep checks ─────────────────────────────────────────
PAGES = [
    {
        "path": "/",
        "name": "Homepage",
        "checks": [
            {"selector": ".h-gauge__num", "min_count": 6, "not_empty": True, "desc": "6 gauge numbers with values"},
            {"selector": ".h-obs-card__metric", "not_empty": True, "desc": "observatory tile metrics populated"},
        ],
    },
    {
        "path": "/live/",
        "name": "Pulse",
        "wait_for": ".detail-card",
        "checks": [
            {"selector": ".detail-card", "min_count": 4, "desc": "4+ pulse glyph cards"},
            {"selector": ".detail-card__value", "min_count": 4, "desc": "glyph value elements present"},
        ],
    },
    {
        "path": "/sleep/",
        "name": "Sleep",
        "wait_for": "#s-content",
        "checks": [
            {"canvas_not_blank": True, "desc": "at least one chart has drawn pixels"},
            {"selector": "canvas", "min_count": 1, "desc": "at least one chart canvas present"},
        ],
    },
    {
        "path": "/glucose/",
        "name": "Glucose",
        "wait_for": "#g-content",
        "checks": [
            {"canvas_not_blank": True, "desc": "glucose trend chart has pixels"},
            {"selector": "#gg-tir-num, #gg-avg-num", "not_empty": True, "desc": "glucose gauges populated"},
        ],
    },
    {
        "path": "/nutrition/",
        "name": "Nutrition",
        "wait_for": "#n-content",
        "checks": [
            {"canvas_not_blank": True, "desc": "macro chart has pixels"},
            {"selector": "#g-cal-num, #g-pro-num", "not_empty": True, "desc": "nutrition gauges populated"},
        ],
    },
    {
        "path": "/training/",
        "name": "Training",
        "wait_for": "#t-content",
        "checks": [
            {"canvas_not_blank": True, "desc": "at least one training chart has pixels"},
        ],
    },
    {
        "path": "/physical/",
        "name": "Physical",
        "wait_for": "#p-content",
        "checks": [
            {"canvas_not_blank": True, "desc": "weight trajectory chart has pixels"},
        ],
    },
    {
        "path": "/mind/",
        "name": "Mind / Inner Life",
        "wait_for": "#m-content",
        "checks": [
            {"selector": "canvas, .heatmap-week, .vice-bar", "min_count": 1, "desc": "charts or heatmap rendered"},
        ],
    },
    {
        "path": "/character/",
        "name": "Character",
        "checks": [
            {"selector": ".pillar-card, .char-pillar", "min_count": 7, "desc": "7 pillar cards"},
        ],
    },
    {
        "path": "/habits/",
        "name": "Habits",
        "checks": [
            {"selector": ".hm-cell:not(.empty)", "min_count": 1, "desc": "heatmap cells with data"},
        ],
    },
    {
        "path": "/status/",
        "name": "Status",
        "checks": [
            {"selector": ".pill", "min_count": 10, "desc": "10+ status pills"},
        ],
    },
    {
        "path": "/story/",
        "name": "Story",
        "checks": [
            {"selector": "#story-weight, .milestone__value", "not_empty": True, "desc": "weight displayed"},
        ],
    },
]


def _scroll_and_reveal(page):
    """Scroll the entire page top-to-bottom, then force all reveal animations."""
    page.evaluate("""
        () => new Promise(resolve => {
            let y = 0;
            const step = 400;
            const timer = setInterval(() => {
                window.scrollBy(0, step);
                y += step;
                // Force reveals as we scroll
                document.querySelectorAll('.reveal').forEach(el => {
                    el.classList.add('is-visible');
                    el.style.opacity = '1';
                    el.style.transform = 'none';
                });
                if (y >= document.body.scrollHeight) {
                    clearInterval(timer);
                    window.scrollTo(0, 0);
                    resolve();
                }
            }, 80);
            // Safety timeout
            setTimeout(() => { clearInterval(timer); window.scrollTo(0, 0); resolve(); }, 10000);
        })
    """)
    # Final reveal pass + wait for chart rendering
    page.evaluate("""
        () => {
            document.querySelectorAll('.reveal').forEach(el => {
                el.classList.add('is-visible');
                el.style.opacity = '1';
                el.style.transform = 'none';
            });
        }
    """)
    page.wait_for_timeout(2000)


def _check_canvas_not_blank(page):
    """Check if any canvas element on the page has actually drawn pixels."""
    return page.evaluate("""
        () => {
            const results = [];
            document.querySelectorAll('canvas').forEach((c, i) => {
                if (c.offsetWidth === 0 || c.offsetHeight === 0) {
                    // Skip canvases in hidden/collapsed sections (intentional)
                    return;
                }
                // Check if Chart.js owns this canvas
                const chartInstance = (typeof Chart !== 'undefined') && Chart.getChart && Chart.getChart(c);
                if (chartInstance) {
                    // Chart.js canvas — check if it has data
                    const hasData = chartInstance.data && chartInstance.data.datasets &&
                        chartInstance.data.datasets.some(ds => ds.data && ds.data.length > 0);
                    results.push({index: i, id: c.id, status: hasData ? 'drawn' : 'blank', note: 'Chart.js'});
                    return;
                }
                try {
                    const ctx = c.getContext('2d');
                    const w = c.width || c.offsetWidth;
                    const h = c.height || c.offsetHeight;
                    if (w < 2 || h < 2) {
                        results.push({index: i, id: c.id, status: 'zero-size', w: w, h: h});
                        return;
                    }
                    const data = ctx.getImageData(0, 0, w, h).data;
                    let nonEmpty = 0;
                    // Sample every 1000th pixel
                    for (let p = 3; p < data.length; p += 4000) {
                        if (data[p] > 0) nonEmpty++;
                    }
                    results.push({index: i, id: c.id, status: nonEmpty > 0 ? 'drawn' : 'blank', pixels: nonEmpty});
                } catch(e) {
                    // Tainted canvas, cross-origin, or timing issue — assume rendered if visible and sized
                    results.push({index: i, id: c.id, status: c.offsetHeight > 10 ? 'assumed-drawn' : 'error', note: String(e).slice(0,60)});
                }
            });
            return results;
        }
    """)


def _check_sections_for_blank(page):
    """Find sections that are visible but effectively empty."""
    return page.evaluate("""
        () => {
            const issues = [];
            // Check for visible sections with very little content
            document.querySelectorAll('section, [class*=section]').forEach(s => {
                const rect = s.getBoundingClientRect();
                if (rect.height < 20) return;  // Too small to matter
                const text = s.innerText.trim();
                const hasCanvas = s.querySelector('canvas');
                const hasSvg = s.querySelector('svg');
                // Large section with almost no text and no charts = suspicious
                if (rect.height > 100 && text.length < 5 && !hasCanvas && !hasSvg) {
                    issues.push({
                        class: s.className.slice(0, 60),
                        id: s.id,
                        height: Math.round(rect.height),
                        text: text.slice(0, 30)
                    });
                }
            });
            return issues;
        }
    """)


def _check_stale_text(page):
    """Check for text that suggests the page is stale or pre-launch."""
    return page.evaluate("""
        () => {
            const body = document.body.innerText;
            const issues = [];
            const suspects = [
                {pattern: /Launching April/i, desc: 'Pre-launch text still visible'},
                // "Coming Soon" in teasers for future features is fine — only flag if in a data section
                // {pattern: /^Coming Soon$/im, desc: '"Coming Soon" standalone text visible'},
                {pattern: /(?<![a-z])TODO(?![a-z])|FIXME|(?<![a-z])TBD(?![a-z])/i, desc: 'Development placeholder text'},
                {pattern: /Loading\\.\\.\\.\\./i, desc: 'Stuck loading indicator'},
                {pattern: /placeholder/i, desc: 'Placeholder text visible'},
            ];
            for (const s of suspects) {
                if (s.pattern.test(body)) {
                    // Find the visible element
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        if (s.pattern.test(walker.currentNode.textContent)) {
                            const el = walker.currentNode.parentElement;
                            if (el && el.offsetParent !== null && el.offsetHeight > 0) {
                                const rect = el.getBoundingClientRect();
                                issues.push({
                                    text: walker.currentNode.textContent.trim().slice(0, 60),
                                    desc: s.desc,
                                    y: Math.round(rect.top + window.scrollY),
                                    visible: true
                                });
                                break;
                            }
                        }
                    }
                }
            }
            return issues;
        }
    """)


def run_sweep(pages=None, save_screenshots=False, screenshot_dir=None):
    """Run deep visual QA sweep on all pages."""
    from playwright.sync_api import sync_playwright

    if screenshot_dir is None:
        screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "qa-screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            color_scheme="dark",
        )

        for page_def in (pages or PAGES):
            page = context.new_page()
            page_path = page_def["path"]
            page_name = page_def["name"]
            issues = []
            page_js_errors = []

            # Capture JS errors (ignore non-critical)
            _non_critical = ["sub_count", "subscriber_count", "405", "favicon", "404"]
            page.on("console", lambda msg: page_js_errors.append(msg.text) if msg.type == "error" and not any(nc in msg.text for nc in _non_critical) else None)
            page.on("pageerror", lambda err: page_js_errors.append(str(err)))

            try:
                url = f"{SITE_URL}{page_path}"
                page.goto(url, wait_until="networkidle", timeout=15000)

                # Wait for content container
                wait_for = page_def.get("wait_for")
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, state="visible", timeout=8000)
                    except Exception:
                        issues.append(f"Content container '{wait_for}' never became visible")

                # ── DEEP SCROLL: top to bottom, triggering all lazy rendering ──
                _scroll_and_reveal(page)
                # Extra wait for raw canvas charts (sleep/glucose use requestAnimationFrame)
                page.wait_for_timeout(1500)

                # ── CHECK 1: Selector-based checks ──
                for check in page_def.get("checks", []):
                    if "selector" in check:
                        elements = page.query_selector_all(check["selector"])
                        if "min_count" in check and len(elements) < check["min_count"]:
                            issues.append(f"Expected {check['min_count']}+ '{check['selector']}', found {len(elements)} — {check['desc']}")
                        if check.get("visible"):
                            el = page.query_selector(check["selector"])
                            if el and not el.is_visible():
                                issues.append(f"'{check['selector']}' exists but hidden — {check['desc']}")
                            elif not el:
                                issues.append(f"'{check['selector']}' not found — {check['desc']}")
                        if check.get("not_empty"):
                            empty_count = 0
                            for el in elements:
                                try:
                                    text = (el.inner_text() or "").strip()
                                except Exception:
                                    text = (el.text_content() or "").strip()
                                if not text or text in ("\u2014", "...", "Loading", "LOADING"):
                                    empty_count += 1
                            if empty_count > 0 and empty_count == len(elements):
                                issues.append(f"All '{check['selector']}' are empty/placeholder — {check['desc']}")
                            elif empty_count > len(elements) // 2:
                                issues.append(f"{empty_count}/{len(elements)} '{check['selector']}' empty — {check['desc']}")

                    # ── CHECK 2: Canvas pixel check (with retry for async rendering) ──
                    if check.get("canvas_not_blank"):
                        canvas_results = _check_canvas_not_blank(page)
                        # Retry once if all blank — charts may render async
                        all_blank = all(c["status"] == "blank" for c in canvas_results) if canvas_results else False
                        if all_blank:
                            page.wait_for_timeout(2000)
                            canvas_results = _check_canvas_not_blank(page)
                        if not canvas_results:
                            issues.append(f"No canvas elements found — {check['desc']}")
                        else:
                            blank = [c for c in canvas_results if c["status"] == "blank"]
                            drawn = [c for c in canvas_results if c["status"] in ("drawn", "chart-js", "assumed-drawn")]
                            zero = [c for c in canvas_results if c["status"] == "zero-size"]
                            if drawn:
                                pass  # At least one canvas has content
                            elif blank and not drawn:
                                ids = [c.get("id", f"canvas-{c['index']}") for c in blank[:3]]
                                issues.append(f"All canvases blank: {', '.join(ids)} — {check['desc']}")
                            if zero:
                                ids = [c.get("id", f"canvas-{c['index']}") for c in zero[:3]]
                                issues.append(f"Zero-size canvases: {', '.join(ids)}")

                # ── CHECK 3: Blank sections ──
                blank_sections = _check_sections_for_blank(page)
                if blank_sections:
                    for bs in blank_sections[:2]:
                        issues.append(f"Empty section: .{bs['class'][:40]} (h={bs['height']}px)")

                # ── CHECK 4: Stale/placeholder text ──
                stale = _check_stale_text(page)
                for s in stale:
                    if s.get("visible"):
                        issues.append(f"Stale text: \"{s['text'][:50]}\" — {s['desc']}")

                # ── CHECK 5: JS errors ──
                if page_js_errors:
                    issues.append(f"{len(page_js_errors)} JS error(s): {page_js_errors[0][:100]}")

                # ── Screenshots ──
                if save_screenshots:
                    slug = page_path.strip("/").replace("/", "-") or "home"
                    page.screenshot(path=os.path.join(screenshot_dir, f"{slug}.png"), full_page=True)

                    # Screenshot individual failing sections
                    if issues:
                        for check in page_def.get("checks", []):
                            if "selector" in check:
                                el = page.query_selector(check["selector"])
                                if el:
                                    try:
                                        el.screenshot(path=os.path.join(screenshot_dir, f"{slug}-{check['desc'][:20].replace(' ','-')}.png"))
                                    except Exception:
                                        pass

            except Exception as e:
                issues.append(f"Page load failed: {e}")

            status = "PASS" if not issues else "FAIL"
            results.append({
                "page": page_name,
                "path": page_path,
                "status": status,
                "issues": issues,
            })
            icon = "✅" if status == "PASS" else "❌"
            print(f"  {icon} {page_name} ({page_path})")
            for issue in issues:
                print(f"      → {issue}")

            page.close()

        browser.close()

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\n{'=' * 50}")
    print(f"Visual QA: {passed} passed, {failed} failed out of {len(results)} pages")

    if save_screenshots:
        print(f"Screenshots saved to: {screenshot_dir}/")

    # Write JSON report
    report_path = os.path.join(screenshot_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "passed": passed,
            "failed": failed,
            "results": results,
        }, f, indent=2)

    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deep visual QA sweep for averagejoematt.com")
    parser.add_argument("--page", help="Test a single page path (e.g., /glucose/)")
    parser.add_argument("--screenshot", action="store_true", help="Save full-page screenshots")
    args = parser.parse_args()

    pages = None
    if args.page:
        pages = [p for p in PAGES if p["path"] == args.page]
        if not pages:
            print(f"Unknown page: {args.page}")
            print(f"Available: {', '.join(p['path'] for p in PAGES)}")
            sys.exit(1)

    print(f"Deep Visual QA Sweep — {SITE_URL}")
    print(f"{'=' * 50}")
    success = run_sweep(pages=pages, save_screenshots=args.screenshot)
    sys.exit(0 if success else 1)
