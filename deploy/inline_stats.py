#!/usr/bin/env python3
"""
inline_stats.py — Bake latest public_stats.json values into static HTML at deploy time.

Solves the "dashes problem": visitors, crawlers, and social bots see real numbers
on first paint instead of JS-dependent placeholders.

Usage:
  python3 deploy/inline_stats.py                    # dry-run (preview changes)
  python3 deploy/inline_stats.py --apply            # write changes to site/ files
  python3 deploy/inline_stats.py --apply --from-s3  # pull latest stats from S3 first

The JS data loader still runs on page load and overwrites these values with the
freshest data. This script just ensures the *initial* render is never blank.
"""

import json
import os
import re
import sys
import argparse
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
STATS_FILE = SITE_DIR / "data" / "public_stats.json"

# ── Replacements: (element_id, fallback_text, lambda to compute display value) ──

def build_replacements(stats: dict) -> list[tuple[str, str, str]]:
    """Return list of (element_id, old_pattern, new_value) tuples."""
    v = stats.get("vitals", {})
    j = stats.get("journey", {})
    p = stats.get("platform", {})
    hero = stats.get("hero", {})

    weight = hero.get("current_weight_lbs") or j.get("current_weight_lbs") or v.get("weight_lbs")
    hrv = v.get("hrv_ms")
    recovery = v.get("recovery_pct")
    streak = p.get("tier0_streak")
    progress = hero.get("progress_pct") or j.get("progress_pct")
    lost = hero.get("lost_lbs") or j.get("lost_lbs")
    days = hero.get("days_on_journey")

    replacements = []

    # Ticker items — replace the "—" inside <strong> tags
    if weight:
        w_str = f"{weight:.1f} LBS"
        replacements.append(("tk-weight", w_str))
        replacements.append(("tk-weight-2", w_str))
    if hrv:
        h_str = f"{round(hrv)} MS"
        replacements.append(("tk-hrv", h_str))
        replacements.append(("tk-hrv-2", h_str))
    if recovery:
        r_str = f"{round(recovery)}%"
        replacements.append(("tk-recovery", r_str))
        replacements.append(("tk-recovery-2", r_str))
    if streak is not None:
        s_str = f"{streak}D STREAK"
        replacements.append(("tk-streak", s_str))
        replacements.append(("tk-streak-2", s_str))
    if progress is not None:
        j_str = f"{progress:.1f}% TO GOAL"
        replacements.append(("tk-journey", j_str))
        replacements.append(("tk-journey-2", j_str))

    # Hero section
    if weight:
        replacements.append(("hero-weight", str(round(weight * 10) / 10)))
    if lost is not None:
        replacements.append(("hero-lost-lbs", f"{round(lost * 10) / 10} lbs lost"))
    if progress is not None:
        replacements.append(("hero-progress-pct", f"{round(progress * 10) / 10}%"))
    if days is not None:
        replacements.append(("hero-days", str(days)))
    if streak is not None:
        replacements.append(("hero-streak", f"Day {streak}"))

    return replacements


def inline_into_html(html: str, replacements: list[tuple[str, str]]) -> str:
    """Replace placeholder content inside elements with known IDs."""
    modified = html
    changes = 0

    for elem_id, new_value in replacements:
        # Pattern: id="elem_id">ANYTHING_INSIDE</
        # Handles both <strong id="...">—</strong> and <span id="...">—</span> etc.
        # Also handles skeleton spans inside the element
        pattern = rf'(id="{re.escape(elem_id)}"[^>]*>)(.+?)(</)'
        match = re.search(pattern, modified, re.DOTALL)
        if match:
            old_content = match.group(2).strip()
            if old_content != new_value:
                modified = modified[:match.start(2)] + new_value + modified[match.end(2):]
                changes += 1

    return modified, changes


def pull_from_s3():
    """Download latest public_stats.json from S3."""
    import subprocess
    dest = STATS_FILE
    cmd = [
        "aws", "s3", "cp",
        "s3://matthew-life-platform/site/data/public_stats.json",
        str(dest),
        "--region", "us-west-2",
    ]
    print(f"  ↓ Pulling from S3...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ S3 pull failed: {result.stderr.strip()}")
        sys.exit(1)
    print(f"  ✓ Updated {dest.name}")


def main():
    parser = argparse.ArgumentParser(description="Inline public_stats.json into site HTML")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument("--from-s3", action="store_true", help="Pull latest stats from S3 first")
    args = parser.parse_args()

    if args.from_s3:
        pull_from_s3()

    if not STATS_FILE.exists():
        print(f"✗ Stats file not found: {STATS_FILE}")
        print("  Run with --from-s3 to pull latest, or ensure data/public_stats.json exists.")
        sys.exit(1)

    with open(STATS_FILE) as f:
        stats = json.load(f)

    replacements = build_replacements(stats)
    if not replacements:
        print("✗ No data found in stats file to inline.")
        sys.exit(1)

    print(f"Found {len(replacements)} values to inline:")
    for elem_id, value in replacements:
        print(f"  {elem_id} → {value}")

    # Process all HTML files in site/
    html_files = list(SITE_DIR.rglob("*.html"))
    total_changes = 0

    for html_path in html_files:
        with open(html_path) as f:
            original = f.read()

        modified, changes = inline_into_html(original, replacements)

        if changes > 0:
            rel = html_path.relative_to(SITE_DIR)
            print(f"\n  {rel}: {changes} replacement(s)")
            if args.apply:
                with open(html_path, "w") as f:
                    f.write(modified)
                print(f"    ✓ Written")
            else:
                print(f"    (dry-run — use --apply to write)")
            total_changes += changes

    print(f"\n{'Applied' if args.apply else 'Would apply'} {total_changes} total changes across {len(html_files)} files.")
    if not args.apply and total_changes > 0:
        print("Run with --apply to write changes.")


if __name__ == "__main__":
    main()
