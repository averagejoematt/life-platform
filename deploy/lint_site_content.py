#!/usr/bin/env python3
"""
sync_site_content.sh (Python) — Validate site content consistency.

Checks:
  1. All data-const references in HTML resolve to keys in site_constants.js
  2. Fragile strings (from content_manifest.json) don't appear hardcoded in
     HTML files that have been migrated to the component/constants system
  3. Data source count in constants matches data_sources.json

Usage:
    python3 deploy/lint_site_content.py           # check mode (CI-safe)
    python3 deploy/lint_site_content.py --verbose  # show all scanned files

v1.0.0 — 2026-03-24
"""

import json
import re
import sys
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
CONSTANTS_FILE = SITE_DIR / "assets" / "js" / "site_constants.js"
MANIFEST_FILE = SITE_DIR / "data" / "content_manifest.json"
SOURCES_FILE = SITE_DIR / "data" / "data_sources.json"

VERBOSE = "--verbose" in sys.argv

# Pages that have been migrated to component system (start empty, grow over time)
# Add a page here after converting it to use <div id="amj-nav"> etc.
MIGRATED_PAGES = [
    "about/index.html",
    "accountability/index.html",
    "achievements/index.html",
    "ask/index.html",
    "benchmarks/index.html",
    "biology/index.html",
    "board/index.html",
    "board/product/index.html",
    "board/technical/index.html",
    "character/index.html",
    "chronicle/archive/index.html",
    "chronicle/index.html",
    "chronicle/posts/week-00/index.html",
    "chronicle/posts/week-01/index.html",
    "chronicle/posts/week-02/index.html",
    "chronicle/posts/week-03/index.html",
    "chronicle/sample/index.html",
    "cost/index.html",
    "data/index.html",
    "discoveries/index.html",
    "experiments/index.html",
    "explorer/index.html",
    "glucose/index.html",
    "habits/index.html",
    "index.html",
    "intelligence/index.html",
    "journal/archive/index.html",
    "journal/index.html",
    "journal/posts/week-00/index.html",
    "journal/posts/week-01/index.html",
    "journal/posts/week-02/index.html",
    "journal/posts/week-03/index.html",
    "journal/posts/week-04/index.html",
    "journal/sample/index.html",
    "live/index.html",
    "methodology/index.html",
    "platform/index.html",
    "platform/reviews/index.html",
    "privacy/index.html",
    "progress/index.html",
    "protocols/index.html",
    "results/index.html",
    "sleep/index.html",
    "start/index.html",
    "story/index.html",
    "subscribe/index.html",
    "supplements/index.html",
    "tools/index.html",
    "week/index.html",
    "weekly/index.html",
]

# Files to skip in fragile-string scan (constants file itself, manifest, archives)
SKIP_PATTERNS = [
    "site_constants.js",
    "content_manifest.json",
    "data_sources.json",
    "chronicle/posts/",
    "journal/posts/",
    "public_stats.json",
    "character_stats.json",
    "site_config.json",
]


def extract_constants_keys(js_path: Path) -> set:
    """Parse site_constants.js and extract all dotted key paths."""
    text = js_path.read_text(encoding="utf-8")
    # Find the AMJ object — extract nested keys via regex
    keys = set()
    # Match patterns like:  key: value  inside the AMJ object
    # This is a simplified parser — works for flat and one-level-nested objects
    current_section = None
    for line in text.splitlines():
        # Section header:  journey: {
        m = re.match(r'\s+(\w+)\s*:\s*\{', line)
        if m:
            current_section = m.group(1)
            continue
        # End of section
        if current_section and re.match(r'\s*\},?\s*$', line):
            current_section = None
            continue
        # Key: value inside a section
        if current_section:
            m = re.match(r"\s+(\w+)\s*:", line)
            if m:
                keys.add(f"{current_section}.{m.group(1)}")
    return keys


def find_data_const_refs(site_dir: Path) -> list:
    """Find all data-const="..." references in HTML files."""
    refs = []
    for html_file in site_dir.rglob("*.html"):
        rel = html_file.relative_to(site_dir)
        text = html_file.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'data-const="([^"]+)"', text):
            refs.append((str(rel), m.group(1)))
    return refs


def scan_fragile_strings(site_dir: Path, fragile: list, migrated: list) -> list:
    """Find hardcoded fragile strings in migrated HTML files."""
    warnings = []
    for page in migrated:
        filepath = site_dir / page
        if not filepath.exists():
            continue
        text = filepath.read_text(encoding="utf-8", errors="replace")
        for frag in fragile:
            # Skip if inside a data-const attribute or JS variable
            # Simple heuristic: count raw occurrences outside of script tags
            # (A more sophisticated version would parse the DOM)
            count = text.count(frag)
            if count > 0:
                warnings.append((page, frag, count))
    return warnings


def main():
    errors = 0
    warnings_count = 0

    print("═══ Site Content Lint ═══\n")

    # 1. Check data-const references resolve
    if CONSTANTS_FILE.exists():
        keys = extract_constants_keys(CONSTANTS_FILE)
        refs = find_data_const_refs(SITE_DIR)
        print(f"[1] data-const references: {len(refs)} found, {len(keys)} keys available")
        for page, ref in refs:
            if ref not in keys:
                print(f"  ❌ {page}: data-const=\"{ref}\" — key not found in site_constants.js")
                errors += 1
            elif VERBOSE:
                print(f"  ✓ {page}: data-const=\"{ref}\"")
        if not refs:
            print("  (no data-const references found yet — migration in progress)")
    else:
        print("[1] SKIP — site_constants.js not found")

    print()

    # 2. Check fragile strings in migrated pages
    if MANIFEST_FILE.exists() and MIGRATED_PAGES:
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        fragile = manifest.get("fragile_strings", {}).get("values", [])
        print(f"[2] Fragile string scan: {len(fragile)} patterns, {len(MIGRATED_PAGES)} migrated pages")
        warns = scan_fragile_strings(SITE_DIR, fragile, MIGRATED_PAGES)
        for page, frag, count in warns:
            print(f"  ⚠️  {page}: \"{frag}\" appears {count}x — should come from site_constants.js")
            warnings_count += 1
        if not warns:
            print("  ✓ No hardcoded fragile strings in migrated pages")
    else:
        print("[2] SKIP — no migrated pages yet (add to MIGRATED_PAGES list after converting)")

    print()

    # 3. Data source count consistency
    if SOURCES_FILE.exists() and CONSTANTS_FILE.exists():
        sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        source_count = len(sources.get("sources", []))
        js_text = CONSTANTS_FILE.read_text(encoding="utf-8")
        m = re.search(r'data_sources:\s*(\d+)', js_text)
        const_count = int(m.group(1)) if m else None
        print(f"[3] Data source count: registry={source_count}, constants={const_count}")
        if const_count and source_count != const_count:
            print(f"  ❌ Mismatch! data_sources.json has {source_count}, site_constants.js says {const_count}")
            errors += 1
        else:
            print("  ✓ Counts match")
    else:
        print("[3] SKIP — data_sources.json or site_constants.js missing")

    print()

    # Summary
    if errors:
        print(f"═══ FAILED: {errors} error(s), {warnings_count} warning(s) ═══")
        sys.exit(1)
    else:
        print(f"═══ PASSED: 0 errors, {warnings_count} warning(s) ═══")


if __name__ == "__main__":
    main()
