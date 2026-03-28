#!/usr/bin/env python3
"""
playwright_qa.py — Visual + behavioural QA for averagejoematt.com

Runs a real Chromium browser against the live site (or a local server).
Catches rendering bugs, JS errors, layout breaks, and overlay issues that
curl/grep cannot detect. Takes full-page screenshots and compares them
against stored baselines for visual regression detection.

Usage:
    # Against the live site (normal use):
    python3 deploy/playwright_qa.py

    # Update baselines (run after intentional visual changes):
    python3 deploy/playwright_qa.py --update-baselines

    # Against a local server (pre-deploy):
    python3 deploy/playwright_qa.py --base-url http://localhost:8000

    # Quick mode — skip visual diff, just check structure:
    python3 deploy/playwright_qa.py --quick

    # Specific pages only:
    python3 deploy/playwright_qa.py --pages story,habits,homepage

    # Mobile viewport:
    python3 deploy/playwright_qa.py --mobile

    # Exit code: 0 = pass, 1 = failures found
    python3 deploy/playwright_qa.py --fail-on-error

Report saved to: deploy/qa_report/
Screenshots:    deploy/qa_report/screenshots/
Baselines:      deploy/qa_baselines/
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Page, Browser
except ImportError:
    print("ERROR: playwright not installed.")
    print("Run: pip install playwright && python3 -m playwright install chromium")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────────────────

REPORT_DIR = Path(__file__).parent / "qa_report"
SCREENSHOT_DIR = REPORT_DIR / "screenshots"
BASELINE_DIR = Path(__file__).parent / "qa_baselines"

PAGES = {
    # slug: (path, page_title_contains, critical_element_selector)
    "homepage":       ("/",                  "Matthew Walker",          ".nav"),
    "story":          ("/story/",            "The Story",               ".story-header"),
    "live":           ("/live/",             "Timeline",                ".nav"),
    "journal":        ("/journal/",          "Journal",                 ".nav"),
    "journal-archive":("/journal/archive/",  "Archive",                 ".nav"),
    "week":           ("/week/",             "Week",                    ".nav"),
    "about":          ("/about/",            "About",                   ".nav"),
    "platform":       ("/platform/",         "Platform",                ".nav"),
    "character":      ("/character/",        "Character",               ".nav"),
    "habits":         ("/habits/",           "Habit",                   ".nav"),
    "achievements":   ("/achievements/",     "Achievements",            ".nav"),
    "discoveries":    ("/discoveries/",      "Discoveries",             ".nav"),
    "results":        ("/results/",          "Results",                 ".nav"),
    "explorer":       ("/explorer/",         "Explorer",                ".nav"),
    "experiments":    ("/experiments/",      "Experiments",             ".nav"),
    "protocols":      ("/protocols/",        "Protocols",               ".nav"),
    "intelligence":   ("/intelligence/",     "Intelligence",            ".nav"),
    "accountability": ("/accountability/",   "Accountability",          ".nav"),
    "methodology":    ("/methodology/",      "Methodology",             ".nav"),
    "progress":       ("/progress/",         "Progress",                ".nav"),
    "benchmarks":     ("/benchmarks/",       "Benchmarks",              ".nav"),
    "supplements":    ("/supplements/",      "Supplements",             ".nav"),
    "cost":           ("/cost/",             "$13",                     ".nav"),
    "tools":          ("/tools/",            "Tools",                   ".nav"),
    "ask":            ("/ask/",              "Ask",                     ".nav"),
    "board":          ("/board/",            "Board",                   ".nav"),
    "data":           ("/data/",             "Data",                    ".nav"),
    "start":          ("/start/",            "Start",                   ".nav"),
    "subscribe":      ("/subscribe/",        "Subscribe",               ".nav"),
    "privacy":        ("/privacy/",          "Privacy",                 ".nav"),
}

ERRORS = []
WARNINGS = []
PASSES = []


def error(page_slug: str, msg: str, screenshot_path: str = None):
    entry = {"page": page_slug, "msg": msg}
    if screenshot_path:
        entry["screenshot"] = screenshot_path
    ERRORS.append(entry)
    print(f"  ❌ [{page_slug}] {msg}")


def warn(page_slug: str, msg: str):
    WARNINGS.append({"page": page_slug, "msg": msg})
    print(f"  ⚠️  [{page_slug}] {msg}")


def ok(page_slug: str, msg: str):
    PASSES.append({"page": page_slug, "msg": msg})
    print(f"  ✅ [{page_slug}] {msg}")


# ── Per-page checks ────────────────────────────────────────────────────────────

def check_page(page: Page, slug: str, path: str, base_url: str,
               title_contains: str, critical_selector: str,
               console_errors: list, update_baselines: bool, quick: bool):
    url = base_url.rstrip("/") + path
    screenshot_path = str(SCREENSHOT_DIR / f"{slug}.png")
    baseline_path = str(BASELINE_DIR / f"{slug}.png")

    # Navigate
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        error(slug, f"Page failed to load: {e}")
        return

    # HTTP status
    if response and response.status != 200:
        error(slug, f"HTTP {response.status}")
        return
    ok(slug, f"HTTP 200")

    # Wait for fonts + basic render + nav.js injection (not full network idle — too slow for 30 pages)
    page.wait_for_timeout(1200)

    # ── Title ──────────────────────────────────────────────────────────────────
    title = page.title()
    if not title:
        error(slug, "Empty <title>")
    elif title_contains.lower() not in title.lower():
        warn(slug, f"<title> doesn't contain '{title_contains}': got '{title}'")
    else:
        ok(slug, f"<title> correct: '{title}'")

    # ── Nav bar visible and not cropped ────────────────────────────────────────
    nav = page.locator(".nav").first
    if nav.count() == 0:
        error(slug, ".nav element missing — nav bar broken")
    else:
        nav_box = nav.bounding_box()
        if nav_box and nav_box["y"] > 10:
            warn(slug, f"Nav bar not at top of page (y={nav_box['y']:.0f}px)")
        elif nav_box:
            ok(slug, "Nav bar at top of page")

    # ── CRITICAL: nav-overlay must NOT be visible on page load ─────────────────
    overlay = page.locator(".nav-overlay").first
    if overlay.count() == 0:
        error(slug, "nav-overlay element missing — hamburger menu broken")
    else:
        # Check computed opacity
        opacity = page.evaluate("""
            () => {
                const el = document.querySelector('.nav-overlay');
                if (!el) return null;
                return window.getComputedStyle(el).opacity;
            }
        """)
        if opacity is None:
            error(slug, "nav-overlay not found in DOM")
        elif float(opacity) > 0.01:
            error(slug, f"nav-overlay is VISIBLE on load (opacity={opacity}) — this is the bug from the screenshot!")
        else:
            ok(slug, f"nav-overlay hidden on load (opacity={opacity})")

        # Check position is fixed
        position = page.evaluate("""
            () => {
                const el = document.querySelector('.nav-overlay');
                return el ? window.getComputedStyle(el).position : null;
            }
        """)
        if position != "fixed":
            error(slug, f"nav-overlay position is '{position}' not 'fixed' — will render in document flow!")
        else:
            ok(slug, "nav-overlay position:fixed")

    # ── Footer: present AND styled (grid applied) ──────────────────────────────
    # Checks both existence and that CSS is actually rendering the grid layout.
    # Presence-only check missed this bug: footer HTML exists but styles not applied.
    footer = page.locator(".footer-v2").first
    if footer.count() == 0:
        error(slug, "footer-v2 missing — footer broken")
    else:
        # Check that the grid container has display:grid (not unstyled block/inline)
        grid_display = page.evaluate("""
            () => {
                const grid = document.querySelector('.footer-v2__grid');
                if (!grid) return null;
                return window.getComputedStyle(grid).display;
            }
        """)
        if grid_display is None:
            error(slug, "footer-v2__grid element missing — footer HTML incomplete")
        elif grid_display != "grid":
            error(slug, f"footer-v2__grid has display:'{grid_display}' not 'grid' — footer CSS not rendering! (base.css may not have loaded)")
        else:
            ok(slug, f"footer-v2 styled correctly (display:{grid_display})")

        # Check that footer columns are flex columns (not unstyled inline)
        col_direction = page.evaluate("""
            () => {
                const col = document.querySelector('.footer-v2__col');
                if (!col) return null;
                return window.getComputedStyle(col).flexDirection;
            }
        """)
        if col_direction != "column":
            error(slug, f"footer-v2__col flex-direction:'{col_direction}' not 'column' — footer column layout broken")
        else:
            ok(slug, "footer-v2__col layout correct")

        # Check challenge-bar is fixed position (not rendered in document flow)
        cb_position = page.evaluate("""
            () => {
                const el = document.querySelector('.challenge-bar');
                if (!el) return 'absent';
                return window.getComputedStyle(el).position;
            }
        """)
        if cb_position == "absent":
            pass  # challenge-bar is page-specific, not on all pages
        elif cb_position != "fixed":
            error(slug, f"challenge-bar position:'{cb_position}' not 'fixed' — will render in document flow above footer")

    # ── No horizontal scrollbar (layout overflow) ───────────────────────────────
    overflow = page.evaluate("""
        () => document.documentElement.scrollWidth > window.innerWidth
    """)
    if overflow:
        warn(slug, "Horizontal overflow detected — content wider than viewport")
    else:
        ok(slug, "No horizontal overflow")

    # ── JS console errors ──────────────────────────────────────────────────────
    page_errors = [e for e in console_errors if "page" not in e.get("skip_for", "")]
    if page_errors:
        for ce in page_errors[-3:]:  # show max 3
            warn(slug, f"Console error: {ce['text'][:120]}")
    else:
        ok(slug, "No console errors")

    # ── Critical element present ───────────────────────────────────────────────
    if critical_selector and critical_selector != ".nav":
        el = page.locator(critical_selector).first
        if el.count() == 0:
            warn(slug, f"Critical element missing: {critical_selector}")
        else:
            ok(slug, f"Critical element present: {critical_selector}")

    # ── Page-specific checks ───────────────────────────────────────────────────
    _page_specific_checks(page, slug)

    # ── Screenshot + visual diff ───────────────────────────────────────────────
    page.screenshot(path=screenshot_path, full_page=True)

    if not quick:
        _visual_diff(slug, screenshot_path, baseline_path, update_baselines)


def _page_specific_checks(page: Page, slug: str):
    """Targeted checks for high-value pages."""

    if slug == "homepage":
        # /start/ must be linked
        start_links = page.locator('a[href="/start/"]').count()
        if start_links == 0:
            error(slug, "/start/ not linked from homepage")
        else:
            ok(slug, f"/start/ linked ({start_links} times)")

        # Accountability quote
        quote_text = page.locator("text=accountability without witnesses").count()
        if quote_text == 0:
            warn(slug, "Accountability quote not found on homepage")
        else:
            ok(slug, "Accountability quote present")

        # No competing CTAs (should not have BOTH an inline email form AND Subscribe nav link)
        email_inputs = page.locator('input[type="email"]').count()
        if email_inputs > 0:
            warn(slug, f"Found {email_inputs} email input(s) on homepage — CTA consolidated?")

    elif slug == "story":
        # "302 pounds" headline
        if page.locator("text=302").count() == 0:
            warn(slug, "302 lbs headline not found")
        else:
            ok(slug, "302 lbs headline present")

    elif slug == "subscribe":
        # Subscribe form or link must exist
        has_form = page.locator("form").count() > 0
        has_email = page.locator('input[type="email"]').count() > 0
        if not has_form and not has_email:
            error(slug, "Subscribe page has no form or email input")
        else:
            ok(slug, "Subscribe form present")

    elif slug == "week":
        # Share button
        share = page.locator("text=Share this week").count()
        if share == 0:
            warn(slug, "Share button not found on /week/")
        else:
            ok(slug, "Share button present")

    elif slug == "habits":
        # Heatmap scroll hint on mobile not checked here (desktop test)
        ok(slug, "habits page loaded")

    elif slug == "start":
        # Should link to Sprint 9 pages
        for page_slug in ["/habits/", "/achievements/", "/accountability/", "/methodology/"]:
            if page.locator(f'a[href="{page_slug}"]').count() == 0:
                warn(slug, f"/start/ missing link to {page_slug}")
        ok(slug, "/start/ link grid checked")

    elif slug == "benchmarks":
        # Calculator should be near the top
        calc = page.locator("#calculator, .calculator, [id*='calc']").first
        if calc.count() > 0:
            calc_box = calc.bounding_box()
            if calc_box and calc_box["y"] > 1200:
                warn(slug, f"Calculator is below fold (y={calc_box['y']:.0f}px — needs to be higher)")
            elif calc_box:
                ok(slug, f"Calculator position: y={calc_box['y']:.0f}px")


def _visual_diff(slug: str, screenshot_path: str, baseline_path: str, update_baselines: bool):
    """Compare screenshot against baseline using pixel diff."""
    try:
        from PIL import Image, ImageChops
        import math
    except ImportError:
        # PIL not available — skip visual diff
        return

    if update_baselines or not Path(baseline_path).exists():
        import shutil
        shutil.copy2(screenshot_path, baseline_path)
        ok(slug, f"Baseline {'updated' if update_baselines else 'created'}")
        return

    # Compare
    try:
        current = Image.open(screenshot_path).convert("RGB")
        baseline = Image.open(baseline_path).convert("RGB")

        # Resize to same dimensions if needed (page content changes height)
        if current.size != baseline.size:
            # Resize current to baseline height for comparison (top portion only)
            min_height = min(current.size[1], baseline.size[1])
            current_crop = current.crop((0, 0, current.size[0], min_height))
            baseline_crop = baseline.crop((0, 0, baseline.size[0], min_height))
        else:
            current_crop, baseline_crop = current, baseline

        diff = ImageChops.difference(current_crop, baseline_crop)
        pixels = list(diff.getdata())
        total_pixels = len(pixels)
        changed_pixels = sum(1 for p in pixels if max(p) > 10)  # threshold: 10/255
        pct = changed_pixels / total_pixels * 100

        if pct > 5.0:  # >5% changed = visual regression
            error(slug, f"Visual regression: {pct:.1f}% of pixels changed vs baseline")
            # Save diff image
            diff_path = str(SCREENSHOT_DIR / f"{slug}_diff.png")
            diff.save(diff_path)
        elif pct > 1.0:
            warn(slug, f"Minor visual change: {pct:.1f}% pixels changed")
        else:
            ok(slug, f"Visual match ({pct:.1f}% pixel delta)")
    except Exception as e:
        warn(slug, f"Visual diff failed: {e}")


def check_hamburger_behavior(page: Page, base_url: str):
    """Click the hamburger, verify overlay opens and closes."""
    slug = "overlay-behavior"
    url = base_url.rstrip("/") + "/story/"

    # Must use mobile viewport to test hamburger (hidden on desktop)
    context = page.context.browser.new_context(viewport={"width": 390, "height": 844})
    mobile_page = context.new_page()
    mobile_page.goto(url, wait_until="domcontentloaded", timeout=15000)
    mobile_page.wait_for_timeout(500)

    hamburger = mobile_page.locator(".nav__hamburger").first
    if hamburger.count() == 0 or not hamburger.is_visible():
        warn(slug, "Hamburger not visible at 390px — check CSS media query")
        context.close()
        return

    # Click open
    hamburger.click()
    mobile_page.wait_for_timeout(400)

    opacity_after_open = mobile_page.evaluate(
        "() => window.getComputedStyle(document.querySelector('.nav-overlay')).opacity"
    )
    if float(opacity_after_open) < 0.9:
        error(slug, f"Overlay didn't open after hamburger click (opacity={opacity_after_open})")
    else:
        ok(slug, f"Overlay opens on hamburger click (opacity={opacity_after_open})")

    # Click close
    close_btn = mobile_page.locator(".nav-overlay__close").first
    if close_btn.count() > 0:
        close_btn.click()
        mobile_page.wait_for_timeout(400)
        opacity_after_close = mobile_page.evaluate(
            "() => window.getComputedStyle(document.querySelector('.nav-overlay')).opacity"
        )
        if float(opacity_after_close) > 0.01:
            error(slug, f"Overlay didn't close after close button (opacity={opacity_after_close})")
        else:
            ok(slug, "Overlay closes correctly")

    context.close()


def check_back_to_top(page: Page, base_url: str):
    """Scroll down, verify back-to-top appears."""
    slug = "back-to-top"
    url = base_url.rstrip("/") + "/platform/"
    # Use a fresh context so we have a live page
    context = page.context.browser.new_context(viewport={"width": 1280, "height": 900})
    p = context.new_page()
    p.goto(url, wait_until="domcontentloaded", timeout=15000)
    p.wait_for_timeout(500)
    page = p  # shadow the parameter for the rest of the function

    # Check initial state — should be invisible
    btt = page.locator(".back-to-top").first
    if btt.count() == 0:
        warn(slug, "back-to-top button not in DOM (nav.js loaded?)")
        return

    initial_opacity = page.evaluate(
        "() => { const el = document.querySelector('.back-to-top'); return el ? window.getComputedStyle(el).opacity : null; }"
    )
    if initial_opacity and float(initial_opacity) > 0.01:
        warn(slug, f"back-to-top visible before scroll (opacity={initial_opacity})")

    # Scroll down
    page.evaluate("window.scrollTo(0, 500)")
    page.wait_for_timeout(400)

    after_scroll = page.evaluate(
        "() => { const el = document.querySelector('.back-to-top'); return el ? window.getComputedStyle(el).opacity : null; }"
    )
    if after_scroll and float(after_scroll) > 0.9:
        ok(slug, "back-to-top appears after scrolling")
    else:
        warn(slug, f"back-to-top not visible after scroll (opacity={after_scroll})")

    context.close()


def check_api_responses(page: Page, base_url: str):
    """Check that API endpoints return data and pages parse it correctly."""
    slug = "api"
    import urllib.request

    endpoints = [
        ("/api/vitals",    "weight_lbs"),
        ("/api/journey",   "start_weight"),
        ("/api/character", "level"),
    ]
    for path, expected_key in endpoints:
        url = base_url.rstrip("/") + path
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
            if expected_key in str(data):
                ok(slug, f"{path}: {expected_key} present")
            else:
                warn(slug, f"{path}: {expected_key} not in response")
        except Exception as e:
            error(slug, f"{path}: {e}")


def check_mobile_viewport(browser: Browser, base_url: str, pages_to_check: list):
    """Re-run core checks at mobile viewport (375px)."""
    print("\n── Mobile viewport (375×812) ─────────────────────────────")
    context = browser.new_context(viewport={"width": 375, "height": 812})
    page = context.new_page()
    console_errors = []
    page.on("console", lambda msg: console_errors.append({"text": msg.text}) if msg.type == "error" else None)
    page.on("pageerror", lambda err: console_errors.append({"text": str(err)}))

    for slug in pages_to_check:
        path, title_contains, critical_selector = PAGES[slug]
        url = base_url.rstrip("/") + path
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(600)

        # Hamburger must be visible on mobile
        hamburger = page.locator(".nav__hamburger").first
        if hamburger.count() == 0:
            error(f"{slug}@mobile", "Hamburger button not in DOM")
        else:
            is_visible = hamburger.is_visible()
            if not is_visible:
                error(f"{slug}@mobile", "Hamburger button hidden on mobile (CSS wrong)")
            else:
                ok(f"{slug}@mobile", "Hamburger visible")

        # No horizontal overflow
        overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        if overflow:
            warn(f"{slug}@mobile", "Horizontal overflow on mobile")
        else:
            ok(f"{slug}@mobile", "No horizontal overflow")

        # Screenshot
        mobile_shot = str(SCREENSHOT_DIR / f"{slug}_mobile.png")
        page.screenshot(path=mobile_shot, full_page=True)

        # Hamburger click → overlay opens
        if hamburger.is_visible():
            hamburger.click()
            page.wait_for_timeout(400)
            opacity = page.evaluate(
                "() => window.getComputedStyle(document.querySelector('.nav-overlay')).opacity"
            )
            if float(opacity) > 0.9:
                ok(f"{slug}@mobile", "Overlay opens on mobile")
            else:
                error(f"{slug}@mobile", f"Overlay didn't open on mobile (opacity={opacity})")
            # Close
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

    context.close()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Playwright QA for averagejoematt.com")
    parser.add_argument("--base-url", default="https://averagejoematt.com",
                        help="Base URL (default: https://averagejoematt.com)")
    parser.add_argument("--update-baselines", action="store_true",
                        help="Update baseline screenshots (run after intentional changes)")
    parser.add_argument("--quick", action="store_true",
                        help="Skip visual diff — structure checks only")
    parser.add_argument("--pages", default="",
                        help="Comma-separated page slugs to test (default: all)")
    parser.add_argument("--mobile", action="store_true",
                        help="Also run mobile viewport tests")
    parser.add_argument("--fail-on-error", action="store_true",
                        help="Exit 1 if any errors found")
    parser.add_argument("--headless", default=True, action=argparse.BooleanOptionalAction,
                        help="Run headless (default: True)")
    args = parser.parse_args()

    # Setup dirs
    REPORT_DIR.mkdir(exist_ok=True)
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    BASELINE_DIR.mkdir(exist_ok=True)

    # Filter pages
    if args.pages:
        slugs = [s.strip() for s in args.pages.split(",")]
        pages_to_run = {k: v for k, v in PAGES.items() if k in slugs}
        if not pages_to_run:
            print(f"No matching pages for: {args.pages}")
            print(f"Available: {', '.join(PAGES.keys())}")
            sys.exit(1)
    else:
        pages_to_run = PAGES

    start_time = time.time()

    print("=" * 60)
    print(f"averagejoematt.com — Playwright QA")
    print(f"Target: {args.base_url}")
    print(f"Pages:  {len(pages_to_run)}")
    print(f"Mode:   {'quick' if args.quick else 'full'}{', mobile' if args.mobile else ''}")
    print(f"Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)

        # Desktop context
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Collect console errors per page
        current_console_errors = []
        page.on("console", lambda msg: current_console_errors.append({"text": msg.text}) if msg.type == "error" else None)
        page.on("pageerror", lambda err: current_console_errors.append({"text": str(err)}))

        # ── Check each page ────────────────────────────────────────────────────
        print(f"\n── Desktop (1280×900) — {len(pages_to_run)} pages ─────────────────")
        for slug, (path, title_contains, critical_selector) in pages_to_run.items():
            print(f"\n  [{slug}] {args.base_url}{path}")
            current_console_errors.clear()
            check_page(
                page=page,
                slug=slug,
                path=path,
                base_url=args.base_url,
                title_contains=title_contains,
                critical_selector=critical_selector,
                console_errors=current_console_errors,
                update_baselines=args.update_baselines,
                quick=args.quick,
            )

        # ── Behavioural tests ──────────────────────────────────────────────────
        print(f"\n── Behavioural tests ──────────────────────────────────────")
        check_hamburger_behavior(page, args.base_url)
        check_back_to_top(page, args.base_url)

        context.close()

        # ── API checks ─────────────────────────────────────────────────────────
        if "averagejoematt.com" in args.base_url:
            print(f"\n── API endpoints ──────────────────────────────────────────")
            check_api_responses(page, args.base_url)

        # ── Mobile ─────────────────────────────────────────────────────────────
        if args.mobile:
            mobile_pages = list(pages_to_run.keys())[:5]  # Check first 5 pages on mobile
            check_mobile_viewport(browser, args.base_url, mobile_pages)

        browser.close()

    elapsed = time.time() - start_time

    # ── Report ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"QA REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({elapsed:.0f}s)")
    print("=" * 60)
    print(f"  Passed:   {len(PASSES)}")
    print(f"  Warnings: {len(WARNINGS)}")
    print(f"  Errors:   {len(ERRORS)}")

    if ERRORS:
        print(f"\n❌ ERRORS ({len(ERRORS)}) — must fix:")
        for e in ERRORS:
            print(f"  [{e['page']}] {e['msg']}")
            if e.get('screenshot'):
                print(f"    Screenshot: {e['screenshot']}")

    if WARNINGS:
        print(f"\n⚠️  WARNINGS ({len(WARNINGS)}):")
        for w in WARNINGS:
            print(f"  [{w['page']}] {w['msg']}")

    print(f"\nScreenshots: {SCREENSHOT_DIR}/")
    print(f"Baselines:   {BASELINE_DIR}/")

    # Save JSON report
    report = {
        "timestamp": datetime.now().isoformat(),
        "base_url": args.base_url,
        "elapsed_seconds": round(elapsed, 1),
        "passes": len(PASSES),
        "warnings": len(WARNINGS),
        "errors": len(ERRORS),
        "error_details": ERRORS,
        "warning_details": WARNINGS,
    }
    report_path = REPORT_DIR / "latest.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"JSON report: {report_path}")
    print("=" * 60)

    if not ERRORS:
        print("✅ All checks passed.")
    else:
        print(f"❌ {len(ERRORS)} error(s) found.")

    if args.fail_on_error and ERRORS:
        sys.exit(1)


if __name__ == "__main__":
    main()
