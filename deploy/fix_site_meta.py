#!/usr/bin/env python3
"""
fix_site_meta.py — Add OG/Twitter meta tags and standardize nav across all site pages.

Usage:
  python3 deploy/fix_site_meta.py --apply
"""

import re
import argparse
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
OG_IMAGE = "https://averagejoematt.com/assets/images/og-image.png"

# Page metadata for OG tags
PAGE_META = {
    "story/index.html": {
        "og:title": "The Story — Matthew Walker",
        "og:description": "302 lbs. January 2026. And a decision to stop optimizing in the dark.",
    },
    "journal/index.html": {
        "og:title": "The Measured Life — Journal",
        "og:description": "Weekly chronicles from 19 data sources. Every number, every failure, every week.",
    },
    "platform/index.html": {
        "og:title": "The Platform — Matthew Walker",
        "og:description": "48 Lambda functions. 95 AI tools. 19 data sources. $10/month. Built by a non-engineer with Claude.",
    },
    "character/index.html": {
        "og:title": "Character Sheet — Matthew Walker",
        "og:description": "7-pillar scoring system tracking sleep, movement, nutrition, metabolic, mind, relationships, consistency.",
    },
    "live/index.html": {
        "og:title": "Transformation Timeline — Matthew Walker",
        "og:description": "Every weigh-in, experiment, and milestone from 302 lbs to goal. Interactive timeline.",
    },
    "explorer/index.html": {
        "og:title": "Correlation Explorer — Matthew Walker",
        "og:description": "23 cross-source correlations. FDR corrected. What actually predicts what in one person's health data.",
    },
    "experiments/index.html": {
        "og:title": "N=1 Experiments — Matthew Walker",
        "og:description": "Real self-experiments with data. Hypothesis, protocol, duration, result — no filtering.",
    },
    "biology/index.html": {
        "og:title": "Genome Risk Dashboard — Matthew Walker",
        "og:description": "110 SNPs mapped to interventions, evidence, and what to monitor.",
    },
    "about/index.html": {
        "og:title": "About — Matthew Walker",
        "og:description": "Senior Director by day. Solo engineer by night. Building the infrastructure to change everything.",
    },
}

# Standard nav HTML
STANDARD_NAV = '''<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
    <a href="/#experiment" class="nav__link">The experiment</a>
    <a href="/platform/" class="nav__link">The platform</a>
    <a href="/journal/" class="nav__link">Journal</a>
    <a href="/character/" class="nav__link">Character</a>
  </div>
  <div class="nav__status">
    <div class="pulse"></div>
    <span>Live</span>
  </div>
</nav>'''

# Standard footer HTML
STANDARD_FOOTER = '''<footer class="footer">
  <div class="footer__brand">AMJ</div>
  <div class="footer__links">
    <a href="/story/" class="footer__link">Story</a>
    <a href="/journal/" class="footer__link">Journal</a>
    <a href="/platform/" class="footer__link">Platform</a>
    <a href="/character/" class="footer__link">Character</a>
    <a href="/subscribe" class="footer__link">Subscribe</a>
  </div>
  <div class="footer__copy">// updated daily by life-platform</div>
</footer>'''


def add_og_tags(html: str, page_rel: str) -> tuple[str, int]:
    """Add OG/Twitter meta tags if missing."""
    changes = 0
    meta = PAGE_META.get(page_rel)
    if not meta:
        return html, 0

    # Check if og:image already present
    if 'og:image' not in html:
        og_block = f'''  <meta property="og:image" content="{OG_IMAGE}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{meta['og:title']}">
  <meta name="twitter:description" content="{meta['og:description']}">
  <meta name="twitter:image" content="{OG_IMAGE}">'''

        # Insert before <title>
        title_match = re.search(r'(\s*<title>)', html)
        if title_match:
            html = html[:title_match.start()] + '\n' + og_block + html[title_match.start():]
            changes += 1

    # Add og:title if missing
    if 'og:title' not in html:
        title_tag = f'  <meta property="og:title" content="{meta["og:title"]}">'
        desc_tag = f'  <meta property="og:description" content="{meta["og:description"]}">'
        type_tag = '  <meta property="og:type" content="website">'

        title_match = re.search(r'(\s*<title>)', html)
        if title_match:
            insert = f'\n{title_tag}\n{desc_tag}\n{type_tag}'
            html = html[:title_match.start()] + insert + html[title_match.start():]
            changes += 1

    return html, changes


def fix_nav(html: str) -> tuple[str, int]:
    """Standardize nav across all pages (skip homepage)."""
    # Match the nav block
    nav_pattern = r'<nav class="nav">.*?</nav>'
    match = re.search(nav_pattern, html, re.DOTALL)
    if not match:
        return html, 0

    old_nav = match.group()
    # Don't touch homepage nav (it has special structure that already works)
    if 'id="experiment"' in html and 'hero' in html:
        return html, 0

    # Check if nav already matches standard
    if 'class="nav__brand">AMJ</a>' in old_nav and '/#experiment' in old_nav:
        return html, 0

    html = html[:match.start()] + STANDARD_NAV + html[match.end():]
    return html, 1


def fix_footer(html: str) -> tuple[str, int]:
    """Standardize footer across all pages (skip homepage)."""
    # Skip homepage
    if 'id="experiment"' in html and 'hero' in html:
        return html, 0

    footer_pattern = r'<footer class="footer">.*?</footer>'
    match = re.search(footer_pattern, html, re.DOTALL)
    if not match:
        return html, 0

    old_footer = match.group()
    if 'Story' in old_footer and 'Subscribe' in old_footer and 'updated daily' in old_footer:
        return html, 0

    html = html[:match.start()] + STANDARD_FOOTER + html[match.end():]
    return html, 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    html_files = list(SITE_DIR.rglob("index.html"))
    # Exclude journal posts template and individual posts for now
    html_files = [f for f in html_files if "TEMPLATE" not in str(f)]

    total = 0
    for path in sorted(html_files):
        rel = str(path.relative_to(SITE_DIR))
        with open(path) as f:
            original = f.read()

        html = original
        changes = 0

        html, c = add_og_tags(html, rel)
        changes += c

        html, c = fix_nav(html)
        changes += c

        html, c = fix_footer(html)
        changes += c

        if changes > 0:
            print(f"  {rel}: {changes} fix(es)")
            if args.apply:
                with open(path, "w") as f:
                    f.write(html)
                print(f"    ✓ Written")
            total += changes

    print(f"\n{'Applied' if args.apply else 'Would apply'} {total} total fixes.")
    if not args.apply and total > 0:
        print("Run with --apply to write.")


if __name__ == "__main__":
    main()
