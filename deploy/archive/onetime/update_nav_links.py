#!/usr/bin/env python3
"""
Batch-update nav dropdowns across all site HTML files.
Adds: /explorer/, /achievements/ to "The Data"; /weekly/ to "Follow"
Run from project root: python3 deploy/update_nav_links.py [--dry-run]
"""
import os, sys, glob

DRY_RUN = '--dry-run' in sys.argv
SITE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'site')

# ── Replacement pairs: (old_str, new_str) ──
# Each pair is applied once per file. Order matters.
REPLACEMENTS = [
    # 1) Desktop dropdown — "The Data": add Explorer + Milestones after Benchmarks
    (
        '<a href="/benchmarks/" class="nav__dropdown-item">Benchmarks</a>',
        '<a href="/benchmarks/" class="nav__dropdown-item">Benchmarks</a>\n        <a href="/explorer/" class="nav__dropdown-item">Explorer</a>\n        <a href="/achievements/" class="nav__dropdown-item">Milestones</a>',
    ),
    # 2) Desktop dropdown — "Follow": add Weekly Snapshots after Weekly Journal
    (
        '<a href="/chronicle/" class="nav__dropdown-item">Weekly Journal</a>',
        '<a href="/chronicle/" class="nav__dropdown-item">Weekly Journal</a>\n        <a href="/weekly/" class="nav__dropdown-item">Weekly Snapshots</a>',
    ),
    # 3) Mobile overlay — "The Data": add Explorer + Milestones after Benchmarks
    (
        '<a href="/benchmarks/" class="nav-overlay__link">Benchmarks</a>',
        '<a href="/benchmarks/" class="nav-overlay__link">Benchmarks</a>\n      <a href="/explorer/" class="nav-overlay__link">Explorer</a>\n      <a href="/achievements/" class="nav-overlay__link">Milestones</a>',
    ),
    # 4) Mobile overlay — "Follow": add Weekly Snapshots after Weekly Journal
    (
        '<a href="/chronicle/" class="nav-overlay__link">Weekly Journal</a>',
        '<a href="/chronicle/" class="nav-overlay__link">Weekly Journal</a>\n      <a href="/weekly/" class="nav-overlay__link">Weekly Snapshots</a>',
    ),
    # 5) Footer — "The Data": add Explorer + Milestones after Progress
    (
        '<a href="/accountability/" class="footer-v2__link">Progress</a>',
        '<a href="/accountability/" class="footer-v2__link">Progress</a>\n      <a href="/explorer/" class="footer-v2__link">Explorer</a>\n      <a href="/achievements/" class="footer-v2__link">Milestones</a>',
    ),
    # 6) Footer — "Follow": add Weekly Snapshots after Weekly Journal
    (
        '<a href="/chronicle/" class="footer-v2__link">Weekly Journal</a>',
        '<a href="/chronicle/" class="footer-v2__link">Weekly Journal</a>\n      <a href="/weekly/" class="footer-v2__link">Weekly Snapshots</a>',
    ),
]

def find_html_files(site_dir):
    """Find all .html files recursively, skip TEMPLATE.html."""
    files = []
    for root, dirs, filenames in os.walk(site_dir):
        for f in filenames:
            if f.endswith('.html') and f != 'TEMPLATE.html':
                files.append(os.path.join(root, f))
    return sorted(files)

def update_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as fh:
        content = fh.read()

    original = content
    applied = []
    skipped = []

    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        # Skip if already has the new link (idempotent)
        # Check for key marker in the new text that wouldn't exist in old
        markers = {
            1: '/explorer/" class="nav__dropdown-item"',
            2: '/weekly/" class="nav__dropdown-item"',
            3: '/explorer/" class="nav-overlay__link"',
            4: '/weekly/" class="nav-overlay__link"',
            5: '/explorer/" class="footer-v2__link"',
            6: '/weekly/" class="footer-v2__link"',
        }
        marker = markers[i]
        if marker in content:
            skipped.append(i)
            continue

        if old in content:
            content = content.replace(old, new, 1)  # replace only first occurrence
            applied.append(i)
        else:
            skipped.append(i)

    if content != original:
        if not DRY_RUN:
            with open(filepath, 'w', encoding='utf-8') as fh:
                fh.write(content)
        return filepath, applied, skipped, True
    return filepath, applied, skipped, False

def main():
    html_files = find_html_files(SITE_DIR)
    print(f"Found {len(html_files)} HTML files in {SITE_DIR}")
    if DRY_RUN:
        print("** DRY RUN — no files will be modified **\n")

    modified = 0
    already_done = 0
    errors = 0

    for f in html_files:
        rel = os.path.relpath(f, SITE_DIR)
        try:
            _, applied, skipped, changed = update_file(f)
            if changed:
                modified += 1
                print(f"  ✅ {rel}  (applied: {applied})")
            elif applied:
                modified += 1
                print(f"  ✅ {rel}  (partial — applied: {applied}, skipped: {skipped})")
            else:
                already_done += 1
                # Only print if all 6 were skipped because already present
                if all(s in skipped for s in range(1,7)):
                    pass  # silent — already up to date
                else:
                    print(f"  ⚪ {rel}  (no matching nav patterns)")
        except Exception as e:
            errors += 1
            print(f"  ❌ {rel}  ERROR: {e}")

    print(f"\nDone: {modified} modified, {already_done} already current, {errors} errors")
    if DRY_RUN:
        print("Re-run without --dry-run to apply changes.")

if __name__ == '__main__':
    main()
