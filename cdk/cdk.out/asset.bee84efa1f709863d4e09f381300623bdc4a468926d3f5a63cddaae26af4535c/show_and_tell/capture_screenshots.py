#!/usr/bin/env python3
"""
show_and_tell/capture_screenshots.py

Automated screenshot capture for the Life Platform Show & Tell PDF.
Uses Playwright to hit the live dashboard and buddy page with demo mode active.

Prerequisites:
  pip3 install playwright pillow
  playwright install chromium

Usage:
  python3 capture_screenshots.py

Outputs to show_and_tell/screenshots/ — raw, unredacted screenshots.
Run redact_screenshots.py after this to produce clean versions in processed/.

For the blog and email screenshots, those require manual capture (email client,
live blog) — this script marks which ones need manual intervention.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
DASHBOARD_URL = "https://dash.averagejoematt.com"
BUDDY_URL     = "https://buddy.averagejoematt.com"

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# Cookie name used for HMAC dashboard auth (set this to your actual cookie value)
# Get it by: open dashboard in Chrome → DevTools → Application → Cookies
DASHBOARD_COOKIE = os.environ.get("DASH_COOKIE", "")

# ── Shot definitions ─────────────────────────────────────────────────────────
# Each entry: (filename, url, selector_to_wait_for, scroll_y, clip_or_fullpage)
AUTOMATED_SHOTS = [
    # Dashboard - main view
    ("shot16_dashboard",       DASHBOARD_URL, "#dashboard-container",    0,    "fullpage"),
    # Dashboard - clinical tab
    ("shot17_clinical",        DASHBOARD_URL + "?tab=clinical", ".clinical-summary", 0, "fullpage"),
    # Dashboard - character sheet section (scroll to bottom)
    ("shot18_dashboard_character", DASHBOARD_URL, "#character-section",  1400, "viewport"),
    # Character radar only
    ("shot21_char_radar",      DASHBOARD_URL, "#radar-chart",             1600, "element:#radar-chart"),
    # Buddy page
    ("shot14_buddy1",          BUDDY_URL,     "#buddy-container",         0,    "viewport"),
    ("shot15_buddy2",          BUDDY_URL,     "#buddy-container",         600,  "viewport"),
    # Buddy character sheet
    ("shot19_buddy_character", BUDDY_URL,     "#character-section",       1000, "viewport"),
]

MANUAL_SHOTS = [
    "shot01_freshness      → Daily Brief email (screenshot from Mail.app)",
    "shot02_daily_brief    → Daily Brief email — full scroll (Mail.app)",
    "shot03_training       → Training section of Daily Brief",
    "shot04_nutrition      → Nutrition section of Daily Brief",
    "shot05_habits         → Habits Deep Dive section",
    "shot06_cgm_board      → CGM + Board of Directors section",
    "shot07_brittany1      → Brittany email (Mail.app)",
    "shot08_brittany2      → Brittany email continued",
    "shot09_alarm          → CloudWatch alarm (AWS Console screenshot)",
    "shot10_plate1         → Weekly Plate email part 1",
    "shot11_plate2         → Weekly Plate email part 2",
    "shot12_grocery        → Grocery list section",
    "shot13_blog           → Elena Voss blog (browser screenshot)",
    "shot20_brief_character → Character section of Daily Brief",
]


async def capture_automated():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: pip3 install playwright && playwright install chromium")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,  # retina-quality
        )

        # Inject auth cookie for dashboard
        if DASHBOARD_COOKIE:
            await context.add_cookies([{
                "name": "auth_token",
                "value": DASHBOARD_COOKIE,
                "domain": "dash.averagejoematt.com",
                "path": "/",
            }])
        else:
            print("⚠  DASH_COOKIE not set — dashboard screenshots will show login page")
            print("   Run: export DASH_COOKIE='your-cookie-value'")

        for name, url, wait_selector, scroll_y, clip_mode in AUTOMATED_SHOTS:
            print(f"  Capturing {name}...", end=" ", flush=True)
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_selector(wait_selector, timeout=10000)

                if scroll_y > 0:
                    await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    await page.wait_for_timeout(500)

                out_path = str(SCREENSHOTS_DIR / f"{name}.png")

                if clip_mode == "fullpage":
                    await page.screenshot(path=out_path, full_page=True)
                elif clip_mode == "viewport":
                    await page.screenshot(path=out_path, full_page=False)
                elif clip_mode.startswith("element:"):
                    selector = clip_mode.replace("element:", "")
                    el = await page.query_selector(selector)
                    if el:
                        await el.screenshot(path=out_path)
                    else:
                        await page.screenshot(path=out_path, full_page=False)

                print("✓")
                await page.close()

            except Exception as e:
                print(f"✗ FAILED: {e}")
                await page.close()

        await browser.close()


def print_manual_checklist():
    print("\n" + "─"*60)
    print("MANUAL SCREENSHOTS NEEDED")
    print("─"*60)
    print("Take these screenshots and save to show_and_tell/screenshots/")
    print("Use CleanShot X with @2x retina, 880px wide window\n")
    for item in MANUAL_SHOTS:
        fname = item.split("→")[0].strip()
        desc  = item.split("→")[1].strip()
        exists = (SCREENSHOTS_DIR / f"{fname}.png").exists()
        status = "✓" if exists else "□"
        print(f"  {status}  {fname}.png")
        print(f"       {desc}")
    print()


def main():
    print(f"\nLife Platform Screenshot Capture")
    print(f"Output: {SCREENSHOTS_DIR}")
    print(f"─"*60)

    print("\nAutomated captures (Playwright):")
    asyncio.run(capture_automated())

    print_manual_checklist()

    # Summary
    total = len(AUTOMATED_SHOTS) + len(MANUAL_SHOTS)
    captured = len(list(SCREENSHOTS_DIR.glob("*.png")))
    print(f"Status: {captured}/{total} screenshots in place")
    print("Next step: python3 redact_screenshots.py")


if __name__ == "__main__":
    main()
