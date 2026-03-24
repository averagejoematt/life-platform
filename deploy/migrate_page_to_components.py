#!/usr/bin/env python3
"""
migrate_page_to_components.py — Convert an HTML page to use the component system.

Replaces inline nav, footer, bottom-nav, and subscribe CTA with mount-point divs.
Adds script includes for site_constants.js and components.js.

Usage:
    python3 deploy/migrate_page_to_components.py site/about/index.html
    python3 deploy/migrate_page_to_components.py site/about/index.html --dry-run
    python3 deploy/migrate_page_to_components.py --all --dry-run

This is a MECHANICAL transformation — it handles the structural chrome.
Prose changes (data-const attributes on inline content) must be done manually.

v1.0.0 — 2026-03-24
"""

import re
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
ALL_MODE = "--all" in sys.argv

SITE_DIR = Path(__file__).resolve().parent.parent / "site"

# Skip these pages (they have custom layouts or are templates)
SKIP = {
    "404.html",
    "subscribe.html",
    "chronicle/posts/TEMPLATE.html",
    "journal/posts/TEMPLATE.html",
}


def migrate(filepath: Path):
    """Strip inline nav/footer/bottom-nav, replace with mount points."""
    rel = filepath.relative_to(SITE_DIR)
    text = filepath.read_text(encoding="utf-8")
    original = text

    changes = []

    # ── 1. Replace <nav class="nav"> ... </nav> + overlay with mount point ──
    # The nav block starts with <nav class="nav"> and the overlay ends with </div>\n</div>
    # Strategy: find <nav class="nav"> to the closing </div> of nav-overlay
    nav_pattern = r'<nav class="nav">.*?</nav>\s*(?:<!--.*?-->\s*)?<div class="nav-overlay">.*?</div>\s*</div>'
    if re.search(nav_pattern, text, re.DOTALL):
        text = re.sub(nav_pattern, '<div id="amj-nav"></div>', text, count=1, flags=re.DOTALL)
        changes.append("nav + overlay → <div id=\"amj-nav\">")

    # ── 2. Replace <nav class="bottom-nav" ...> ... </nav> with mount point ──
    bottom_nav_pattern = r'<nav class="bottom-nav"[^>]*>.*?</nav>'
    if re.search(bottom_nav_pattern, text, re.DOTALL):
        text = re.sub(bottom_nav_pattern, '<div id="amj-bottom-nav"></div>', text, count=1, flags=re.DOTALL)
        changes.append("bottom-nav → <div id=\"amj-bottom-nav\">")

    # ── 3. Replace <footer class="footer-v2"> ... </footer> with mount point ──
    footer_pattern = r'<footer class="footer-v2">.*?</footer>'
    if re.search(footer_pattern, text, re.DOTALL):
        text = re.sub(footer_pattern, '<div id="amj-footer"></div>', text, count=1, flags=re.DOTALL)
        changes.append("footer → <div id=\"amj-footer\">")

    # ── 4. Replace inline subscribe CTA (email-cta-footer class) with mount point ──
    # Only if not already using amj-subscribe mount
    if 'id="amj-subscribe"' not in text:
        sub_pattern = r'<section class="email-cta-footer[^"]*"[^>]*>.*?</section>\s*(?:<script>.*?</script>)?'
        if re.search(sub_pattern, text, re.DOTALL):
            text = re.sub(sub_pattern, '<div id="amj-subscribe"></div>', text, count=1, flags=re.DOTALL)
            changes.append("subscribe CTA → <div id=\"amj-subscribe\">")

    # ── 5. Replace inline reading-path section with mount point ──
    if 'id="amj-reading-path"' not in text:
        rp_pattern = r'<section class="reading-path"[^>]*>.*?</section>'
        if re.search(rp_pattern, text, re.DOTALL):
            text = re.sub(rp_pattern, '<div id="amj-reading-path"></div>', text, count=1, flags=re.DOTALL)
            changes.append("reading path → <div id=\"amj-reading-path\">")

    # ── 6. Remove duplicate amjSubscribe function definitions ──
    # (now provided by components.js)
    dup_sub_pattern = r'<script>\s*\(function\(\)\s*\{\s*(?://[^\n]*\n\s*)?if\s*\(!window\.amjSubscribe\).*?\}\);\s*\}\)\(\);\s*</script>'
    count_before = len(text)
    text = re.sub(dup_sub_pattern, '', text, flags=re.DOTALL)
    if len(text) < count_before:
        changes.append("removed duplicate amjSubscribe script")

    # ── 7. Add script includes if not already present ──
    if 'site_constants.js' not in text:
        # Insert before closing </body> or before nav.js
        if '<script src="/assets/js/nav.js"></script>' in text:
            text = text.replace(
                '<script src="/assets/js/nav.js"></script>',
                '<script src="/assets/js/site_constants.js"></script>\n<script src="/assets/js/components.js"></script>\n<script src="/assets/js/nav.js"></script>'
            )
        elif '</body>' in text:
            text = text.replace(
                '</body>',
                '<script src="/assets/js/site_constants.js"></script>\n<script src="/assets/js/components.js"></script>\n<script src="/assets/js/nav.js"></script>\n</body>'
            )
        changes.append("added site_constants.js + components.js script tags")

    # ── 8. Remove the inline reading-path block from nav.js (handled by components.js) ──
    # This is in the READING_PATHS section of nav.js — handled separately

    if text == original:
        print(f"  ⏭  {rel} — no changes needed (already migrated or incompatible layout)")
        return False

    if DRY_RUN:
        print(f"  🔍 {rel} — DRY RUN — would make {len(changes)} changes:")
        for c in changes:
            print(f"      • {c}")
        saved = len(original) - len(text)
        print(f"      ({saved:+d} bytes, {saved / len(original) * 100:.1f}% reduction)")
        return True
    else:
        filepath.write_text(text, encoding="utf-8")
        saved = len(original) - len(text)
        print(f"  ✅ {rel} — {len(changes)} changes ({saved:+d} bytes)")
        for c in changes:
            print(f"      • {c}")
        return True


def main():
    print("═══ Page Migration to Component System ═══\n")
    if DRY_RUN:
        print("MODE: DRY RUN (no files will be modified)\n")

    if ALL_MODE:
        files = sorted(SITE_DIR.rglob("*.html"))
        targets = [f for f in files if str(f.relative_to(SITE_DIR)) not in SKIP]
    else:
        # Specific files from command line
        targets = []
        for arg in sys.argv[1:]:
            if arg.startswith("--"):
                continue
            p = Path(arg)
            if not p.is_absolute():
                p = SITE_DIR / arg
            if p.exists():
                targets.append(p)
            else:
                print(f"  ❌ File not found: {arg}")

    if not targets:
        print("Usage:")
        print("  python3 deploy/migrate_page_to_components.py site/about/index.html")
        print("  python3 deploy/migrate_page_to_components.py --all --dry-run")
        sys.exit(1)

    migrated = 0
    for t in targets:
        if migrate(t):
            migrated += 1

    print(f"\n═══ {'Would migrate' if DRY_RUN else 'Migrated'}: {migrated} / {len(targets)} pages ═══")

    if not DRY_RUN and migrated > 0:
        print("\nNext steps:")
        print("  1. Review changes in browser (python3 -m http.server 8000 from site/)")
        print("  2. Add data-const attributes to inline hardcoded values")
        print("  3. Add migrated pages to MIGRATED_PAGES list in deploy/lint_site_content.py")
        print("  4. Run: python3 deploy/lint_site_content.py")
        print("  5. Deploy: aws s3 sync site/ s3://matthew-life-platform/site/ --delete")


if __name__ == "__main__":
    main()
