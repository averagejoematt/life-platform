#!/usr/bin/env python3
"""Re-flatten every v4 page's chrome to the single source in `v4_chrome.py` (#1009).

The doors nav and `.site-foot` footer were copy-pasted across ~75 site HTML files and
drifted. This regenerator detects each page's DELIBERATE per-page nav state — which door
is current (`aria-current="page"`) and whether the follow pill is present — then replaces
the page's `<nav class="doors">…</nav>` and `<footer class="site-foot">…</footer>` with
the canonical partial output for that state. Everything else on the page is untouched.

It is idempotent (running twice is a no-op) and is the AUTHORITATIVE post-build chrome
pass: run it after any `v4_build_*` build so generator-local chrome can't re-drift.

  python3 scripts/v4_apply_chrome.py            # rewrite in place, print summary
  python3 scripts/v4_apply_chrome.py --check    # exit 1 if any page would change (CI)

Excludes `site/legacy/**` (the frozen old site — never touched).
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v4_chrome  # noqa: E402

SITE_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site")

# The doors nav is terminated by its theme-toggle <button>, then (canonically) </nav>.
# We anchor on the toggle and make </nav> OPTIONAL because one page (now/index.html)
# ships a doors nav with no </nav> tag (the browser auto-closes it at the parent </div>);
# a plain `<nav class="doors">.*?</nav>` there over-matches into downstream markup.
NAV_RE = re.compile(r'<nav class="doors".*?<button class="theme-toggle"[^>]*>.*?</button>(?:\s*</nav>)?', re.DOTALL)
NAV_OPEN = '<nav class="doors"'
FOOT_RE = re.compile(r'<footer class="site-foot".*?</footer>', re.DOTALL)
CURRENT_RE = re.compile(r'<a href="([^"]+)"[^>]*aria-current="page"')
FOLLOW_RE = re.compile(r'class="nav-follow"')


def iter_html_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        # prune the frozen legacy tree
        dirnames[:] = [d for d in dirnames if not (dirpath == root and d == "legacy")]
        if os.sep + "legacy" + os.sep in dirpath + os.sep:
            continue
        for name in sorted(filenames):
            if name.endswith(".html"):
                yield os.path.join(dirpath, name)


def detect_nav_state(nav_html: str):
    """Return (current_door, with_follow) for an existing doors nav."""
    m = CURRENT_RE.search(nav_html)
    current_door = m.group(1) if m else None
    with_follow = bool(FOLLOW_RE.search(nav_html))
    return current_door, with_follow


def rewrite(html: str):
    """Return (new_html, nav_changed, foot_changed, door, follow, gained_icons)."""
    nav_changed = foot_changed = gained_icons = False
    door = None
    follow = False

    nav_m = NAV_RE.search(html)
    if NAV_OPEN in html and not nav_m:
        raise RuntimeError('found a `<nav class="doors"` with no theme-toggle terminator — refusing to guess its boundary')
    if nav_m:
        old_nav = nav_m.group(0)
        door, follow = detect_nav_state(old_nav)
        new_nav = v4_chrome.doors_nav(door, follow)
        if new_nav != old_nav:
            nav_changed = True
            gained_icons = "ico-door" not in old_nav
            html = html[: nav_m.start()] + new_nav + html[nav_m.end() :]

    foot_m = FOOT_RE.search(html)
    if foot_m:
        old_foot = foot_m.group(0)
        new_foot = v4_chrome.site_footer()
        if new_foot != old_foot:
            foot_changed = True
            html = html[: foot_m.start()] + new_foot + html[foot_m.end() :]

    return html, nav_changed, foot_changed, door, follow, gained_icons


def main() -> int:
    ap = argparse.ArgumentParser(description="Flatten site chrome to v4_chrome.py")
    ap.add_argument("--check", action="store_true", help="exit 1 if any page would change (no writes)")
    args = ap.parse_args()

    nav_changed = []
    foot_changed = []
    gained_icons = []
    by_door: dict[str | None, int] = {}
    follow_count = 0
    total = 0

    for path in iter_html_files(SITE_ROOT):
        original = open(path, encoding="utf-8").read()
        if '<nav class="doors"' not in original and '<footer class="site-foot"' not in original:
            continue
        total += 1
        new, nc, fc, door, follow, gi = rewrite(original)
        if '<nav class="doors"' in original:
            by_door[door] = by_door.get(door, 0) + 1
            if follow:
                follow_count += 1
        rel = os.path.relpath(path, SITE_ROOT)
        if nc:
            nav_changed.append(rel)
        if fc:
            foot_changed.append(rel)
        if gi:
            gained_icons.append(rel)
        if new != original and not args.check:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)

    print(f"Scanned {total} chrome-bearing pages under {SITE_ROOT} (legacy excluded).")
    print(f"  nav rewritten:    {len(nav_changed)}")
    print(f"  footer rewritten: {len(foot_changed)}")
    print(f"  icon-less navs that GAINED door icons: {len(gained_icons)}")
    for rel in gained_icons:
        print(f"      + {rel}")
    print("  nav current-door buckets (detected & preserved):")
    for door in sorted(by_door, key=lambda d: (d is None, d)):
        print(f"      {door if door is not None else '(none)':<12} {by_door[door]}")
    print(f"  follow-pill pages (detected & preserved): {follow_count}")

    if args.check and (nav_changed or foot_changed):
        print("\nCHECK FAILED: chrome is out of sync with v4_chrome.py — run without --check.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
