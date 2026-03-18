#!/usr/bin/env python3
"""
inline_site_data.py — Bake live data into HTML before S3 upload.

Reads public_stats.json (from S3 or local fallback) and inlines current values
into the HTML so that first-paint never shows "—" dashes. JS still hydrates for
real-time freshness, but the server-rendered values are the fallback.

Usage:
  python3 deploy/inline_site_data.py                    # default: reads from S3
  python3 deploy/inline_site_data.py --local             # reads site/data/public_stats.json
  python3 deploy/inline_site_data.py --dry-run           # print changes without writing

Run BEFORE `aws s3 sync` in the deploy pipeline.
"""

import json
import os
import re
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
LOCAL_STATS = SITE_DIR / "data" / "public_stats.json"
S3_BUCKET = "matthew-life-platform"
S3_KEY = "site/data/public_stats.json"

# ── Helpers ──────────────────────────────────────────────────────────────

def load_stats(use_local: bool) -> dict:
    """Load public_stats.json from S3 or local fallback."""
    if use_local:
        print(f"  Reading local: {LOCAL_STATS}")
        return json.loads(LOCAL_STATS.read_text())

    print(f"  Fetching s3://{S3_BUCKET}/{S3_KEY}")
    result = subprocess.run(
        ["aws", "s3", "cp", f"s3://{S3_BUCKET}/{S3_KEY}", "-", "--region", "us-west-2"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ⚠ S3 fetch failed, falling back to local: {result.stderr.strip()}")
        return json.loads(LOCAL_STATS.read_text())
    return json.loads(result.stdout)


def inline_ticker(html: str, stats: dict) -> str:
    """Replace ticker placeholder dashes with real values."""
    v = stats.get("vitals", {})
    j = stats.get("journey", {})
    p = stats.get("platform", {})

    weight_str = f'{v["weight_lbs"]:.1f} LBS' if v.get("weight_lbs") else "—"
    hrv_str = f'{round(v["hrv_ms"])} MS' if v.get("hrv_ms") else "—"
    recovery_str = f'{round(v["recovery_pct"])}%' if v.get("recovery_pct") else "—"
    streak = p.get("tier0_streak")
    streak_str = f'{streak}D STREAK' if streak is not None else "—"
    journey_str = f'{j["progress_pct"]:.1f}% TO GOAL' if j.get("progress_pct") is not None else "—"

    # Replace each ticker ID pair (primary + duplicate)
    replacements = {
        "tk-weight": weight_str,
        "tk-hrv": hrv_str,
        "tk-recovery": recovery_str,
        "tk-streak": streak_str,
        "tk-journey": journey_str,
        "tk-weight-2": weight_str,
        "tk-hrv-2": hrv_str,
        "tk-recovery-2": recovery_str,
        "tk-streak-2": streak_str,
        "tk-journey-2": journey_str,
    }

    for elem_id, value in replacements.items():
        # Match: id="tk-weight">—</strong> or id="tk-weight"><span...>...</span></strong>
        # Replace the inner content between > and </strong>
        pattern = rf'(id="{re.escape(elem_id)}">).*?(</strong>)'
        replacement = rf'\g<1>{value}\g<2>'
        html = re.sub(pattern, replacement, html, count=1, flags=re.DOTALL)

    return html


def inline_hero(html: str, stats: dict) -> str:
    """Replace BS-02 hero skeleton/dashes with real values."""
    v = stats.get("vitals", {})
    j = stats.get("journey", {})
    p = stats.get("platform", {})
    hero = stats.get("hero", {})

    # Hero weight: replace skeleton span with actual number
    cw = hero.get("current_weight_lbs") or j.get("current_weight_lbs") or v.get("weight_lbs")
    if cw:
        weight_val = str(round(cw * 10) / 10)
        # Replace the skeleton span inside hero-weight
        html = re.sub(
            r'(id="hero-weight">)\s*<span class="skeleton"[^>]*>[^<]*</span>\s*(</span>)',
            rf'\g<1>{weight_val}\g<2>',
            html, count=1, flags=re.DOTALL
        )

    # Progress bar: set initial width via inline style
    pct = hero.get("progress_pct") or j.get("progress_pct") or 0
    lost = hero.get("lost_lbs") or j.get("lost_lbs") or 0
    html = re.sub(
        r'(id="hero-progress-fill")([^>]*)(></div>)',
        rf'\g<1>\g<2> style="width:{min(pct, 100):.1f}%"\g<3>',
        html, count=1
    )

    # Lost lbs text
    if lost:
        html = re.sub(
            r'(id="hero-lost-lbs">)[^<]*(</span>)',
            rf'\g<1>{round(lost * 10) / 10} lbs lost\g<2>',
            html, count=1
        )

    # Progress percentage text
    if pct:
        html = re.sub(
            r'(id="hero-progress-pct">)[^<]*(</span>)',
            rf'\g<1>{round(pct * 10) / 10}%\g<2>',
            html, count=1
        )

    # Days on journey
    days = hero.get("days_on_journey")
    if days is not None:
        html = re.sub(
            r'(id="hero-days">)[^<]*(</span>)',
            rf'\g<1>{days}\g<2>',
            html, count=1
        )

    # Streak
    streak = p.get("tier0_streak")
    if streak is not None:
        html = re.sub(
            r'(id="hero-streak">)[^<]*(</span>)',
            rf'\g<1>Day {streak}\g<2>',
            html, count=1
        )

    return html


def inline_nav_date(html: str, stats: dict) -> str:
    """Replace nav 'Live' text with the data generation date."""
    meta = stats.get("_meta", {})
    gen_at = meta.get("generated_at")
    if gen_at:
        try:
            d = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
            date_str = d.strftime("%b %-d")
            html = re.sub(
                r'(id="nav-date">)[^<]*(</span>)',
                rf'\g<1>{date_str}\g<2>',
                html, count=1
            )
        except (ValueError, OSError):
            pass  # macOS %-d may fail; skip silently
    return html


def inline_og_stats(html: str, stats: dict) -> str:
    """Update OG description with current numbers."""
    v = stats.get("vitals", {})
    j = stats.get("journey", {})
    p = stats.get("platform", {})

    tools = p.get("mcp_tools", 95)
    sources = p.get("data_sources", 19)
    weight = v.get("weight_lbs")

    if weight:
        new_desc = f"302 → {weight:.0f} lbs. {sources} data sources. {tools} intelligence tools. Every number public."
        html = re.sub(
            r'(<meta property="og:description" content=")[^"]*(")',
            rf'\g<1>{new_desc}\g<2>',
            html, count=1
        )

    return html


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    use_local = "--local" in sys.argv

    print("── inline_site_data.py ──")
    stats = load_stats(use_local)

    v = stats.get("vitals", {})
    j = stats.get("journey", {})
    print(f"  Weight: {v.get('weight_lbs')}  HRV: {v.get('hrv_ms')}  Progress: {j.get('progress_pct')}%")

    # Only inline the homepage — it has all the dynamic elements
    homepage = SITE_DIR / "index.html"
    if not homepage.exists():
        print(f"  ✗ {homepage} not found")
        sys.exit(1)

    html = homepage.read_text()
    original = html

    html = inline_ticker(html, stats)
    html = inline_hero(html, stats)
    html = inline_nav_date(html, stats)
    html = inline_og_stats(html, stats)

    if html == original:
        print("  No changes needed — data already inlined or no placeholders found.")
        return

    changes = sum(1 for a, b in zip(html, original) if a != b)
    print(f"  {changes} characters changed in index.html")

    if dry_run:
        print("  [DRY RUN] — no files written.")
        return

    homepage.write_text(html)
    print(f"  ✓ {homepage} updated with live data")


if __name__ == "__main__":
    main()
